"""Helpers shared by the frequency extractors (wordfreq_it, opensubtitles, leipzig)."""

import math

import polars as pl

from .. import schema, text

COUNT_COLUMNS = ("count", "cap_count", "lower_count")   # FREQ columns a source may lack (null)


def zipf(count: float, total: float) -> float:
    """log10(count / total × 10⁹); ``total`` 1 turns a share of tokens into Zipf."""
    return math.log10(count / total * 1e9)


def normalize_forms(df: pl.DataFrame) -> pl.DataFrame:
    """NFC-lowercase ``form`` (as text.norm) and keep only allowed spellings."""
    return df.with_columns(pl.col("form").str.normalize("NFC").str.to_lowercase()).filter(
        pl.col("form").str.contains(text.ALLOWED_RE)
    )


def tables(
    freq: pl.DataFrame, source: str, total: int | None, floor: float, truncated: bool
) -> dict[str, pl.DataFrame]:
    """FREQ (absent count columns as null) and its one-row FREQ_META."""
    freq = freq.with_columns(
        [pl.lit(None, pl.Int64).alias(c) for c in COUNT_COLUMNS if c not in freq.columns], source=pl.lit(source)
    ).sort("form")
    meta = pl.DataFrame({
        "source": [source], "total_tokens": [total], "floor_zipf": [floor],
        "complete": [True], "truncated": [truncated],
    })
    return {"freq": schema.conform(freq, schema.FREQ), "meta": schema.conform(meta, schema.FREQ_META)}


def from_counts(
    counts: pl.DataFrame, total: int, source: str, min_count: int | None = None
) -> dict[str, pl.DataFrame]:
    """FREQ + FREQ_META from raw (form, count[, cap_count, lower_count]) rows over ``total`` tokens.

    Rows that normalize to the same form are summed. The floor is the Zipf of
    ``min_count`` (default: the smallest count in ``counts``); the list counts
    as truncated when that is above 1.
    """
    min_count = min_count or counts["count"].min()
    present = [c for c in COUNT_COLUMNS if c in counts.columns]
    freq = (
        normalize_forms(counts)
        .group_by("form")
        .agg(pl.col(present).sum())
        .with_columns(zipf=(pl.col("count") / total * 1e9).log10())
    )
    return tables(freq, source, total, zipf(min_count, total), min_count > 1)
