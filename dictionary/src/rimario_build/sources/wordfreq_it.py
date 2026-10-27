"""wordfreq's Italian list as Zipf values (source "wordfreq")."""

from pathlib import Path

import polars as pl
from wordfreq import get_frequency_dict

from .. import config
from .freq import normalize_forms, tables, zipf

SOURCE = "wordfreq"


def from_frequencies(freqs: dict[str, float]) -> dict[str, pl.DataFrame]:
    """FREQ + FREQ_META from wordfreq's {word: share of tokens}.

    wordfreq's tokenizer splits single-letter elisions (``l'``, ``c'``) but keeps
    longer ones whole (``dell'uomo``, ``quest'anno``); such an entry counts for
    its right-hand word, as in leipzig.scan and OpenSubtitles. Rows that then
    normalize to the same form add up their shares. The floor is the smallest
    Zipf in the whole list: wordfreq drops every word below it.
    """
    raw = pl.DataFrame(
        {"form": list(freqs), "f": list(freqs.values())},
        schema={"form": pl.String, "f": pl.Float64},
    )
    freq = (
        normalize_forms(raw.with_columns(pl.col("form").str.split("'").list.last()))
        .group_by("form")
        .agg(pl.col("f").sum())
        .with_columns(zipf=(pl.col("f") * 1e9).log10().round(2))
    )
    return tables(freq, SOURCE, None, round(zipf(raw["f"].min(), 1), 2), True)


def extract(raw_dir: Path) -> dict[str, pl.DataFrame]:
    """The installed wordfreq package's Italian list; ``raw_dir`` is unused."""
    return from_frequencies(get_frequency_dict("it", config.WORDFREQ_LIST))
