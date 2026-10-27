"""QA report (§9): curation scores, counts, diff against the previous build, worklists."""

import gzip
import hashlib
import math
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from . import config, export, fetch, schema, text
from .lexicon import read_tsv, stress_error

GOLD = {
    "form": pl.String,
    "stress_idx": pl.Int16,
    "default": pl.Boolean,          # True: must be the default; False: must not; null: either
    "note": pl.String,
}
FREQ_PAIRS = {"more": pl.String, "less": pl.String, "note": pl.String}
GOLD_MISSES = {**GOLD, "reason": pl.String, "got": pl.String}
PAIR_MISSES = {**FREQ_PAIRS, "zipf_more": pl.Int32, "zipf_less": pl.Int32, "reason": pl.String}

NA = "n/a"


# --- Curation files -----------------------------------------------------------

def load_gold(path: Path = config.GOLD_TSV) -> pl.DataFrame:
    """Read ``gold.tsv`` (form, stress_idx, default 1/0/empty, note)."""
    if not path.exists():
        return schema.empty(GOLD)
    rows = []
    for n, line, (form, idx, default, note) in read_tsv(path, GOLD):
        form = text.norm(form)
        error = stress_error(form, idx)
        if error is None and default not in ("", "0", "1"):
            error = "default must be 1, 0 or empty"
        if error:
            raise ValueError(f"{path}:{n}: {error}: {line!r}")
        rows.append((form, int(idx), {"1": True, "0": False}.get(default), note or None))
    return pl.DataFrame(rows, schema=GOLD, orient="row")


def load_freq_pairs(path: Path = config.FREQ_PAIRS_TSV) -> pl.DataFrame:
    """Read ``freq_pairs.tsv`` (more, less, note): ``more`` should be more frequent."""
    if not path.exists():
        return schema.empty(FREQ_PAIRS)
    rows = []
    for n, line, (more, less, note) in read_tsv(path, FREQ_PAIRS):
        if not more or not less:
            raise ValueError(f"{path}:{n}: both words are required: {line!r}")
        rows.append((text.norm(more), text.norm(less), note or None))
    return pl.DataFrame(rows, schema=FREQ_PAIRS, orient="row")


def _readings(rows: pl.DataFrame, words: Iterable[str]) -> dict[str, list[tuple[int, int, int]]]:
    """word -> [(stress, zipf, flags)] for the given words."""
    out: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    sel = rows.filter(pl.col("word").is_in(pl.Series(list(words), dtype=pl.String).implode()))
    for w, s, z, f in sel.select("word", "stress", "zipf", "flags").iter_rows():
        out[w].append((s, z, f))
    return out


def _default(readings: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    """The default reading: no non-default flag, highest zipf, then lowest stress/flags."""
    if not readings:
        return None
    pool = [r for r in readings if not r[2] & schema.FLAG_NON_DEFAULT] or readings
    return min(pool, key=lambda r: (-r[1], r[0], r[2]))


def _mark(form: str, idx: int | None) -> str:
    """``form`` with its stress marked; falls back to ``form[idx]`` if idx is not a vowel."""
    if idx is None:
        return form
    try:
        return text.mark_stress(form, int(idx))
    except (ValueError, IndexError):
        return f"{form}[{idx}]"


def _show(word: str, readings: list[tuple[int, int, int]]) -> str:
    return ", ".join(_mark(word, s) + (f" ({f})" if f else "") for s, _, f in sorted(readings))


def gold_accuracy(rows: pl.DataFrame, gold: pl.DataFrame) -> tuple[float, pl.DataFrame]:
    """Fraction of gold rows the output satisfies, and the misses.

    A gold row needs an output row with its form and stress; ``default`` 1/0
    requires that row to be the default / a non-default reading.
    """
    if gold.is_empty():
        return math.nan, schema.empty(GOLD_MISSES)
    found = _readings(rows, gold.get_column("form").unique())
    ok, misses = 0, []
    for g in gold.iter_rows(named=True):
        got = found.get(g["form"], [])
        hits = [r for r in got if r[0] == g["stress_idx"]]
        reason = None
        if not hits:
            reason = "missing reading" if got else "missing form"
        elif g["default"] is not None:
            want = not g["default"]
            if not any(bool(r[2] & schema.FLAG_NON_DEFAULT) == want for r in hits):
                reason = "should be default" if g["default"] else "should not be default"
        if reason is None:
            ok += 1
        else:
            misses.append({**g, "reason": reason, "got": _show(g["form"], got)})
    return ok / gold.height, pl.DataFrame(misses, schema=GOLD_MISSES)


def freq_pair_agreement(rows: pl.DataFrame, pairs: pl.DataFrame) -> tuple[float, pl.DataFrame]:
    """Fraction of pairs whose ``more`` default reading has a higher zipf than ``less``'s.

    A pair with a word missing from the output counts as a disagreement.
    """
    if pairs.is_empty():
        return math.nan, schema.empty(PAIR_MISSES)
    found = _readings(rows, pairs.get_column("more").to_list() + pairs.get_column("less").to_list())
    ok, misses = 0, []
    for p in pairs.iter_rows(named=True):
        dm, dl = _default(found.get(p["more"], [])), _default(found.get(p["less"], []))
        zm, zl = (dm[1] if dm else None), (dl[1] if dl else None)
        if zm is not None and zl is not None and zm > zl:
            ok += 1
            continue
        reason = "missing" if zm is None or zl is None else "tie" if zm == zl else "reversed"
        misses.append({**p, "zipf_more": zm, "zipf_less": zl, "reason": reason})
    return ok / pairs.height, pl.DataFrame(misses, schema=PAIR_MISSES)


def _per_word(rows: pl.DataFrame) -> pl.DataFrame:
    """word -> top zipf, sorted set of stresses, default stress (as ``_default``)."""
    non_default = (pl.col("flags") & schema.FLAG_NON_DEFAULT) != 0
    return rows.group_by("word").agg(
        top=pl.col("zipf").max(),
        stresses=pl.col("stress").unique().sort(),
        default=pl.col("stress").sort_by(non_default, "zipf", "stress", "flags",
                                         descending=[False, True, False, False]).first(),
    )


def _by_top(df: pl.DataFrame) -> pl.DataFrame:
    return df.sort(["top", "word"], descending=[True, False])


# --- Markdown helpers ---------------------------------------------------------

def _cell(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return NA if math.isnan(v) else f"{v:.3f}"
    if isinstance(v, list):
        v = ", ".join(map(str, v))
    return str(v).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: Iterable[Iterable[object]]) -> str:
    rows = [list(r) for r in rows]
    if not rows:
        return "_none_"
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_cell(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def _pct(x: float | None) -> str:
    return NA if x is None or math.isnan(x) else f"{100 * x:.2f}%"


# --- Sections -----------------------------------------------------------------

class _Report:
    """Shared lookups for the report sections; ``ctx`` is the pipeline's full context."""

    def __init__(self, ctx: dict, previous: pl.DataFrame):
        self.ctx = ctx
        self.previous = previous
        self.entries = ctx["entries"]
        self.rows = ctx["rows"]
        self.form_zipf = ctx["form_zipf"].select("form", "zipf")
        self.zipf = dict(self.form_zipf.iter_rows())

    def by_zipf(self, df: pl.DataFrame, n: int = config.REPORT_TOP_N) -> list[dict]:
        """Rows of ``df`` sorted by the zipf of their ``form`` (desc), then as given; first n."""
        return sorted(df.to_dicts(), key=lambda d: -self.zipf.get(d["form"], -math.inf))[:n]

    def zcell(self, form: str) -> str:
        z = self.zipf.get(form)
        return NA if z is None else f"{z:.2f}"

    # sections

    def sources(self) -> str:
        old, new = self.ctx["lock_old"], self.ctx["lock_new"]
        if not new:
            return "No lock file (offline build without a fetch)."
        rows = []
        for sid in sorted(set(old) | set(new)):
            o, n = old.get(sid), new.get(sid)
            if n is None:
                status, n = "removed", o
            elif o is None:
                status = "new"
            elif (o.get("sha256"), o.get("version"), o.get("url")) != (n.get("sha256"), n.get("version"), n.get("url")):
                status = "changed"
            else:
                status = "unchanged"
            rows.append((sid, status, n.get("version") or n.get("etag") or n.get("last_modified") or "",
                         (n.get("sha256") or "")[:12], n.get("size"), n.get("fetched_at"), n.get("url")))
        out = _table(["source", "status", "version", "sha256", "size", "fetched", "url"], rows)
        warnings = self.ctx["fetch_warnings"]
        if warnings:
            out += "\n\n**Fetch warnings:**\n\n" + "\n".join(f"- {w}" for w in warnings)
        return out

    def output(self) -> str:
        data = export.render(self.rows)
        gz = len(gzip.compress(data, compresslevel=9, mtime=0))
        return _table(["", ""], [
            ("file", config.OUT_CSV.name), ("rows", f"{self.rows.height:,}"),
            ("distinct words", f"{self.rows.get_column('word').n_unique():,}"),
            ("size", f"{len(data):,} bytes"), ("gzipped", f"{gz:,} bytes"),
            ("sha256", f"`{hashlib.sha256(data).hexdigest()}`"),
        ])

    def counts(self) -> str:
        rows, entries = self.rows, self.entries
        tiers = entries.group_by("tier").len().sort("tier")
        src = (
            entries.with_row_index("i").select("i", pl.col("provenance").str.split(","))
            .explode("provenance").filter(pl.col("provenance") != "")
            .select("i", source=pl.col("provenance").str.split(":").list.first()).unique()
            .group_by("source").len().sort("source")
        )
        flags = [("none", rows.filter(pl.col("flags") == 0).height)] + [
            (f"{bit} {name}", rows.filter((pl.col("flags") & bit) != 0).height)
            for bit, name in (
                (schema.FLAG_NON_DEFAULT, "non-default"), (schema.FLAG_PREDICTED, "predicted"),
                (schema.FLAG_VULGAR, "vulgar"), (schema.FLAG_ARCHAIC, "archaic"),
                (schema.FLAG_PROPER, "proper"),
            )
        ]
        edges = config.REPORT_ZIPF_BANDS
        labels = [f"< {edges[0]}"] + [f"{a}–{b}" for a, b in zip(edges, edges[1:])] + [f"≥ {edges[-1]}"]
        counts = Counter(labels[bisect_right([e * 100 for e in edges], z)] for z in rows.get_column("zipf"))
        excluded = self.ctx["excluded"].group_by("reason").len().sort("reason")
        return "\n\n".join([
            "**By tier**\n\n" + _table(["tier", "rows"], tiers.iter_rows()),
            "**By supporting source** (a row counts once per source)\n\n"
            + _table(["source", "rows"], src.iter_rows()),
            "**By flag**\n\n" + _table(["flag", "rows"], flags),
            "**By Zipf band**\n\n" + _table(["zipf", "rows"], ((b, counts.get(b, 0)) for b in labels)),
            "**Excluded lexicon forms by reason**\n\n" + _table(["reason", "forms"], excluded.iter_rows()),
        ])

    def gold(self) -> str:
        gold = self.ctx.get("gold")
        gold = gold if gold is not None else load_gold()
        acc, misses = gold_accuracy(self.rows, gold)
        out = f"Accuracy: **{_pct(acc)}** on {gold.height:,} gold rows ({misses.height:,} misses)."
        if misses.height:
            out += "\n\n" + _table(
                ["gold", "default", "reason", "output", "note"],
                ((_mark(m["form"], m["stress_idx"]), m["default"], m["reason"], m["got"], m["note"])
                 for m in misses.head(config.REPORT_TOP_N).iter_rows(named=True)),
            )
        return out

    def model(self) -> str:
        m = self.ctx["metrics"]
        return _table(["metric", "value"], ((k, m.get_column(k)[0]) for k in m.columns)) if m.height else NA

    def freq_pairs(self) -> str:
        pairs = self.ctx.get("freq_pairs")
        pairs = pairs if pairs is not None else load_freq_pairs()
        acc, misses = freq_pair_agreement(self.rows, pairs)
        out = f"Agreement: **{_pct(acc)}** on {pairs.height:,} pairs ({misses.height:,} misses)."
        if misses.height:
            out += "\n\n" + _table(
                ["more", "less", "zipf×100 more", "zipf×100 less", "reason", "note"],
                ((m["more"], m["less"], m["zipf_more"], m["zipf_less"], m["reason"], m["note"])
                 for m in misses.head(config.REPORT_TOP_N).iter_rows(named=True)),
            )
        return out

    def diff(self) -> str:
        new, old = self.rows, self.previous
        if old is None or old.is_empty():
            return "No previous CSV."
        legacy = old.filter(pl.col("flags") != 0).is_empty()
        top = config.REPORT_TOP_N
        n, o = _per_word(new), _per_word(old)
        added = _by_top(n.join(o, on="word", how="anti"))
        removed = _by_top(o.join(n, on="word", how="anti"))
        both = _by_top(n.join(o, on="word", suffix="_old"))
        changed = both.filter(pl.col("stresses") != pl.col("stresses_old"))
        moved = both.filter(pl.col("default") != pl.col("default_old"))
        shown = pl.concat([d.head(top).select("word") for d in (added, removed, changed, moved)])["word"]
        new_r, old_r = _readings(new, shown), _readings(old, shown)
        value = "old count" if legacy else "old zipf×100"
        parts = [f"Previous CSV: {old.height:,} rows, {o.height:,} words"
                 + (" (old `word,stress,count` format: defaults not compared)." if legacy else ".")]
        parts.append(f"**Forms added:** {added.height:,} (most frequent first)\n\n" + _table(
            ["form", "zipf×100"], ((_show(w, new_r[w]), z) for w, z in added.head(top).select("word", "top").iter_rows())))
        parts.append(f"**Forms removed:** {removed.height:,} (most frequent first)\n\n" + _table(
            ["form", value], ((_show(w, old_r[w]), z) for w, z in removed.head(top).select("word", "top").iter_rows())))
        parts.append(f"**Stress changed:** {changed.height:,} forms (set of stressed positions differs)\n\n" + _table(
            ["before", "after", "zipf×100"],
            ((_show(w, old_r[w]), _show(w, new_r[w]), z) for w, z in changed.head(top).select("word", "top").iter_rows())))
        if not legacy:
            parts.append(f"**Default reading changed:** {moved.height:,} forms\n\n" + _table(
                ["form", "before", "after"],
                ((w, _mark(w, a), _mark(w, b))
                 for w, a, b in moved.head(top).select("word", "default_old", "default").iter_rows())))
        return "\n\n".join(parts)

    def conflicts(self) -> str:
        c = self.ctx["conflicts"].sort("form", "lemma", "pos", nulls_last=True)
        return f"{c.height:,} conflicts (most frequent forms first).\n\n" + _table(
            ["form", "lemma", "pos", "readings", "zipf"],
            ((d["form"], d["lemma"], d["pos"], d["readings"], self.zcell(d["form"])) for d in self.by_zipf(c)))

    def even_splits(self) -> str:
        e = self.ctx["even_splits"].sort("form")
        return f"{e.height:,} homographs split 50/50 (override candidates).\n\n" + _table(
            ["form", "readings", "reason", "zipf"],
            ((d["form"], ", ".join(_mark(d["form"], i) for i in d["stress_idxs"]), d["reason"],
              self.zcell(d["form"])) for d in self.by_zipf(e)))

    def disagreements(self) -> str:
        d = self.ctx["disagreements"]
        d = d.with_columns(gap=(pl.col("zipf_source") - pl.col("zipf_others")).abs()).sort(
            ["gap", "form", "source"], descending=[True, False, False])
        return (f"The {d.height:,} largest gaps between a down-weighted source estimate and the other "
                f"sources (the merge keeps at most {config.DISAGREEMENTS_KEEP:,}), largest first.\n\n") + _table(
            ["form", "source", "zipf source", "zipf others", "weight factor"],
            d.select("form", "source", "zipf_source", "zipf_others", "weight_factor")
            .head(config.REPORT_TOP_N).iter_rows())

    def low_confidence(self) -> str:
        lc = self.ctx["low_confidence"].sort("form", "stress_idx")
        out = self.ctx["excluded"].filter(pl.col("reason") == "low_confidence").height
        thresholds = ", ".join(f"{pos} {t:.2f}" for pos, t in sorted(config.MODEL_MIN_CONFIDENCE_BY_POS.items()))
        return (f"{lc.height:,} predictions ({lc.get_column('form').n_unique():,} forms) were below the "
                f"confidence threshold of their POS ({thresholds}; any other POS "
                f"{config.MODEL_MIN_CONFIDENCE:.2f}) and were not shipped; {out:,} of those forms have no other "
                "reading and are left out (most frequent first).\n\n") + _table(
            ["prediction", "confidence", "zipf"],
            ((_mark(d["form"], d["stress_idx"]), d["confidence"], self.zcell(d["form"])) for d in self.by_zipf(lc)))

    def unattested(self) -> str:
        n = config.REPORT_UNATTESTED_N
        forms = (
            self.entries.group_by("form").agg(
                unattested=pl.col("tier").is_in(["propagated", "predicted"]).all(),
                tiers=pl.col("tier").unique().sort(),
                lemmas=pl.col("lemmas").list.explode(keep_nulls=False, empty_as_null=False).unique().sort(),
                stresses=pl.col("stress_idx").sort(),
                zipf=pl.col("zipf").max(),
            ).filter("unattested")
            .join(self.form_zipf.rename({"zipf": "fz"}), on="form", how="left")
            .with_columns(z=pl.coalesce("fz", "zipf"))
            .sort(["z", "form"], descending=[True, False], nulls_last=True)
        )
        return (f"{forms.height:,} forms have only propagated or predicted stress; "
                f"the {min(n, forms.height)} most frequent (work through these first):\n\n") + _table(
            ["#", "form", "tier", "zipf", "lemmas"],
            ((i, ", ".join(_mark(d["form"], s) for s in d["stresses"]), d["tiers"],
              NA if d["z"] is None else f"{d['z']:.2f}", d["lemmas"])
             for i, d in enumerate(forms.head(n).iter_rows(named=True), 1)))

    def correlations(self) -> str:
        c = self.ctx["correlations"].sort("source")
        return "Spearman correlation of each source against the mean of the others (leave-one-out).\n\n" + _table(
            ["source", "spearman", "n"], c.select("source", "spearman", "n").iter_rows())


def render_report(ctx: dict, previous_rows: pl.DataFrame | None, built: str | None = None) -> str:
    """The Markdown report; ``built`` is the only variable line (defaults to today, UTC)."""
    r = _Report(ctx, previous_rows)
    built = built or datetime.now(UTC).date().isoformat()
    sections = [
        ("Sources", r.sources),
        ("Output", r.output),
        ("Row counts", r.counts),
        ("Gold accuracy", r.gold),
        ("Model", r.model),
        ("Frequency pairs", r.freq_pairs),
        ("Diff against the previous build", r.diff),
        ("Stress conflicts between sources", r.conflicts),
        ("Homographs split 50/50", r.even_splits),
        ("Largest frequency disagreements", r.disagreements),
        ("Low-confidence predictions left out", r.low_confidence),
        ("Most frequent forms without attested stress", r.unattested),
        ("Source correlations", r.correlations),
    ]
    head = f"# Dictionary QA report\n\nBuilt: {built}\n"
    return "\n".join([head, *(f"## {title}\n\n{body()}\n" for title, body in sections)])


def write_report(ctx: dict, previous_rows: pl.DataFrame | None, path: Path = config.OUT_REPORT) -> None:
    """Write ``out/report.md`` (§9) from the pipeline's full context."""
    fetch.atomic_write(path, render_report(ctx, previous_rows).encode("utf-8"))
