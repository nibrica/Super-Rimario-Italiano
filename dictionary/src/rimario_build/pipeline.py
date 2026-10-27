"""The build pipeline: fetch, extract, stress, lexicon, frequency, export, report.

Stage modules are imported lazily, so ``fetch`` works without them. Every
stage runs through ``cache``; a stage reruns when its code, its upstream
stages' keys, its raw files (their real sha256, not just the lock) or this
module's glue change, or when it is forced (``--only``), which also forces
everything downstream of it.
"""

import importlib
import importlib.metadata
import json
import logging
import multiprocessing
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import polars as pl

from . import cache, config, fetch, schema, text

log = logging.getLogger(__name__)

# Source id -> extractor module (each has ``extract(raw_dir) -> table(s)``).
EXTRACTORS = {
    "kaikki_en": "rimario_build.sources.kaikki_en",
    "kaikki_it": "rimario_build.sources.kaikki_it",
    "morphit": "rimario_build.sources.morphit",
    "wordfreq": "rimario_build.sources.wordfreq_it",
    "opensubtitles": "rimario_build.sources.opensubtitles",
    "leipzig_news": "rimario_build.sources.leipzig",
}
LEXICONS = ("kaikki_en", "kaikki_it", "morphit")
CORPORA = ("wordfreq", "opensubtitles", "leipzig_news")
# This module builds the inputs of the stages after the extractors (targets,
# form sets, lexicon counts), so its source is part of their cache keys.
GLUE = fetch.sha256_file(Path(__file__))


# --- Fetch -------------------------------------------------------------------

def run_fetch(only: str | None = None) -> tuple[dict, list[str]]:
    """Fetch sources, writing the lock after each; returns (lock before the fetch, warnings)."""
    sources = fetch.load_sources(config.SOURCES_TOML)
    lock_old = fetch.load_lock(config.SOURCES_LOCK)
    _, warnings = fetch.fetch_all(sources, lock_old, config.RAW_DIR, only=only, lock_path=config.SOURCES_LOCK)
    stored = fetch.read_json(_warnings_json())
    for sid in [s["id"] for s in sources] if only is None else [only]:
        stored.pop(sid, None)
    stored.update(warnings)
    fetch.write_json(_warnings_json(), stored)
    return lock_old, _warning_list(stored)


def _warnings_json() -> Path:
    return config.CACHE_DIR / "fetch_warnings.json"


def _warning_list(stored: dict[str, str]) -> list[str]:
    return [stored[k] for k in sorted(stored)]


def raw_state(src: dict, lock: dict, raw_dir: Path) -> str:
    """Identity of a source's raw data for cache keys.

    A package: its installed version. Otherwise the name and sha256 of every
    file in ``raw_dir/<id>/``, which must hold the locked file. A file that
    differs from the lock (e.g. a lock pulled from git, not fetched yet) is
    keyed by its real content, with a warning.
    """
    if src["resolver"] == "package":
        return importlib.metadata.version(src["package"])
    sid, entry, d = src["id"], lock.get(src["id"]) or {}, raw_dir / src["id"]
    files = sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith(".")) if d.is_dir() else []
    locked = d / entry["file"] if entry.get("file") else None
    if not files or (locked and locked not in files):
        missing = f"{locked} (in sources.lock.json) is missing" if locked else f"no raw data in {d}"
        raise fetch.FetchError(f"{sid}: {missing}; run `rimario-build fetch`")
    hashes = {p.name: _raw_sha256(p) for p in files}
    if locked and hashes[locked.name] != entry.get("sha256"):
        log.warning("%s: %s differs from sources.lock.json; run `rimario-build fetch`", sid, locked.name)
    return "|".join(f"{name}:{h}" for name, h in hashes.items())


def _raw_sha256(path: Path) -> str:
    """sha256 of a raw file, memoized by path, size and mtime (hashing them all takes seconds)."""
    memo_path = config.CACHE_DIR / config.RAW_HASHES_JSON
    memo, st, key = fetch.read_json(memo_path), path.stat(), str(path.resolve())
    if memo.get(key, [None, None])[:2] != [st.st_size, st.st_mtime_ns]:
        memo = {k: v for k, v in memo.items() if Path(k).exists()}
        memo[key] = [st.st_size, st.st_mtime_ns, fetch.sha256_file(path)]
        fetch.write_json(memo_path, memo)
    return memo[key][2]


# --- Stage runner ------------------------------------------------------------

def setup_logging(level: int) -> None:
    """Log format of the CLI and of pool workers."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")


class Runner:
    """Runs stages through the cache, chaining keys and forced reruns."""

    def __init__(self, force: frozenset[str] = frozenset(), cache_only: bool = False,
                 parallel: bool = True, root: Path | None = None):
        self.force, self.cache_only, self.parallel = force, cache_only, parallel
        self.root = root or config.CACHE_DIR
        self.keys: dict[str, str] = {}
        self.forced: set[str] = set()

    def _deps(self, name: str, after: tuple[str, ...], extra: tuple[str, ...]) -> tuple[list[str], bool]:
        force = name in self.force or any(a in self.forced for a in after)
        if force:
            self.forced.add(name)
        return [self.keys[a] for a in after] + list(extra), force

    def stage(self, name: str, fn: Callable, args: tuple = (), after: tuple[str, ...] = (),
              extra: tuple[str, ...] = ()) -> cache.Output:
        """Run ``fn(*args)``; ``after`` names upstream stages, ``extra`` other inputs' hashes.

        The key also covers GLUE, since this module builds the stage's inputs.
        """
        deps, force = self._deps(name, after, (*extra, GLUE))
        out, self.keys[name] = cache.run_stage(name, fn, args, deps, force=force,
                                               cache_only=self.cache_only, root=self.root)
        return out

    def stages_parallel(self, specs: list[tuple[str, Callable, tuple, tuple[str, ...]]],
                        in_process: frozenset[str] = frozenset()) -> dict[str, cache.Output]:
        """Run independent stages (name, fn, args, extra) in a process pool.

        Stages named in ``in_process`` (they run their own process pool, and
        pools must not nest) run in threads of this process meanwhile.
        """
        results: dict[str, cache.Output] = {}
        misses = []
        for name, fn, args, extra in specs:
            deps, force = self._deps(name, (), extra)
            key, out = cache.lookup(name, fn, deps, force=force, cache_only=self.cache_only, root=self.root)
            self.keys[name] = key
            if out is None:
                misses.append((name, fn, args, key))
            else:
                results[name] = out
        if not self.parallel or len(misses) <= 1:
            for name, fn, args, key in misses:
                results[name] = cache.compute(name, fn, args, key, self.root)
            return {name: results[name] for name, *_ in specs}
        here = [m for m in misses if m[0] in in_process]
        pooled = [m for m in misses if m not in here]
        workers = min(len(pooled), config.MAX_WORKERS or os.cpu_count() or 1)
        level = logging.getLogger().getEffectiveLevel()
        with (ThreadPoolExecutor(max(len(here), 1)) as threads,
              ProcessPoolExecutor(max(workers, 1), mp_context=multiprocessing.get_context("forkserver"),
                                  initializer=setup_logging, initargs=(level,)) as pool):
            local = {name: threads.submit(cache.compute, name, fn, args, key, self.root)
                     for name, fn, args, key in here}
            remote = {name: pool.submit(cache.compute_quietly, name, fn, args, key, self.root)
                      for name, fn, args, key in pooled}
            for name, fn, args, key in pooled:
                seconds = remote[name].result()
                results[name] = cache.load(name, key, self.root)
                log.info("stage %s: computed, %.1fs (%s)", name, seconds, cache.describe(results[name]))
            results |= {name: f.result() for name, f in local.items()}
        return {name: results[name] for name, *_ in specs}


# --- Build -------------------------------------------------------------------

def _extractor(sid: str) -> Callable:
    return importlib.import_module(EXTRACTORS[sid]).extract


def _uses_process_pool(fn: Callable) -> bool:
    """True if ``fn``'s module, or a package module it uses (transitively), uses ProcessPoolExecutor."""
    return any(vars(m).get("ProcessPoolExecutor") is ProcessPoolExecutor
               for m in cache._used_modules(sys.modules[fn.__module__]))


def _concat(frames: list[pl.DataFrame], table: dict) -> pl.DataFrame:
    return pl.concat([schema.conform(f, table) for f in frames])


def _form_set(*frames: pl.DataFrame) -> pl.DataFrame:
    return pl.concat([f.select("form") for f in frames]).unique().sort("form")


def _file_hash(path: Path) -> str:
    return fetch.sha256_file(path) if path.exists() else "missing"


def stages(runner: Runner, sources: list[dict], lock: dict, raw_dir: Path) -> dict:
    """Run every stage up to the complete entries; returns the stage outputs by name."""
    from .frequency import homographs, merge
    from . import lexicon
    from .stress import model, paradigm, vote

    by_id = {s["id"]: s for s in sources}
    fns = {sid: _extractor(sid) for sid in EXTRACTORS}
    ext = runner.stages_parallel(
        [(sid, fns[sid], (raw_dir / sid,), (raw_state(by_id[sid], lock, raw_dir),)) for sid in EXTRACTORS],
        in_process=frozenset(sid for sid, fn in fns.items() if _uses_process_pool(fn)),
    )
    forms = _concat([ext[s] for s in LEXICONS], schema.FORMS)
    freq = _concat([ext[s]["freq"] for s in CORPORA], schema.FREQ)
    meta = _concat([ext[s]["meta"] for s in CORPORA], schema.FREQ_META)
    contexts = schema.conform(ext["leipzig_news"]["contexts"], schema.CONTEXTS)

    voted = runner.stage("vote", vote.vote, (forms,), LEXICONS)
    attested = voted["readings"]
    propagated = runner.stage("paradigm", paradigm.propagate, (forms, attested, _form_set(forms, freq)),
                              ("vote", *EXTRACTORS))
    known = _concat([attested, propagated], schema.READINGS)
    # Vowel-less forms stay: the model lists them in low_confidence (excluded with that reason).
    targets = (forms.filter(pl.col("form").str.contains(text.ALLOWED_RE))
               .join(known.select("form").unique(), on="form", how="anti")
               # with the lemma, so lexicon.select finds each prediction's tags (misspelling...)
               .select("form", "pos", "lemma").unique().sort("form", "pos", "lemma", nulls_last=True))
    predicted = runner.stage("model", model.predict, (known, targets), ("vote", "paradigm", *LEXICONS))
    readings = _concat([known, predicted["predictions"]], schema.READINGS)

    overrides = runner.stage("overrides", lexicon.load_overrides, (), extra=(_file_hash(config.OVERRIDES_TSV),))
    selected = runner.stage("lexicon", lexicon.select,
                            (forms, readings, _form_set(freq), overrides, predicted["low_confidence"]),
                            ("model", "paradigm", "vote", "overrides", *EXTRACTORS))

    # Every lexicon form plus the selected entries' forms: paradigm may add forms
    # found only in a corpus (§5.2, §7), which are in no lexicon (n_lexicons 0).
    entry_forms = selected["entries"].select("form", source=pl.lit(None, pl.String))
    lexicon_forms = (pl.concat([forms.select("form", "source"), entry_forms])
                     .group_by("form").agg(pl.col("source").drop_nulls().n_unique().cast(pl.Int8).alias("n_lexicons"))
                     .sort("form"))
    merged = runner.stage("merge", merge.merge, (freq, meta, lexicon_forms), ("lexicon", *EXTRACTORS))
    split = runner.stage("homographs", homographs.split,
                         (selected["entries"], merged["form_zipf"], contexts, freq),
                         ("lexicon", "merge", *EXTRACTORS))
    return {
        "forms": forms, "freq": freq, "meta": meta, "contexts": contexts,
        "readings": readings, "conflicts": voted["conflicts"],
        "predictions": predicted["predictions"], "low_confidence": predicted["low_confidence"],
        "metrics": predicted["metrics"],
        "entries": split["entries"], "excluded": selected["excluded"],
        "form_zipf": merged["form_zipf"], "disagreements": merged["disagreements"],
        "correlations": merged["correlations"], "even_splits": split["even_splits"],
    }


def build(lock_before: dict, warnings: list[str], only: str | None = None, parallel: bool = True) -> dict:
    """Run the stages, write out/ (CSV, ATTRIBUTION.md, report.md); returns the report ctx.

    ``lock_before`` is the lock before this run's fetch: the report's baseline
    when git HEAD has no lock (see ``_baseline``).
    """
    from . import export, report

    sources = fetch.load_sources(config.SOURCES_TOML)
    lock_new = fetch.load_lock(config.SOURCES_LOCK)
    runner = Runner(force=frozenset({only} if only else ()), parallel=parallel)
    ctx = stages(runner, sources, lock_new, config.RAW_DIR)
    lock_old, previous_rows = _baseline(lock_before)
    rows = export.to_rows(ctx["entries"])
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    ctx |= {
        "rows": rows, "csv_sha256": export.write_csv(rows, config.OUT_CSV),
        "csv_bytes": config.OUT_CSV.stat().st_size,
        "lock_old": lock_old, "lock_new": lock_new, "fetch_warnings": warnings,
    }
    export.write_attribution(sources, lock_new, config.OUT_ATTRIBUTION)
    report.write_report(ctx, previous_rows, config.OUT_REPORT)
    log.info("wrote %s (%d rows, %.1f MB, sha256 %s)", config.OUT_CSV, rows.height,
             ctx["csv_bytes"] / 1e6, ctx["csv_sha256"][:12])
    return ctx


def _git_show(path: Path) -> bytes | None:
    """``path`` as committed at HEAD, or None."""
    try:
        rel = path.resolve().relative_to(config.ROOT.parent)
        return subprocess.run(["git", "show", f"HEAD:{rel.as_posix()}"], cwd=config.ROOT,
                              capture_output=True, check=True).stdout
    except (ValueError, OSError, subprocess.CalledProcessError):
        return None


def _baseline(lock_before: dict) -> tuple[dict, pl.DataFrame]:
    """(lock, CSV rows) the report diffs against: both as committed at git HEAD (§9).

    Without a committed lock: ``lock_before``. Without a committed CSV: the old
    pipeline's CSV (config.PREVIOUS_CSV_FALLBACK), else the out/ CSV on disk.
    """
    from . import export

    committed_lock = _git_show(config.SOURCES_LOCK)
    lock_old = json.loads(committed_lock) if committed_lock else lock_before
    committed_csv = _git_show(config.OUT_CSV)
    if committed_csv is None:
        fallback = config.PREVIOUS_CSV_FALLBACK
        return lock_old, export.read_csv(fallback if fallback.exists() else config.OUT_CSV)
    return lock_old, export.read_csv(committed_csv)


def regenerate_report() -> dict:
    """Rewrite out/report.md from cached stage outputs, diffing against git HEAD."""
    from . import export, report

    lock_new = fetch.load_lock(config.SOURCES_LOCK)
    ctx = stages(Runner(cache_only=True), fetch.load_sources(config.SOURCES_TOML), lock_new, config.RAW_DIR)
    lock_old, previous_rows = _baseline(lock_new)
    ctx |= {
        "rows": export.to_rows(ctx["entries"]), "csv_sha256": _file_hash(config.OUT_CSV),
        "csv_bytes": config.OUT_CSV.stat().st_size if config.OUT_CSV.exists() else 0,
        "lock_old": lock_old, "lock_new": lock_new,
        "fetch_warnings": _warning_list(fetch.read_json(_warnings_json())),
    }
    report.write_report(ctx, previous_rows, config.OUT_REPORT)
    log.info("wrote %s", config.OUT_REPORT)
    return ctx


def run(do_fetch: bool = True, only: str | None = None, parallel: bool = True) -> dict:
    """``rimario-build`` / ``build``: optionally fetch, then build."""
    if do_fetch:
        lock_before, warnings = run_fetch(only)
    else:
        lock_before = fetch.load_lock(config.SOURCES_LOCK)
        warnings = _warning_list(fetch.read_json(_warnings_json()))
    return build(lock_before, warnings, only=only, parallel=parallel)
