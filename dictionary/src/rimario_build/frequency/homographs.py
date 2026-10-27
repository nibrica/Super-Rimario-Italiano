"""Split a spelling's merged frequency among its output rows.

``zipf(row) = zipf(form) + log10(share(row))``, one row per (form, stress_idx)
(vowel-quality variants are already one row). A form with one row gets
share 1 ("single"). For several rows the first applicable rule below splits
them into two groups, and each group is split again recursively by the same
rules:

1. "capitalization": proper rows (``is_proper``) vs the others,
   ``share_proper = (cap + α) / (cap + lower + 2α)`` from Leipzig's capitalized
   mid-sentence and all-lowercase occurrences (sentence-initial and all-caps
   ones say nothing); skipped below ``config.CAPITALIZATION_MIN_COUNT`` of them.
   Applied before the context rule because a proper noun takes no article.
2. "function_word": rows with a ``config.FUNCTION_POS`` reading vs the others,
   which get ``1 - config.FUNCTION_WORD_SHARE``.
3. "minor": rows tagged archaic, poetic, literary, obsolete or rare vs untagged
   rows, which get ``1 - config.MINOR_READING_SHARE``.
4. "participle": the participle row of a ``config.PARTICIPLE_ENDINGS`` form vs
   verb-only rows stressed earlier (imperative + clitic): ``config.PARTICIPLE_SHARE``.
5. "context": the nominal vs the verbal side (config.NOMINAL_POS / VERBAL_POS;
   a row with a noun and a verb reading is on both), when every row is on a
   side, not every row on both, and the form has at least
   ``config.CONTEXT_MIN_CUES`` cues: ``share_verbal = (v + α) / (v + n + 2α)``.
   Each side's share is divided by lemma frequency: a row only on that side
   counts all its lemmas, a row on both sides only that side's lemmas (see
   ``_side_lemmas``: àncora's verbal reading is *ancorare*, not *ancora*);
   equally if the side has no lemma frequency.
6. "lemma_ratio": each row's lemmas not shared with the other rows, weighted by
   their merged frequency (``10 ** zipf`` of the lemma spelling); applies when
   every row has such a lemma (any POS, e.g. *sùbito* adv vs *subìto* of subire).
7. "even": 1/n, listed in ``even_splits`` with the reason.

A row's zipf is never below ``config.READING_MIN_ZIPF``, so no row exports as 0,
and the default row of a corpus form is never below the lexicon-only band (it
gets the band's top + ``config.LEXICON_ONLY_STEP``), so a split can't rank an
attested word under the forms no corpus has.

A row's ``share_method`` is the rule of the top-level split. ``is_default`` is
the largest share; ties go to the better tier (schema.TIER_ORDER), then the
lower stress_idx, then the lemmas.
"""

import logging
from dataclasses import dataclass
from itertools import groupby
from operator import itemgetter

import polars as pl

from .. import config, schema
from ..schema import ENTRIES, conform

EVEN_SPLITS = {"form": pl.String, "stress_idxs": pl.List(pl.Int16), "reason": pl.String}
MINOR_TAGS = frozenset(schema.ARCHAIC_TAGS) | {"rare"}
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Signals:
    """Evidence for one form: nominal/verbal cue counts and Leipzig casing counts."""

    nominal: int = 0
    verbal: int = 0
    cap_count: int = 0
    lower_count: int = 0


def cue_classes() -> dict[str, str]:
    """Cue -> "nominal"/"verbal" (config.AMBIGUOUS_CUES are ignored)."""
    return {c: "nominal" for c in config.NOMINAL_CUES} | {c: "verbal" for c in config.VERBAL_CUES}


def _sides(pos: list[str] | None) -> set[str]:
    """The context sides of a row with POS ``pos`` (config.py, "Context sides")."""
    pos = set(pos or [])
    sides = set()
    if pos & config.NOMINAL_POS or ("adj" in pos and "verb" not in pos):
        sides.add("nominal")
    if pos & config.VERBAL_POS:
        sides.add("verbal")
    return sides


def _distinct_lemma_weights(rows: list[dict], lemma_freq: dict[str, float]) -> list[float] | None:
    """Per row, the summed frequency of its lemmas no other row has; None if any row has none."""
    weights = []
    for i, r in enumerate(rows):
        others = {l for j, o in enumerate(rows) if j != i for l in o["lemmas"] or []}
        w = sum(lemma_freq.get(l, 0.0) for l in sorted(set(r["lemmas"] or []) - others))
        if w <= 0:
            return None
        weights.append(w)
    return weights


def _side_lemmas(row: dict, side: str, both: bool) -> list[str]:
    """The lemmas of ``row`` that count on ``side``: all of them, unless the row
    is on both sides; then its infinitives (-re, -rsi) on the verbal side (all
    with an adverb reading), its other lemmas on the nominal side."""
    lemmas = row["lemmas"] or []
    if not both or (side == "verbal" and "adv" in (row["pos"] or [])):
        return lemmas
    return [l for l in lemmas if l.endswith(("re", "rsi")) == (side == "verbal")]


def _participle(form: str, rows: list[dict]) -> list[bool] | None:
    """Rows that are the participle of a participle-vs-imperative+clitic form, or None."""
    if not form.endswith(config.PARTICIPLE_ENDINGS):
        return None
    flags = [r["stress_idx"] == len(form) - 3 and "verb" in (r["pos"] or []) for r in rows]
    if sum(flags) != 1 or any(
        not f and (r["stress_idx"] >= len(form) - 3 or set(r["pos"] or []) != {"verb"}) for f, r in zip(flags, rows)
    ):
        return None
    return flags


def shares(
    form: str, rows: list[dict], sig: Signals, lemma_freq: dict[str, float]
) -> tuple[list[float], str, list[str]]:
    """Shares of ``rows`` (one form), the method used, and the reasons of any even split."""
    n = len(rows)
    if n == 1:
        return [1.0], "single", []
    alpha = config.CONTEXT_PRIOR

    def two_groups(in_a: list[bool], p_a: float, method: str):
        out, evens = [0.0] * n, []
        for flag, p in ((True, p_a), (False, 1 - p_a)):
            idx = [i for i in range(n) if in_a[i] == flag]
            sub, _, sub_evens = shares(form, [rows[i] for i in idx], sig, lemma_freq)
            evens += [f"{e} ({method} group)" for e in sub_evens]
            for i, s in zip(idx, sub):
                out[i] = p * s
        return out, method, evens

    def split_off(flags: list[bool]) -> bool:
        return any(flags) and not all(flags)

    proper = [bool(r["is_proper"]) for r in rows]
    cased = sig.cap_count + sig.lower_count
    if split_off(proper) and cased >= config.CAPITALIZATION_MIN_COUNT:
        return two_groups(proper, (sig.cap_count + alpha) / (cased + 2 * alpha), "capitalization")
    function = [bool(config.FUNCTION_POS.intersection(r["pos"] or [])) for r in rows]
    if split_off(function):
        return two_groups(function, config.FUNCTION_WORD_SHARE, "function_word")
    minor = [bool(MINOR_TAGS.intersection(r["tags"] or [])) for r in rows]
    if split_off(minor):
        return two_groups(minor, config.MINOR_READING_SHARE, "minor")
    if (participle := _participle(form, rows)) is not None:
        return two_groups(participle, config.PARTICIPLE_SHARE, "participle")
    sides = [_sides(r["pos"]) for r in rows]
    if (all(sides) and not all(len(s) == 2 for s in sides) and len(set().union(*sides)) == 2
            and sig.nominal + sig.verbal >= config.CONTEXT_MIN_CUES):
        p_verbal = (sig.verbal + alpha) / (sig.verbal + sig.nominal + 2 * alpha)
        out, evens = [0.0] * n, []
        for side, p in (("nominal", 1 - p_verbal), ("verbal", p_verbal)):
            idx = [i for i in range(n) if side in sides[i]]
            w = [sum(lemma_freq.get(l, 0.0) for l in _side_lemmas(rows[i], side, len(sides[i]) == 2)) for i in idx]
            if sum(w) <= 0:
                w = [1.0] * len(idx)
                if len(idx) > 1:
                    evens.append(f"no lemma frequency ({side} side)")
            for i, x in zip(idx, w):
                out[i] += p * x / sum(w)
        return out, "context", evens
    weights = _distinct_lemma_weights(rows, lemma_freq)
    if weights is not None:
        total = sum(weights)
        return [w / total for w in weights], "lemma_ratio", []
    reason = "same lemmas" if len({tuple(r["lemmas"] or []) for r in rows}) == 1 else "no lemma unique to each row"
    return [1.0 / n] * n, "even", [reason]


def split(
    entries: pl.DataFrame, form_zipf: pl.DataFrame, contexts: pl.DataFrame, freq: pl.DataFrame
) -> dict[str, pl.DataFrame]:
    """Fill zipf/share/share_method/is_default of ``entries``; list the even splits."""
    key = ["form", "stress_idx"]
    entries = entries.sort(key)
    fz = form_zipf.select("form", form_zip=pl.col("zipf"), corpus=pl.col("estimate") == "corpus")
    entries = entries.join(fz, on="form", how="left")
    missing = entries.filter(pl.col("form_zip").is_null())["form"].n_unique()
    if missing:
        log.warning("%d entry forms have no merged frequency; using the lexicon-only minimum", missing)
        entries = entries.with_columns(pl.col("form_zip").fill_null(config.LEXICON_ONLY_MIN_ZIPF))
    multi = entries.filter(pl.len().over("form") > 1)
    multi_forms = multi.select(pl.col("form").unique())

    cue_counts = (
        contexts.join(multi_forms, on="form", how="semi")
        .with_columns(side=pl.col("cue").replace_strict(cue_classes(), default=None))
        .group_by("form")
        .agg(
            nominal=pl.col("count").filter(pl.col("side") == "nominal").sum(),
            verbal=pl.col("count").filter(pl.col("side") == "verbal").sum(),
        )
    )
    cases = (
        freq.filter(pl.col("cap_count").is_not_null())
        .join(multi_forms, on="form", how="semi")
        .group_by("form")
        .agg(pl.col("cap_count").sum(), pl.col("lower_count").fill_null(0).sum())
    )
    signals = {
        r.pop("form"): Signals(**r)
        for r in multi_forms.join(cue_counts, on="form", how="left")
        .join(cases, on="form", how="left")
        .fill_null(0)
        .iter_rows(named=True)
    }
    lemmas = multi.select(pl.col("lemmas").explode().unique().alias("form"))
    lemma_freq = {
        f: 10.0 ** z for f, z in lemmas.join(form_zipf, on="form", how="inner").select("form", "zipf").iter_rows()
    }

    share_rows, even_rows = [], []
    cols = ["form", "stress_idx", "lemmas", "pos", "tags", "is_proper"]
    for form, group in groupby(multi.sort(key).select(cols).iter_rows(named=True), key=itemgetter("form")):
        rows = list(group)
        sh, method, evens = shares(form, rows, signals[form], lemma_freq)
        share_rows += [(form, r["stress_idx"], x, method) for r, x in zip(rows, sh)]
        if evens:
            even_rows.append((form, [r["stress_idx"] for r in rows], "; ".join(evens)))

    multi_shares = pl.DataFrame(
        share_rows, schema={"form": pl.String, "stress_idx": pl.Int16, "share_m": pl.Float64, "method_m": pl.String},
        orient="row",
    )
    tier_rank = {t: i for i, t in enumerate(schema.TIER_ORDER)}
    lexicon_only_top = form_zipf.filter(pl.col("estimate") == "lexicon_only")["zipf"].max()
    default_floor = (lexicon_only_top if lexicon_only_top is not None else 0.0) + config.LEXICON_ONLY_STEP
    out = (
        entries.join(multi_shares, on=key, how="left")
        .with_columns(
            share=pl.col("share_m").fill_null(1.0),
            share_method=pl.col("method_m").fill_null("single"),
        )
        .with_columns(
            zipf=(pl.col("form_zip") + pl.col("share").log10()).clip(lower_bound=config.READING_MIN_ZIPF),
            _share=pl.col("share").round(12),
            _tier=pl.col("tier").replace_strict(tier_rank, default=len(tier_rank), return_dtype=pl.Int8),
            _lemmas=pl.col("lemmas").list.join(","),
        )
        .sort(["form", "_share", "_tier", "stress_idx", "_lemmas"], descending=[False, True, False, False, False])
        .with_columns(is_default=pl.int_range(pl.len()).over("form") == 0)
        .with_columns(
            zipf=pl.when(pl.col("is_default") & pl.col("corpus").fill_null(False))
            .then(pl.col("zipf").clip(lower_bound=default_floor)).otherwise("zipf")
        )
        .sort(key)
    )
    even = pl.DataFrame(even_rows, schema=EVEN_SPLITS, orient="row").sort("form")
    return {"entries": conform(out, ENTRIES), "even_splits": even}
