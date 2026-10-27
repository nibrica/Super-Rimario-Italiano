"""Fetch the latest version of every source (OVERHAUL-PLAN §2).

Sources are declared in ``sources.toml``; ``sources.lock.json`` records, per
source id, what the last fetch resolved to::

    {"kaikki_en": {"url", "file", "etag", "last_modified", "sha256", "size", "fetched_at"},
     "wordfreq":  {"package", "version", "url", "fetched_at"}, ...}

An entry restored from a source's repository ``mirror`` (used when upstream
can't serve the file and there is no usable local copy) also has
``"via": "mirror"`` and ``"mirror"`` (its path, relative to dictionary/).

``fetched_at`` (UTC, ISO 8601) changes only when the content changes, so an
unchanged source leaves the lock file untouched. Downloads are data only:
nothing fetched is ever executed or extracted here.
"""

import hashlib
import http.client
import importlib.metadata
import json
import logging
import os
import re
import shutil
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

CHUNK_BYTES = 1 << 20
PROGRESS_MIN_BYTES = 20 << 20      # log download progress above this size
PROGRESS_STEP = 0.1                # ...every 10%
PART_SUFFIX = ".part"


class FetchError(RuntimeError):
    """A source can't be fetched and there is no local copy to fall back on."""


class Unreachable(Exception):
    """The server can't be reached or doesn't serve a usable file."""


def load_sources(path: Path = config.SOURCES_TOML) -> list[dict]:
    """The ``[[source]]`` tables of ``sources.toml``, in file order."""
    return tomllib.loads(path.read_text("utf-8"))["source"]


def read_json(path: Path) -> dict:
    """A JSON state file (lock, fetch warnings, hash memo); empty if missing."""
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def write_json(path: Path, obj: dict) -> None:
    """Write ``obj`` atomically as sorted, indented JSON (byte-identical when unchanged)."""
    atomic_write(path, (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def load_lock(path: Path = config.SOURCES_LOCK) -> dict[str, dict]:
    """``sources.lock.json`` as {source id: entry}; empty if missing."""
    return read_json(path)


def write_lock(lock: dict[str, dict], path: Path = config.SOURCES_LOCK) -> None:
    write_json(path, lock)


def atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to a temp file next to ``path`` (mode 644), then rename it into place."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = _temp_file(path)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK_BYTES):
            h.update(chunk)
    return h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_all(
    sources: list[dict], lock: dict[str, dict], raw_dir: Path = config.RAW_DIR,
    only: str | None = None, base: Path = config.ROOT, lock_path: Path | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Fetch every source (or only ``only``) into ``raw_dir/<id>/``.

    Returns the new lock (entries of undeclared sources dropped) and the
    warnings by source id. Raises FetchError if a source is unreachable and
    has no local copy. ``base`` is the directory mirror paths are relative to.
    With ``lock_path``, the lock is written there after each fetched source,
    so a fetch that fails partway leaves it describing the files on disk.
    """
    ids = [s["id"] for s in sources]
    if only is not None and only not in ids:
        raise ValueError(f"unknown source {only!r}; known: {', '.join(ids)}")
    new = {k: v for k, v in lock.items() if k in ids}
    warnings: dict[str, str] = {}
    for src in sources:
        if only is None or src["id"] == only:
            new[src["id"]], warning = fetch_source(src, lock.get(src["id"]), raw_dir / src["id"], base)
            if warning:
                log.warning(warning)
                warnings[src["id"]] = warning
            if lock_path is not None:
                write_lock(new, lock_path)
    return new, warnings


def fetch_source(src: dict, old: dict | None, dest: Path, base: Path = config.ROOT) -> tuple[dict, str | None]:
    """Bring one source up to date; returns (lock entry, warning or None)."""
    if src["resolver"] == "package":
        return _package(src, old), None
    try:
        url, file = resolve(src, _locked_year(src, old, dest))
        return _download(src["id"], url, file, old, dest), None
    except Unreachable as e:
        local = _local_copy(dest, old)
        stale_mirror = old and old.get("via") == "mirror" and old.get("sha256") != src.get("mirror_sha256")
        if src.get("mirror") and (local is None or stale_mirror):
            return _from_mirror(src, old, dest, base, e)
        if local is None:
            raise FetchError(
                f"{src['id']}: {e}, and there is no local copy in {dest}. "
                "Check the network connection or the URL in sources.toml."
            ) from None
        entry = old if _matches(old, local) else _local_entry(src, local, old)
        return entry, f"{src['id']}: {e}; using the local copy {local.name} (fetched {entry.get('fetched_at')})"


def _from_mirror(src: dict, old: dict | None, dest: Path, base: Path, e: Exception) -> tuple[dict, str | None]:
    """Restore the repository mirror of ``src`` into ``dest``; warn if upstream has moved on."""
    mirror = base / src["mirror"]
    if not mirror.is_file():
        raise FetchError(f"{src['id']}: {e}, and the mirror {mirror} is missing") from None
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / mirror.name
    fd, tmp = _temp_file(target)
    try:
        os.close(fd)
        shutil.copyfile(mirror, tmp)
        sha256 = sha256_file(tmp)
        if sha256 != src.get("mirror_sha256"):
            raise FetchError(f"{src['id']}: the mirror {mirror} has sha256 {sha256}, "
                             f"but sources.toml says {src.get('mirror_sha256')}")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    _prune(dest, target.name)
    log.info("%s: %s; restored %s from the mirror %s", src["id"], e, target.name, src["mirror"])
    url = src["url"]
    entry = _entry(url, target, {"Last-Modified": src.get("mirror_last_modified")}, sha256, old)
    entry |= {"via": "mirror", "mirror": src["mirror"]}
    try:
        status, head = _head(url)
    except Unreachable:
        return entry, None
    if status == 200 and (head.get("Last-Modified") != src.get("mirror_last_modified")
                          or _content_length(head) != entry["size"]):
        return entry, (f"{src['id']}: upstream has a newer version (Last-Modified {head.get('Last-Modified')}) "
                       f"than the mirror {src['mirror']}; refresh the mirror")
    return entry, None


def resolve(src: dict, min_year: int | None = None) -> tuple[str, str]:
    """The (URL, local file name) of the newest version of an http/leipzig source.

    Leipzig years are probed down to ``min_year`` (default: the source's);
    only HTTP 404/410 mean "this year doesn't exist".
    """
    if src["resolver"] == "http":
        return src["url"], src["file"]
    if src["resolver"] != "leipzig":
        raise ValueError(f"{src['id']}: unknown resolver {src['resolver']!r}")
    first, last = datetime.now(timezone.utc).year, min_year or int(src["min_year"])
    for year in range(first, last - 1, -1):
        url = src["url"].format(year=year)
        status, _ = _head(url)
        if status == 200:
            log.info("%s: newest year is %d", src["id"], year)
            return url, src["file"].format(year=year)
        if status not in (404, 410):
            raise Unreachable(f"HEAD {url} returned HTTP {status}")
    raise Unreachable(f"no year between {last} and {first} exists at {src['url']}")


def _year(src: dict, file: str) -> int | None:
    """The year in a leipzig file name (``file`` pattern with {year}), or None."""
    pattern = re.escape(src["file"]).replace(re.escape("{year}"), r"(\d{4})")
    m = re.fullmatch(pattern, file)
    return int(m.group(1)) if m else None


def _locked_year(src: dict, old: dict | None, dest: Path) -> int | None:
    """Leipzig: the locked year if its file is on disk (never downgrade below it), else None."""
    if src["resolver"] != "leipzig" or not old or not old.get("file") or not (dest / old["file"]).is_file():
        return None
    return _year(src, old["file"])


def _package(src: dict, old: dict | None) -> dict:
    version = importlib.metadata.version(src["package"])
    if old and old.get("version") == version:
        return old
    log.info("%s: installed version %s", src["id"], version)
    return {
        "package": src["package"], "version": version, "fetched_at": utc_now(),
        "url": f"https://pypi.org/project/{src['package']}/{version}/",
    }


def _request(url: str, method: str = "GET", headers: dict | None = None):
    req = urllib.request.Request(
        url, method=method, headers={"User-Agent": config.HTTP_USER_AGENT, **(headers or {})}
    )
    return urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_S)


def _head(url: str) -> tuple[int, Mapping[str, str]]:
    """(status, headers) of a HEAD request; raises Unreachable on network errors.

    Headers stay an ``HTTPMessage``, whose lookups are case-insensitive.
    """
    try:
        with _request(url, "HEAD") as resp:
            return resp.status, resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers or Message()
    except (OSError, http.client.HTTPException) as e:
        raise Unreachable(f"can't reach {url} ({_reason(e)})") from None


def _reason(e: Exception) -> str:
    return str(getattr(e, "reason", None) or e)


def _matches(entry: dict | None, path: Path) -> bool:
    """True if the lock ``entry`` describes the local file ``path`` (name and size)."""
    return bool(entry) and entry.get("file") == path.name and entry.get("size") == path.stat().st_size


def _entry(url: str, path: Path, headers: Mapping[str, str], sha256: str, old: dict | None) -> dict:
    keep = old if old and old.get("sha256") == sha256 else None
    return {
        "url": url, "file": path.name, "sha256": sha256, "size": path.stat().st_size,
        "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified"),
        "fetched_at": keep["fetched_at"] if keep else utc_now(),
    }


def _download(sid: str, url: str, file: str, old: dict | None, dest: Path) -> dict:
    """Conditional GET of ``url`` into ``dest/file``; returns the lock entry."""
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / file
    headers: dict[str, str] = {}
    if target.is_file() and old and old.get("url") == url and _matches(old, target):
        if old.get("etag"):
            headers["If-None-Match"] = old["etag"]
        if old.get("last_modified"):
            headers["If-Modified-Since"] = old["last_modified"]
    elif target.is_file():
        # A local file the lock doesn't describe (e.g. downloaded by hand):
        # adopt it if the server's file has the same size, else download.
        status, head = _head(url)
        if status == 200 and _content_length(head) == target.stat().st_size:
            log.info("%s: adopting the local %s (same size as the server's)", sid, file)
            entry = _entry(url, target, head, sha256_file(target), old)
            _prune(dest, file)
            return entry
    try:
        resp = _request(url, headers=headers)
    except urllib.error.HTTPError as e:
        if e.code == 304:
            log.info("%s: up to date (%s)", sid, file)
            _prune(dest, file)
            return old
        if headers and _unchanged(url, old):
            # Some servers refuse automated GETs (morphit shows a bot check)
            # but answer HEAD: the locked version is still the current one.
            log.info("%s: up to date (%s; HEAD, GET returned HTTP %d)", sid, file, e.code)
            _prune(dest, file)
            return old
        raise Unreachable(f"GET {url} returned HTTP {e.code}") from None
    except (OSError, http.client.HTTPException) as e:
        raise Unreachable(f"can't reach {url} ({_reason(e)})") from None
    with resp:
        sha256 = _save(sid, resp, target)
        entry = _entry(url, target, resp.headers, sha256, old)
    _prune(dest, file)
    return entry


def _unchanged(url: str, old: dict) -> bool:
    """True if a HEAD request shows the locked validators (ETag, else Last-Modified) and size."""
    try:
        status, head = _head(url)
    except Unreachable:
        return False
    validator, header = ("etag", "ETag") if old.get("etag") else ("last_modified", "Last-Modified")
    return (status == 200 and head.get(header) == old[validator]
            and _content_length(head) == old.get("size"))


def _content_length(headers: Mapping[str, str]) -> int | None:
    value = headers.get("Content-Length")
    return int(value) if value and value.isdigit() else None


def _save(sid: str, resp, target: Path) -> str:
    """Stream ``resp`` to a temp file, verify size, hash, rename to ``target``."""
    expected = _content_length(resp.headers)
    log.info("%s: downloading %s (%s)", sid, target.name,
             f"{expected / 1e6:.1f} MB" if expected else "unknown size")
    fd, tmp = _temp_file(target)
    h, size, next_log = hashlib.sha256(), 0, PROGRESS_STEP
    try:
        with os.fdopen(fd, "wb") as f:
            while chunk := resp.read(CHUNK_BYTES):
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
                if expected and expected >= PROGRESS_MIN_BYTES and size >= next_log * expected:
                    log.info("%s: %3.0f%% of %.1f MB", sid, 100 * size / expected, expected / 1e6)
                    next_log += PROGRESS_STEP
        if expected is not None and size != expected:
            raise Unreachable(f"incomplete download of {target.name}: {size} of {expected} bytes")
        os.replace(tmp, target)
    except (OSError, http.client.HTTPException) as e:
        raise Unreachable(f"download of {target.name} failed ({_reason(e)})") from None
    finally:
        tmp.unlink(missing_ok=True)
    log.info("%s: saved %s (%.1f MB, sha256 %s)", sid, target.name, size / 1e6, h.hexdigest()[:12])
    return h.hexdigest()


def _temp_file(target: Path) -> tuple[int, Path]:
    """A temp file next to ``target`` (same filesystem: atomic rename), mode 644."""
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=PART_SUFFIX)
    os.fchmod(fd, 0o644)
    return fd, Path(name)


def _prune(dest: Path, keep: str) -> None:
    """Keep only the current version: delete every other file in ``dest``."""
    for p in dest.iterdir():
        if p.is_file() and p.name != keep:
            log.info("%s: removing old file %s", dest.name, p.name)
            p.unlink()


def _local_copy(dest: Path, old: dict | None) -> Path | None:
    """The local file to fall back on: the locked one, else the newest by name."""
    if old and old.get("file") and (dest / old["file"]).is_file():
        return dest / old["file"]
    files = sorted(p for p in dest.glob("*") if p.is_file() and not p.name.endswith(PART_SUFFIX)) if dest.is_dir() else []
    return files[-1] if files else None


def _local_entry(src: dict, path: Path, old: dict | None) -> dict:
    """Lock entry for a local file the lock doesn't describe (offline fallback)."""
    url = src["url"]
    if "{year}" in src["file"] and (year := _year(src, path.name)):
        url = url.format(year=year)
    return _entry(url, path, {}, sha256_file(path), old)
