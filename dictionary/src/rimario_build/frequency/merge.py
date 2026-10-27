"""Merge the frequency sources into one Zipf value per spelling.

Each lexicon form gets one observation per source, all in Zipf:

* present: the source's Zipf, weight ``W_s * r_s`` (source weight times reliability), with
  ``r_s = min(1, count / RELIABLE_COUNT)`` for counted sources and, for
  wordfreq (no counts), a linear ramp from ``WORDFREQ_MIN_RELIABILITY`` at its
  floor to 1 at ``WORDFREQ_RELIABLE_ZIPF``;
* missing from a ``complete`` source while present in another: an upper bound
  ``floor_s - MISSING_OFFSET`` with weight ``W_s * MISSING_WEIGHT_FACTOR``
  used only where it lies below the weighted mean of the present
  observations (it may pull a word down, never up).

Robustness: an observation (present or bound) more than
``OUTLIER_DISTANCE`` from the mean of the two others, both present and agreeing
within ``OUTLIER_AGREEMENT``, has its weight capped at ``factor * W_s``. The
factor ramps linearly from 1 at ``OUTLIER_DISTANCE`` to ``OUTLIER_WEIGHT_FACTOR``
at ``OUTLIER_DISTANCE + OUTLIER_RAMP``, so the weight has no step where one more
occurrence crosses the threshold; the cap never raises a weight (a weak
observation, e.g. 2 occurrences, keeps its own). ``zipf`` is the weighted mean.

Accent-dropping typos: the unaccented spelling of a final-accent word (*cosi*
for *così*, *citta* for *città*) is mostly the accented word typed without its
accent (or as ``citta'``): in OpenSubtitles about as often as the accented
spelling. Where the twins (summed) are the more frequent spelling both merged
and in ``config.ACCENT_TWIN_REFERENCE`` (Leipzig news, edited text; there by at
least ``ACCENT_TWIN_MIN_GAP``, the reference's missing-word bound standing in
for an absent spelling), the unaccented spelling's Zipf is capped at the twins'
merged Zipf plus the difference between the two spellings in the reference,
and never below the lexicon-only band: *pero* gets *però*'s Zipf minus 2.25,
while *papa*/*papà*, *se*/*sé*, *cattivo*/*cattivò* keep theirs.

Forms in no corpus get the lexicon-only fallback ``top - LEXICON_ONLY_STEP * (max_n - n_lexicons)``
with ``top = max(min_floor - LEXICON_ONLY_OFFSET, LEXICON_ONLY_MIN_ZIPF + LEXICON_ONLY_STEP * max_n)``
and ``max_n`` the largest n_lexicons: never above ``min_floor - 0.5`` unless the
minimum applies (see config.py for why it exists). A corpus estimate is never
below that band: it gets at least its top + ``LEXICON_ONLY_STEP``.

``disagreements`` lists the observations whose weight the robustness rule
actually cut; ``weight_factor`` is the final weight as a fraction of ``W_s``.
"""

import logging

import polars as pl

from .. import config, text
from ..schema import FORM_ZIPF, conform, empty

DISAGREEMENTS = {
    "form": pl.String, "source": pl.String, "zipf_source": pl.Float64,
    "zipf_others": pl.Float64, "weight_factor": pl.Float64,
}
CORRELATIONS = {"source": pl.String, "spearman": pl.Float64, "n": pl.Int64}
TWIN_CAPS = {"form": pl.String, "twin": pl.Float64, "cap": pl.Float64}
FINAL_ACCENT = "[" + "".join(sorted(text.ACCENTED)) + "]$"
log = logging.getLogger(__name__)


def _present(freq: pl.DataFrame) -> pl.DataFrame:
    """One row per (form, source) actually seen in that source."""
    return (
        freq.filter(pl.col("zipf").is_not_null() & (pl.col("count").is_null() | (pl.col("count") > 0)))
        .group_by("form", "source")
        .agg(pl.col("zipf").max(), pl.col("count").max())
    )


def _reliability(floor: float) -> pl.Expr:
    """r_s (reliability) of a present observation; ``floor`` is its source's floor."""
    counted = (pl.col("count") / config.RELIABLE_COUNT).clip(upper_bound=1.0)
    lo = config.WORDFREQ_MIN_RELIABILITY
    span = max(config.WORDFREQ_RELIABLE_ZIPF - floor, 1e-9)
    ramp = (lo + (1 - lo) * (pl.col("zipf") - floor) / span).clip(lo, 1.0)
    return pl.when(pl.col("count").is_not_null()).then(counted).otherwise(ramp)


def lexicon_only_zipf(min_floor: float, n_lexicons: pl.Expr | int, max_n: int) -> pl.Expr | float:
    """Lexicon-only fallback for a form found in no corpus, ordered by n_lexicons."""
    step = config.LEXICON_ONLY_STEP
    top = max(min_floor - config.LEXICON_ONLY_OFFSET, config.LEXICON_ONLY_MIN_ZIPF + step * max_n)
    return top - step * (max_n - n_lexicons)


def spearman(a: pl.Expr, b: pl.Expr) -> pl.Expr:
    """Spearman correlation: Pearson correlation of average ranks."""
    return pl.corr(a.rank("average"), b.rank("average"))


def correlations(present: pl.DataFrame, sources: list[str]) -> pl.DataFrame:
    """Validation: Spearman of each source vs the mean of the others, on forms present in all."""
    wide = None
    for s in sources:
        col = present.filter(pl.col("source") == s).select("form", pl.col("zipf").alias(s))
        wide = col if wide is None else wide.join(col, on="form", how="inner")
    wide = wide.sort("form")
    rows = []
    for s in sources:
        others = [o for o in sources if o != s]
        rho = wide.select(spearman(pl.col(s), pl.mean_horizontal(others))).item() if others and wide.height > 1 else None
        rows.append({"source": s, "spearman": rho, "n": wide.height})
    return pl.DataFrame(rows, schema=CORRELATIONS)


def _observations(lex: pl.DataFrame, present: pl.DataFrame, meta: pl.DataFrame) -> pl.DataFrame:
    """Per source s: z_<s>/w_<s> (observation or active bound, weight) and p_<s> (present)."""
    sources = meta["source"].to_list()
    wide = lex
    for s, floor in zip(sources, meta["floor_zipf"]):
        obs = present.filter(pl.col("source") == s).select(
            "form", pl.col("zipf").alias(f"z_{s}"), (config.SOURCE_WEIGHTS[s] * _reliability(floor)).alias(f"w_{s}"),
        )
        wide = wide.join(obs, on="form", how="left").with_columns(pl.col(f"z_{s}").is_not_null().alias(f"p_{s}"))
    num = pl.sum_horizontal(pl.col(f"w_{s}") * pl.col(f"z_{s}") for s in sources)
    den = pl.sum_horizontal(pl.col(f"w_{s}") for s in sources)
    wide = wide.with_columns(
        n_sources=pl.sum_horizontal(pl.col(f"p_{s}") for s in sources).cast(pl.Int8), _mean=num / den,
    )
    bounds = []
    for s, floor, complete in zip(sources, meta["floor_zipf"], meta["complete"]):
        if not complete:
            continue
        bound = floor - config.MISSING_OFFSET
        active = ~pl.col(f"p_{s}") & (pl.col("n_sources") > 0) & (pl.col("_mean") > bound)
        bounds += [
            pl.when(active).then(bound).otherwise(pl.col(f"z_{s}")).alias(f"z_{s}"),
            pl.when(active).then(config.SOURCE_WEIGHTS[s] * config.MISSING_WEIGHT_FACTOR)
            .otherwise(pl.col(f"w_{s}")).alias(f"w_{s}"),
        ]
    return wide.with_columns(bounds).drop("_mean")


def _robust_weights(wide: pl.DataFrame, sources: list[str]) -> pl.DataFrame:
    """Cap outlier weights (robustness); c_<s> marks a weight actually cut, zo_<s> the others' mean."""
    cols = []
    for s in sources:
        others = [o for o in sources if o != s]
        if len(others) < 2:
            continue
        zo = [pl.col(f"z_{o}") for o in others]
        mean = pl.mean_horizontal(zo)
        ramp = (((pl.col(f"z_{s}") - mean).abs() - config.OUTLIER_DISTANCE) / config.OUTLIER_RAMP).clip(0.0, 1.0)
        factor = 1 - (1 - config.OUTLIER_WEIGHT_FACTOR) * ramp
        applies = (
            pl.all_horizontal(pl.col(f"p_{o}") for o in others)
            & pl.col(f"z_{s}").is_not_null()
            & (pl.max_horizontal(zo) - pl.min_horizontal(zo) <= config.OUTLIER_AGREEMENT)
        )
        capped = pl.min_horizontal(pl.col(f"w_{s}"), factor * config.SOURCE_WEIGHTS[s])
        cols += [
            pl.when(applies).then(capped).otherwise(pl.col(f"w_{s}")).alias(f"w_{s}"),
            (applies & (capped < pl.col(f"w_{s}"))).alias(f"c_{s}"),
            mean.alias(f"zo_{s}"),
        ]
    return wide.with_columns(cols)


def _disagreements(wide: pl.DataFrame, sources: list[str]) -> pl.DataFrame:
    """The cut observations, largest |zipf_source - zipf_others| first."""
    cut = [
        wide.filter(pl.col(f"c_{s}")).select(
            "form", pl.lit(s).alias("source"), pl.col(f"z_{s}").alias("zipf_source"),
            pl.col(f"zo_{s}").alias("zipf_others"),
            (pl.col(f"w_{s}") / config.SOURCE_WEIGHTS[s]).alias("weight_factor"),
        )
        for s in sources if f"c_{s}" in wide.columns
    ]
    return (
        pl.concat([conform(c, DISAGREEMENTS) for c in cut] or [empty(DISAGREEMENTS)])
        .with_columns(d=(pl.col("zipf_source") - pl.col("zipf_others")).abs())
        .sort(["d", "form", "source"], descending=[True, False, False])
        .head(config.DISAGREEMENTS_KEEP)
    )


def accent_twin_caps(form_zipf: pl.DataFrame, present: pl.DataFrame, meta: pl.DataFrame) -> pl.DataFrame:
    """(form, twin, cap) for unaccented spellings of final-accent lexicon forms (module docstring).

    ``twin`` is the twins' summed merged Zipf; only spellings at least
    ``ACCENT_TWIN_MIN_GAP`` rarer than their twins in the reference get a cap.
    """
    meta = meta.filter(pl.col("source") == config.ACCENT_TWIN_REFERENCE)
    if meta.is_empty():
        return empty(TWIN_CAPS)
    ref = present.filter(pl.col("source") == config.ACCENT_TWIN_REFERENCE).select("form", "zipf")
    missing = meta["floor_zipf"].item() - config.MISSING_OFFSET if meta["complete"].item() else None
    return (
        form_zipf.filter(pl.col("form").str.contains(FINAL_ACCENT))
        .select("zipf", twin="form", form=pl.col("form").map_elements(text.strip_accents, return_dtype=pl.String))
        .join(ref.rename({"form": "twin", "zipf": "twin_ref"}), on="twin", how="inner")
        .group_by("form")
        .agg(twin=(10 ** pl.col("zipf")).sum().log10(), twin_ref=(10 ** pl.col("twin_ref")).sum().log10())
        .join(ref.rename({"zipf": "form_ref"}), on="form", how="left")
        .with_columns(pl.col("form_ref").fill_null(pl.lit(missing, pl.Float64)))
        .filter(pl.col("form_ref") <= pl.col("twin_ref") - config.ACCENT_TWIN_MIN_GAP)
        .select("form", "twin", cap=pl.col("twin") + pl.col("form_ref") - pl.col("twin_ref"))
        .drop_nulls()
    )


def merge(freq: pl.DataFrame, meta: pl.DataFrame, lexicon_forms: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """Merged Zipf per lexicon form, logged outliers and source correlations."""
    meta = meta.sort("source")
    sources = meta["source"].to_list()
    min_floor = min(meta["floor_zipf"])
    present = _present(freq)
    lex = lexicon_forms.group_by("form").agg(pl.col("n_lexicons").max().fill_null(0))
    max_n = lex["n_lexicons"].max() or 0

    wide = _robust_weights(_observations(lex, present, meta), sources)
    num = pl.sum_horizontal(pl.col(f"w_{s}") * pl.col(f"z_{s}") for s in sources)
    den = pl.sum_horizontal(pl.when(pl.col(f"z_{s}").is_not_null()).then(pl.col(f"w_{s}")) for s in sources)
    corpus = pl.col("n_sources") > 0
    floor = lexicon_only_zipf(min_floor, max_n, max_n) + config.LEXICON_ONLY_STEP   # corpus estimates' minimum
    form_zipf = wide.select(
        "form",
        pl.when(corpus).then(num / den)
        .otherwise(lexicon_only_zipf(min_floor, pl.col("n_lexicons"), max_n)).alias("zipf"),
        "n_sources",
        "n_lexicons",
        pl.when(corpus).then(pl.lit("corpus")).otherwise(pl.lit("lexicon_only")).alias("estimate"),
    )
    if n := form_zipf.filter(corpus & (pl.col("zipf") < floor)).height:
        log.warning("%d corpus estimates raised to %.2f, above the lexicon-only band", n, floor)
    form_zipf = form_zipf.join(accent_twin_caps(form_zipf, present, meta), on="form", how="left").with_columns(
        capped=corpus & (pl.col("twin") >= pl.col("zipf")) & (pl.col("cap") < pl.col("zipf"))
    )
    log.info("%d unaccented spellings capped below their final-accent twin", form_zipf["capped"].sum())
    form_zipf = form_zipf.with_columns(
        pl.when("capped").then("cap").otherwise("zipf").alias("zipf")
    ).with_columns(
        pl.when(corpus).then(pl.col("zipf").clip(lower_bound=floor)).otherwise("zipf").alias("zipf")
    ).sort("form")
    return {
        "form_zipf": conform(form_zipf, FORM_ZIPF),
        "disagreements": conform(_disagreements(wide, sources), DISAGREEMENTS),
        "correlations": correlations(present, sources),
    }
