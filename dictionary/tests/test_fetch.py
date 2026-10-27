"""fetch.py (conditional download, lock, fallback), cache.py and the pipeline wiring.

No internet: a local http.server serves the "sources".
"""

import hashlib
import http.server
import importlib.metadata
import sys
import threading
import types
from datetime import datetime, timezone

import polars as pl
import pytest

from rimario_build import cache, config, fetch, pipeline, schema

LAST_MODIFIED = "Wed, 12 Feb 2025 18:47:02 GMT"


class Server(http.server.ThreadingHTTPServer):
    """Serves ``files`` {path: bytes} with ETags; records (method, path, headers)."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.files: dict[str, bytes] = {}
        self.requests: list[tuple[str, str, dict]] = []
        self.short: set[str] = set()      # paths whose body is cut short
        self.refuse_get: set[str] = set()  # paths whose GET returns 402 (bot check)
        self.forbid: set[str] = set()      # paths answering 403 (rate limit, WAF)
        self.lowercase = False             # send header names in lowercase

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}{path}"

    def gets(self) -> list[str]:
        return [p for m, p, _ in self.requests if m == "GET"]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _serve(self, body: bool):
        srv: Server = self.server
        srv.requests.append((self.command, self.path, dict(self.headers)))
        data = srv.files.get(self.path)
        if self.path in srv.forbid:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if data is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        etag = '"' + hashlib.sha256(data).hexdigest()[:16] + '"'
        if body and self.path in srv.refuse_get:
            self.send_response(402)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if body and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.end_headers()
            return
        self.send_response(200)
        for name, value in (("Content-Length", str(len(data))), ("ETag", etag), ("Last-Modified", LAST_MODIFIED)):
            self.send_header(name.lower() if srv.lowercase else name, value)
        self.end_headers()
        if body:
            self.wfile.write(data[: len(data) // 2] if self.path in srv.short else data)

    def do_GET(self):
        self._serve(True)

    def do_HEAD(self):
        self._serve(False)


@pytest.fixture
def server():
    srv = Server()
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def http_source(server: Server, sid: str = "src", file: str = "data.txt") -> dict:
    return {"id": sid, "resolver": "http", "url": server.url(f"/{file}"), "file": file}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- fetch -------------------------------------------------------------------

def test_download_then_not_modified(server, tmp_path):
    server.files["/data.txt"] = b"v1 " * 1000
    src = http_source(server)
    lock, warnings = fetch.fetch_all([src], {}, tmp_path)
    entry = lock["src"]
    assert warnings == {}
    assert (tmp_path / "src" / "data.txt").read_bytes() == server.files["/data.txt"]
    assert entry["sha256"] == sha(server.files["/data.txt"]) and entry["size"] == 3000
    assert entry["etag"] and entry["last_modified"] == LAST_MODIFIED and entry["url"] == src["url"]
    assert entry["file"] == "data.txt" and entry["fetched_at"].endswith("Z")
    assert list((tmp_path / "src").iterdir()) == [tmp_path / "src" / "data.txt"]   # no temp file left

    lock2, _ = fetch.fetch_all([src], lock, tmp_path)
    assert lock2 == lock
    method, _, headers = server.requests[-1]
    assert method == "GET" and headers["If-None-Match"] == entry["etag"]
    assert headers["If-Modified-Since"] == LAST_MODIFIED


def test_changed_source_is_downloaded_again(server, tmp_path):
    server.files["/data.txt"] = b"old"
    src = http_source(server)
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    server.files["/data.txt"] = b"new content"
    lock2, _ = fetch.fetch_all([src], lock, tmp_path)
    assert (tmp_path / "src" / "data.txt").read_bytes() == b"new content"
    assert lock2["src"]["sha256"] == sha(b"new content") and lock2["src"]["etag"] != lock["src"]["etag"]


def test_adopts_local_file_without_lock_when_size_matches(server, tmp_path):
    data = b"pre-downloaded"
    server.files["/data.txt"] = data
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "data.txt").write_bytes(data)
    (tmp_path / "src" / "stale.txt").write_bytes(b"old version")
    lock, _ = fetch.fetch_all([http_source(server)], {}, tmp_path)
    assert server.gets() == []
    assert lock["src"]["sha256"] == sha(data) and lock["src"]["etag"]
    assert sorted(p.name for p in (tmp_path / "src").iterdir()) == ["data.txt"]


def test_local_file_of_other_size_is_replaced(server, tmp_path):
    server.files["/data.txt"] = b"server version"
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "data.txt").write_bytes(b"partial")
    lock, _ = fetch.fetch_all([http_source(server)], {}, tmp_path)
    assert server.gets() == ["/data.txt"]
    assert (tmp_path / "src" / "data.txt").read_bytes() == b"server version"


def test_unreachable_uses_local_copy_with_warning(server, tmp_path):
    server.files["/data.txt"] = b"cached"
    src = http_source(server)
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    del server.files["/data.txt"]                       # now 404
    lock2, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert lock2 == lock
    assert "HTTP 404" in warnings["src"] and "local copy data.txt" in warnings["src"]

    offline = {**src, "url": "http://127.0.0.1:9/data.txt"}   # nothing listens on port 9
    lock3, warnings = fetch.fetch_all([offline], {}, tmp_path)   # no lock entry: hash it
    assert "can't reach" in warnings["src"]
    assert lock3["src"]["sha256"] == sha(b"cached") and lock3["src"]["etag"] is None


def test_refused_get_checks_the_version_with_head(server, tmp_path):
    server.files["/data.txt"] = b"v1"
    src = http_source(server)
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    server.refuse_get.add("/data.txt")
    lock2, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert warnings == {} and lock2 == lock               # HEAD shows the same version
    server.files["/data.txt"] = b"v2"
    lock3, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert "HTTP 402" in warnings["src"] and lock3 == lock  # newer but can't be downloaded


def mirrored(server: Server, tmp_path, data: bytes, mirror_sha: str | None = None) -> dict:
    (tmp_path / "repo" / "mirror").mkdir(parents=True)
    (tmp_path / "repo" / "mirror" / "m.tgz").write_bytes(data)
    return {"id": "m", "resolver": "http", "url": server.url("/m.tgz"), "file": "m.tgz",
            "mirror": "mirror/m.tgz", "mirror_sha256": mirror_sha or sha(data),
            "mirror_last_modified": LAST_MODIFIED}


def test_mirror_restores_missing_file_when_upstream_refuses(server, tmp_path):
    data = b"mirrored archive"
    server.files["/m.tgz"] = data
    server.refuse_get.add("/m.tgz")
    src, raw, base = mirrored(server, tmp_path, data), tmp_path / "raw", tmp_path / "repo"
    lock, warnings = fetch.fetch_all([src], {}, raw, base=base)
    assert warnings == {}                                     # upstream HEAD matches the mirror
    assert (raw / "m" / "m.tgz").read_bytes() == data
    entry = lock["m"]
    assert entry["via"] == "mirror" and entry["mirror"] == "mirror/m.tgz" and entry["sha256"] == sha(data)
    assert entry["last_modified"] == LAST_MODIFIED and entry["url"] == src["url"]
    assert fetch.fetch_all([src], lock, raw, base=base) == (lock, {})    # then up to date via HEAD

    (raw / "m" / "m.tgz").unlink()
    server.files["/m.tgz"] = b"newer upstream archive"
    lock2, warnings = fetch.fetch_all([src], lock, raw, base=base)
    assert "refresh the mirror" in warnings["m"] and lock2 == lock


def test_mirror_with_wrong_sha256_is_an_error(server, tmp_path):
    src = mirrored(server, tmp_path, b"tampered", mirror_sha=sha(b"original"))
    with pytest.raises(fetch.FetchError, match="sha256"):
        fetch.fetch_all([src], {}, tmp_path / "raw", base=tmp_path / "repo")
    assert list((tmp_path / "raw" / "m").iterdir()) == []


def test_unreachable_without_local_copy_aborts(tmp_path):
    src = {"id": "src", "resolver": "http", "url": "http://127.0.0.1:9/x", "file": "x"}
    with pytest.raises(fetch.FetchError, match="no local copy"):
        fetch.fetch_all([src], {}, tmp_path)


def test_incomplete_download_keeps_previous_file(server, tmp_path):
    server.files["/data.txt"] = b"v1"
    src = http_source(server)
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    server.files["/data.txt"] = b"version two, longer"
    server.short.add("/data.txt")
    lock2, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert "src" in warnings and lock2 == lock
    assert [p.name for p in (tmp_path / "src").iterdir()] == ["data.txt"]
    assert (tmp_path / "src" / "data.txt").read_bytes() == b"v1"


def test_lowercase_headers_keep_validators_and_size_check(server, tmp_path):
    server.lowercase = True
    server.files["/data.txt"] = b"v1"
    src = http_source(server)
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    assert lock["src"]["etag"] and lock["src"]["last_modified"] == LAST_MODIFIED
    server.files["/data.txt"] = b"version two, longer"
    server.short.add("/data.txt")
    lock2, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert "incomplete download" in warnings["src"] and lock2 == lock


def test_leipzig_uses_newest_year_and_prunes_older(server, tmp_path):
    year = datetime.now(timezone.utc).year
    server.files[f"/news_{year - 2}.tgz"] = b"older"
    server.files[f"/news_{year - 1}.tgz"] = b"newest"
    (tmp_path / "news").mkdir()
    (tmp_path / "news" / f"news_{year - 2}.tgz").write_bytes(b"older")
    src = {"id": "news", "resolver": "leipzig", "url": server.url("/news_{year}.tgz"),
           "file": "news_{year}.tgz", "min_year": year - 3}
    lock, _ = fetch.fetch_all([src], {}, tmp_path)
    assert lock["news"]["url"].endswith(f"/news_{year - 1}.tgz")
    assert [p.name for p in (tmp_path / "news").iterdir()] == [f"news_{year - 1}.tgz"]
    assert [p for m, p, _ in server.requests if m == "HEAD"][:2] == [f"/news_{year}.tgz", f"/news_{year - 1}.tgz"]


def test_leipzig_never_downgrades_a_local_year(server, tmp_path):
    year = datetime.now(timezone.utc).year
    src = {"id": "news", "resolver": "leipzig", "url": server.url("/news_{year}.tgz"),
           "file": "news_{year}.tgz", "min_year": year - 3}
    server.files[f"/news_{year - 2}.tgz"] = b"older"
    server.files[f"/news_{year - 1}.tgz"] = b"newest"
    lock, _ = fetch.fetch_all([src], {}, tmp_path)

    server.forbid.add(f"/news_{year - 1}.tgz")              # 403 is not "missing"
    lock2, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert "HTTP 403" in warnings["news"] and lock2 == lock

    server.forbid.clear()
    del server.files[f"/news_{year - 1}.tgz"]               # withdrawn: keep the newer local file
    lock3, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert "local copy" in warnings["news"] and lock3 == lock
    assert [p.name for p in (tmp_path / "news").iterdir()] == [f"news_{year - 1}.tgz"]

    (tmp_path / "news" / f"news_{year - 1}.tgz").unlink()   # not on disk: an older year will do
    lock4, warnings = fetch.fetch_all([src], lock, tmp_path)
    assert warnings == {} and lock4["news"]["file"] == f"news_{year - 2}.tgz"


def test_package_records_version_without_download(tmp_path):
    src = {"id": "wordfreq", "resolver": "package", "package": "wordfreq", "url": "https://pypi.org/"}
    lock, warnings = fetch.fetch_all([src], {}, tmp_path)
    assert lock["wordfreq"]["version"] == importlib.metadata.version("wordfreq")
    assert not (tmp_path / "wordfreq").exists() and warnings == {}
    assert fetch.fetch_all([src], lock, tmp_path)[0] == lock    # unchanged: same fetched_at


def test_only_and_lock_file(server, tmp_path):
    server.files["/a.txt"] = b"a"
    server.files["/b.txt"] = b"b"
    a, b = http_source(server, "a", "a.txt"), http_source(server, "b", "b.txt")
    old = {"b": {"file": "b.txt", "sha256": "x"}, "gone": {}}
    lock, _ = fetch.fetch_all([a, b], old, tmp_path, only="a")
    assert set(lock) == {"a", "b"} and lock["b"] == old["b"]
    with pytest.raises(ValueError, match="unknown source"):
        fetch.fetch_all([a, b], {}, tmp_path, only="nope")
    path = tmp_path / "lock.json"
    fetch.write_lock(lock, path)
    assert fetch.load_lock(path) == lock and fetch.load_lock(tmp_path / "missing.json") == {}
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []   # no temp file left


def test_lock_is_written_after_each_source(server, tmp_path):
    server.files["/a.txt"] = b"a"
    a, b = http_source(server, "a", "a.txt"), {"id": "b", "resolver": "http", "url": "http://127.0.0.1:9/b", "file": "b"}
    path = tmp_path / "lock.json"
    with pytest.raises(fetch.FetchError):
        fetch.fetch_all([a, b], {}, tmp_path / "raw", lock_path=path)
    assert fetch.load_lock(path)["a"]["sha256"] == sha(b"a")   # the lock describes a's new file


def test_sources_toml_is_complete():
    sources = fetch.load_sources()
    assert [s["id"] for s in sources] == list(pipeline.EXTRACTORS)
    for s in sources:
        assert s["resolver"] in ("http", "leipzig", "package")
        for field in ("name", "url", "homepage", "license", "license_url", "attribution", "cite"):
            assert s.get(field), (s["id"], field)
        assert ("file" in s) != (s["resolver"] == "package")
        if "mirror" in s:
            assert fetch.sha256_file(config.ROOT / s["mirror"]) == s["mirror_sha256"]
            assert s["mirror_last_modified"]


# --- cache -------------------------------------------------------------------

CALLS: list[str] = []


def stage_frame(n: int) -> pl.DataFrame:
    CALLS.append("frame")
    return pl.DataFrame({"x": list(range(n))})


def stage_dict(n: int) -> dict:
    CALLS.append("dict")
    return {"a": pl.DataFrame({"x": [n]}), "b": pl.DataFrame({"s": ["x"]}, schema={"s": pl.String}), "n": n}


def test_run_stage_caches_and_keeps_latest_key(tmp_path):
    CALLS.clear()
    out, key = cache.run_stage("f", stage_frame, (3,), ["dep1"], root=tmp_path)
    again, key2 = cache.run_stage("f", stage_frame, (3,), ["dep1"], root=tmp_path)
    assert CALLS == ["frame"] and key == key2 and again.equals(out)
    _, key3 = cache.run_stage("f", stage_frame, (4,), ["dep2"], root=tmp_path)
    assert key3 != key and CALLS == ["frame", "frame"]
    assert [p.name for p in (tmp_path / "f").iterdir()] == [key3]
    cache.run_stage("f", stage_frame, (4,), ["dep2"], force=True, root=tmp_path)
    assert len(CALLS) == 3

    d, _ = cache.run_stage("d", stage_dict, (7,), root=tmp_path)
    cached, _ = cache.run_stage("d", stage_dict, (7,), root=tmp_path)
    assert list(cached) == ["a", "b", "n"] and cached["n"] == 7
    assert cached["a"].equals(d["a"]) and cached["b"].schema == d["b"].schema
    with pytest.raises(cache.CacheMiss):
        cache.run_stage("d", stage_dict, (7,), ["other"], cache_only=True, root=tmp_path)


def test_code_hash_covers_shared_modules():
    from rimario_build.stress import vote
    mods = {m.__name__ for m in cache._used_modules(vote)}
    assert {"rimario_build.stress.vote", "rimario_build.schema", "rimario_build.config",
            "rimario_build.text"} <= mods


def test_key_covers_pipeline_glue_and_environment(tmp_path, monkeypatch):
    runner = pipeline.Runner(root=tmp_path)
    runner.stage("f", stage_frame, (1,))
    before = runner.keys["f"]
    monkeypatch.setattr(pipeline, "GLUE", "edited pipeline.py")
    runner.stage("f", stage_frame, (1,))
    assert runner.keys["f"] != before
    key = cache.stage_key("f", stage_frame)
    assert cache.environment().endswith(f":py{sys.version_info.major}.{sys.version_info.minor}")
    monkeypatch.setattr(config, "UV_LOCK", tmp_path / "uv.lock")
    (tmp_path / "uv.lock").write_text("other versions")
    cache.environment.cache_clear()
    try:
        assert cache.stage_key("f", stage_frame) != key
    finally:
        cache.environment.cache_clear()


def test_save_prunes_temp_dirs_of_interrupted_saves(tmp_path):
    (tmp_path / "f" / ".abc.tmp123").mkdir(parents=True)
    _, key = cache.run_stage("f", stage_frame, (1,), root=tmp_path)
    assert [p.name for p in (tmp_path / "f").iterdir()] == [key]


def test_raw_state_follows_the_files_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    src, raw = {"id": "s", "resolver": "http", "file": "d.txt"}, tmp_path / "raw"
    lock = {"s": {"file": "d.txt", "sha256": sha(b"v1")}}
    with pytest.raises(fetch.FetchError, match="run `rimario-build fetch`"):
        pipeline.raw_state(src, lock, raw)                  # fresh clone: lock but no file
    (raw / "s").mkdir(parents=True)
    (raw / "s" / "d.txt").write_bytes(b"v1")
    state = pipeline.raw_state(src, lock, raw)
    assert state == f"d.txt:{sha(b'v1')}"
    (raw / "s" / "d.txt").write_bytes(b"v2")              # replaced, lock unchanged
    assert pipeline.raw_state(src, lock, raw) == f"d.txt:{sha(b'v2')}"
    (raw / "s" / "d.txt").rename(raw / "s" / "other.txt")
    with pytest.raises(fetch.FetchError, match="missing"):
        pipeline.raw_state(src, lock, raw)
    pkg = {"id": "wordfreq", "resolver": "package", "package": "wordfreq"}
    assert pipeline.raw_state(pkg, {"wordfreq": {"version": "0.0"}}, raw) == importlib.metadata.version("wordfreq")


# --- pipeline wiring ---------------------------------------------------------

def _forms(source: str) -> pl.DataFrame:
    return pl.DataFrame({"form": ["casa", "ancora"], "lemma": ["casa", "ancora"], "pos": ["noun", "adv"],
                         "feats": [None, None], "stress_idx": [1, None], "quality": [None, None],
                         "evidence": ["hyphenation", "none"], "tags": [[], []], "source": [source] * 2},
                        schema=schema.FORMS)


def _freq(source: str) -> dict:
    out = {"freq": pl.DataFrame({"form": ["casa", "ciao"], "count": [5, 3], "zipf": [5.0, 4.0],
                                 "cap_count": [None, None], "lower_count": [None, None], "source": [source] * 2},
                                schema=schema.FREQ),
           "meta": pl.DataFrame({"source": [source], "total_tokens": [10], "floor_zipf": [1.0],
                                 "complete": [True], "truncated": [False]}, schema=schema.FREQ_META)}
    if source == "leipzig_news":
        out["contexts"] = pl.DataFrame({"form": ["ancora"], "cue": ["non"], "count": [2]}, schema=schema.CONTEXTS)
    return out


def ex_kaikki_en(raw_dir): CALLS.append(raw_dir.name); return _forms("kaikki_en")
def ex_kaikki_it(raw_dir): CALLS.append(raw_dir.name); return _forms("kaikki_it")
def ex_morphit(raw_dir): CALLS.append(raw_dir.name); return _forms("morphit")
def ex_wordfreq(raw_dir): CALLS.append(raw_dir.name); return _freq("wordfreq")
def ex_opensubtitles(raw_dir): CALLS.append(raw_dir.name); return _freq("opensubtitles")
def ex_leipzig(raw_dir): CALLS.append(raw_dir.name); return _freq("leipzig_news")


def _readings(form: str, tier: str) -> pl.DataFrame:
    return pl.DataFrame({"form": [form], "stress_idx": [1], "quality": [None], "lemma": [form], "pos": ["noun"],
                         "tier": [tier], "confidence": [1.0], "evidence": ["ipa"], "sources": [["kaikki_en"]]},
                        schema=schema.READINGS)


def st_vote(forms):
    CALLS.append("vote")
    return {"readings": _readings("casa", "attested"),
            "conflicts": pl.DataFrame(schema=schema.CONFLICTS)}


def st_propagate(forms, readings, attested):
    CALLS.append("paradigm")
    assert attested["form"].to_list() == ["ancora", "casa", "ciao"]
    return pl.DataFrame(schema=schema.READINGS)


def st_predict(readings, targets):
    CALLS.append("model")
    assert targets.to_dicts() == [{"form": "ancora", "pos": "adv", "lemma": "ancora"}]
    return {"predictions": _readings("ancora", "predicted"),
            "low_confidence": pl.DataFrame(schema={"form": pl.String, "stress_idx": pl.Int16, "confidence": pl.Float64}),
            "metrics": pl.DataFrame({"n_train": [1], "cv_accuracy": [1.0], "cv_accuracy_confident": [1.0],
                                     "coverage_confident": [1.0]})}


def st_overrides():
    return pl.DataFrame(schema={"form": pl.String, "stress_idx": pl.Int16, "quality": pl.String,
                                "action": pl.String, "note": pl.String})


def st_select(forms, readings, freq_forms, overrides, low_confidence):
    CALLS.append("lexicon")
    assert low_confidence.columns == ["form", "stress_idx", "confidence"]
    assert readings["tier"].to_list() == ["attested", "predicted"]
    entries = readings.select("form", "stress_idx").with_columns(zipf=pl.lit(None, pl.Float64))
    return {"entries": entries, "excluded": pl.DataFrame(schema={"form": pl.String, "reason": pl.String})}


def st_merge(freq, meta, lexicon_forms):
    CALLS.append("merge")
    assert freq.height == 6 and meta.height == 3
    assert lexicon_forms.to_dicts() == [{"form": "ancora", "n_lexicons": 3}, {"form": "casa", "n_lexicons": 3}]
    return {"form_zipf": lexicon_forms, "disagreements": pl.DataFrame({"form": ["x"]}),
            "correlations": pl.DataFrame({"source": ["wordfreq"]})}


def st_split(entries, form_zipf, contexts, freq):
    CALLS.append("homographs")
    return {"entries": entries.with_columns(zipf=pl.lit(3.0)), "even_splits": pl.DataFrame({"form": ["x"]})}


def _stub(monkeypatch, name: str, **funcs) -> None:
    module = types.ModuleType(f"rimario_build.{name}")
    module.__dict__.update(funcs)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    parent, _, child = module.__name__.rpartition(".")
    monkeypatch.setattr(sys.modules[parent] if parent in sys.modules else __import__(parent), child, module,
                        raising=False)


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    """Stub every stage module and point config at tmp_path; returns the report ctx list."""
    import rimario_build.frequency, rimario_build.sources, rimario_build.stress  # noqa: E401, F401
    extractors = {"kaikki_en": ex_kaikki_en, "kaikki_it": ex_kaikki_it, "morphit": ex_morphit,
                  "wordfreq": ex_wordfreq, "opensubtitles": ex_opensubtitles, "leipzig_news": ex_leipzig}
    monkeypatch.setattr(pipeline, "_extractor", lambda sid: extractors[sid])
    _stub(monkeypatch, "stress.vote", vote=st_vote)
    _stub(monkeypatch, "stress.paradigm", propagate=st_propagate)
    _stub(monkeypatch, "stress.model", predict=st_predict)
    _stub(monkeypatch, "lexicon", load_overrides=st_overrides, select=st_select)
    _stub(monkeypatch, "frequency.merge", merge=st_merge)
    _stub(monkeypatch, "frequency.homographs", split=st_split)
    reports, written = [], {}

    def write_csv(rows, path):
        path.write_text(rows.write_csv(include_header=False))
        return "sha"

    def read_csv(source):
        if isinstance(source, bytes):
            return pl.DataFrame({"word": [source.decode()]})
        return pl.DataFrame({"word": [source.read_text()] if source.exists() else []}, schema={"word": pl.String})

    _stub(monkeypatch, "export", read_csv=read_csv,
          to_rows=lambda entries: entries.select(word="form", stress="stress_idx"),
          write_csv=write_csv, write_attribution=lambda s, lock, path: written.update(lock=lock))
    _stub(monkeypatch, "report", write_report=lambda ctx, prev, path: reports.append((ctx, prev)))
    for name in ("RAW_DIR", "CACHE_DIR", "OUT_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    monkeypatch.setattr(config, "OUT_CSV", tmp_path / "out_dir" / "out.csv")
    monkeypatch.setattr(config, "SOURCES_LOCK", tmp_path / "lock.json")
    lock = {}
    for s in fetch.load_sources():
        if s["resolver"] != "package":
            (config.RAW_DIR / s["id"]).mkdir(parents=True)
            (config.RAW_DIR / s["id"] / "f").write_text(s["id"])
            lock[s["id"]] = {"file": "f", "sha256": sha(s["id"].encode())}
    fetch.write_lock(lock, config.SOURCES_LOCK)
    config.OUT_CSV.parent.mkdir()
    config.OUT_CSV.write_text("old")                     # a previous build, not committed
    return reports


def test_pipeline_wiring_and_cache(stubbed):
    CALLS.clear()
    ctx = pipeline.run(do_fetch=False, parallel=False)
    assert CALLS == ["kaikki_en", "kaikki_it", "morphit", "wordfreq", "opensubtitles", "leipzig_news",
                     "vote", "paradigm", "model", "lexicon", "merge", "homographs"]
    expected = {"readings", "conflicts", "predictions", "low_confidence", "metrics", "entries", "excluded",
                "form_zipf", "disagreements", "correlations", "even_splits", "rows", "csv_sha256",
                "csv_bytes", "lock_old", "lock_new", "fetch_warnings"}
    assert expected <= set(ctx)
    assert ctx["csv_bytes"] > 0 and ctx["fetch_warnings"] == [] and ctx["lock_new"]["morphit"]["sha256"]
    assert stubbed[0][1]["word"].to_list() == ["old"]     # no committed CSV: the out/ CSV on disk
    assert ctx["lock_old"] == ctx["lock_new"]               # no committed lock: the one on disk

    CALLS.clear()
    pipeline.run(do_fetch=False, parallel=False)
    assert CALLS == []                                   # everything cached

    CALLS.clear()
    pipeline.run(do_fetch=False, only="morphit", parallel=False)
    assert CALLS == ["morphit", "vote", "paradigm", "model", "lexicon", "merge", "homographs"]

    CALLS.clear()
    (config.RAW_DIR / "opensubtitles" / "f").write_text("new version")    # the lock alone changes nothing
    pipeline.run(do_fetch=False, parallel=False)
    assert CALLS == ["opensubtitles", "paradigm", "model", "lexicon", "merge", "homographs"]


def test_build_diffs_against_git_head(stubbed, monkeypatch):
    committed = {config.SOURCES_LOCK: b'{"morphit": {"sha256": "committed"}}', config.OUT_CSV: b"committed"}
    monkeypatch.setattr(pipeline, "_git_show", committed.get)
    ctx = pipeline.build({"before": {}}, [], parallel=False)
    assert ctx["lock_old"] == {"morphit": {"sha256": "committed"}}
    assert stubbed[-1][1]["word"].to_list() == ["committed"]
    monkeypatch.setattr(pipeline, "_git_show", lambda path: None)
    on_disk = config.OUT_CSV.read_text()
    ctx = pipeline.build({"before": {}}, [], parallel=False)   # nothing committed: the out/ CSV on disk
    assert ctx["lock_old"] == {"before": {}} and stubbed[-1][1]["word"].to_list() == [on_disk]
    config.OUT_CSV.unlink()
    pipeline.build({}, [], parallel=False)                     # no CSV at all: empty
    assert stubbed[-1][1].is_empty()


def test_build_offline_without_raw_files_is_a_clear_error(stubbed):
    from rimario_build.__main__ import main
    import shutil
    shutil.rmtree(config.RAW_DIR / "kaikki_en")
    assert main(["build", "--offline"]) == 1


@pytest.mark.parametrize("argv", [["build", "--only", "nope"], ["report", "--only", "morphit"]])
def test_main_rejects_bad_arguments(argv):
    from rimario_build.__main__ import main
    with pytest.raises(SystemExit):
        main(argv)


def test_stages_parallel_in_process_pool(tmp_path):
    CALLS.clear()
    runner = pipeline.Runner(root=tmp_path)
    specs = [("p1", stage_frame, (2,), ("a",)), ("p2", stage_dict, (5,), ("b",)), ("p3", stage_frame, (1,), ("c",))]
    out = runner.stages_parallel(specs, in_process=frozenset({"p3"}))
    assert CALLS == ["frame"]                    # only p3 ran in this process
    assert [out[n].height for n in ("p1", "p3")] == [2, 1] and out["p2"]["n"] == 5
    assert set(runner.keys) == {"p1", "p2", "p3"}
    assert cache.load("p1", runner.keys["p1"], tmp_path).height == 2


def test_uses_process_pool_follows_imported_modules(monkeypatch):
    from rimario_build.sources import kaikki_en, leipzig, morphit
    assert [pipeline._uses_process_pool(m.extract) for m in (kaikki_en, leipzig, morphit)] == [True, True, False]
    common = types.ModuleType("rimario_build.sources.fake_common")
    common.__file__, common.ProcessPoolExecutor = __file__, pipeline.ProcessPoolExecutor
    user = types.ModuleType("rimario_build.sources.fake")
    user.__file__, user.fake_common = __file__, common      # like `from . import fake_common`
    exec("def extract(raw_dir): pass", user.__dict__)
    user.extract.__module__ = user.__name__
    for m in (common, user):
        monkeypatch.setitem(sys.modules, m.__name__, m)
    assert pipeline._uses_process_pool(user.extract)
