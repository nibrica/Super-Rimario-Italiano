"""OpenSubtitles 2018 word counts (source "opensubtitles")."""

from pathlib import Path

import polars as pl

from .. import config
from .freq import from_counts

SOURCE = "opensubtitles"


def read_counts(path: Path) -> pl.DataFrame:
    """The raw `word count` lines as (form, count)."""
    return pl.read_csv(
        path, separator=" ", has_header=False, quote_char=None,
        schema={"form": pl.String, "count": pl.Int64},
    )


def extract(raw_dir: Path) -> dict[str, pl.DataFrame]:
    """Counts from ``raw_dir/it_full.txt``; total tokens include dropped rows."""
    counts = read_counts(raw_dir / config.OPENSUBTITLES_FILE)
    return from_counts(counts, int(counts["count"].sum()), SOURCE)
