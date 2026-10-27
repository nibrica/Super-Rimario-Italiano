"""Skip stages whose inputs are unchanged.

A stage's cache key hashes its name, the source code of its module and of
every ``rimario_build`` module that module uses (always including schema,
config and text), the environment (``uv.lock`` and the Python version), and
its ``deps``: the keys of upstream stages, the sha256 / version of raw source
files, or the hash of the glue code that builds the stage's inputs. Outputs (a DataFrame, or a dict of
DataFrames and JSON scalars) are stored as parquet under
``data/cache/<stage>/<key>/``; only the latest key of each stage is kept.
"""

import hashlib
import importlib
import json
import logging
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path
from types import ModuleType

import polars as pl

from . import config

log = logging.getLogger(__name__)

CACHE_FORMAT = 1                   # bump to invalidate every cached output
PACKAGE = __name__.rpartition(".")[0]
SHARED_MODULES = ("schema", "config", "text")
MANIFEST = "manifest.json"

Output = pl.DataFrame | dict


class CacheMiss(RuntimeError):
    """A stage has no cached output and computing it is not allowed."""


def _used_modules(module: ModuleType) -> set[ModuleType]:
    """``module`` plus every package module it references, transitively."""
    shared = [importlib.import_module(f"{PACKAGE}.{m}") for m in SHARED_MODULES]
    seen: set[ModuleType] = set()
    todo = [module, *shared]
    while todo:
        mod = todo.pop()
        if mod in seen or not getattr(mod, "__file__", None):
            continue
        seen.add(mod)
        for value in vars(mod).values():
            name = value.__name__ if isinstance(value, ModuleType) else getattr(value, "__module__", None)
            if isinstance(name, str) and name.startswith(PACKAGE + ".") and name in sys.modules:
                todo.append(sys.modules[name])
    return seen


def code_hash(fn: Callable) -> str:
    """sha256 of the source of every package module ``fn`` depends on."""
    h = hashlib.sha256()
    for mod in sorted(_used_modules(sys.modules[fn.__module__]), key=lambda m: m.__name__):
        h.update(mod.__name__.encode() + b"\0" + Path(mod.__file__).read_bytes() + b"\0")
    return h.hexdigest()


@cache
def environment() -> str:
    """sha256 of ``uv.lock`` (library versions) and the Python version."""
    lock = config.UV_LOCK.read_bytes() if config.UV_LOCK.exists() else b""
    return f"{hashlib.sha256(lock).hexdigest()}:py{sys.version_info.major}.{sys.version_info.minor}"


def stage_key(name: str, fn: Callable, deps: Iterable[str] = ()) -> str:
    payload = [CACHE_FORMAT, name, f"{fn.__module__}.{fn.__qualname__}", code_hash(fn), environment(), list(deps)]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:24]


def describe(out: Output) -> str:
    """Row counts of a stage output, for the log."""
    if isinstance(out, pl.DataFrame):
        return f"{out.height:,} rows"
    return ", ".join(
        f"{k}={v.height:,}" if isinstance(v, pl.DataFrame) else f"{k}={v!r}" for k, v in out.items()
    )


def save(name: str, key: str, out: Output, root: Path = config.CACHE_DIR) -> None:
    """Store ``out`` under ``root/name/key`` and drop the stage's older keys."""
    stage_dir = root / name
    stage_dir.mkdir(parents=True, exist_ok=True)
    tmp = stage_dir / f".{key}.tmp{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    if isinstance(out, pl.DataFrame):
        out.write_parquet(tmp / "data.parquet")
        manifest = {"kind": "frame"}
    else:
        tables, values = [], {}
        for k, v in out.items():
            if isinstance(v, pl.DataFrame):
                v.write_parquet(tmp / f"{k}.parquet")
                tables.append(k)
            else:
                values[k] = v
        manifest = {"kind": "dict", "order": list(out), "tables": tables, "values": values}
    (tmp / MANIFEST).write_text(json.dumps(manifest))
    final = stage_dir / key
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    for p in stage_dir.iterdir():    # older keys and temp dirs of interrupted saves
        if p.name != key and (not p.name.startswith(".") or ".tmp" in p.name):
            shutil.rmtree(p, ignore_errors=True)


def load(name: str, key: str, root: Path = config.CACHE_DIR) -> Output | None:
    """The cached output of ``name`` under ``key``, or None."""
    d = root / name / key
    try:
        manifest = json.loads((d / MANIFEST).read_text())
    except FileNotFoundError:
        return None
    if manifest["kind"] == "frame":
        return pl.read_parquet(d / "data.parquet")
    values = manifest["values"]
    return {k: pl.read_parquet(d / f"{k}.parquet") if k in manifest["tables"] else values[k]
            for k in manifest["order"]}


def lookup(
    name: str, fn: Callable, deps: Iterable[str] = (), *, force: bool = False,
    cache_only: bool = False, root: Path = config.CACHE_DIR,
) -> tuple[str, Output | None]:
    """(key, cached output or None); logs a hit, raises CacheMiss if ``cache_only``."""
    t0 = time.perf_counter()
    key = stage_key(name, fn, deps)
    out = None if force else load(name, key, root)
    if out is not None:
        log.info("stage %s: cached, %.1fs (%s)", name, time.perf_counter() - t0, describe(out))
    elif cache_only:
        raise CacheMiss(f"stage {name}: no cached output for the current inputs; run `rimario-build build` first")
    return key, out


def compute(name: str, fn: Callable, args: tuple, key: str, root: Path = config.CACHE_DIR) -> Output:
    """Run the stage, store its output and log duration and row counts."""
    t0 = time.perf_counter()
    out = fn(*args)
    save(name, key, out, root)
    log.info("stage %s: computed, %.1fs (%s)", name, time.perf_counter() - t0, describe(out))
    return out


def compute_quietly(name: str, fn: Callable, args: tuple, key: str, root: Path = config.CACHE_DIR) -> float:
    """``compute`` for a worker process: returns the duration, not the output."""
    t0 = time.perf_counter()
    save(name, key, fn(*args), root)
    return time.perf_counter() - t0


def run_stage(
    name: str, fn: Callable, args: tuple = (), deps: Iterable[str] = (), *,
    force: bool = False, cache_only: bool = False, root: Path = config.CACHE_DIR,
) -> tuple[Output, str]:
    """Return (output, key) of ``fn(*args)``, from the cache when its inputs are unchanged."""
    key, out = lookup(name, fn, deps, force=force, cache_only=cache_only, root=root)
    if out is None:
        out = compute(name, fn, args, key, root)
    return out, key
