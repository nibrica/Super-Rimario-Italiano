"""The output CSV (§8) and out/ATTRIBUTION.md (§1)."""

import hashlib
from pathlib import Path

import polars as pl

from . import config, schema
from .fetch import atomic_write

ROWS = {"word": pl.String, "stress": pl.Int16, "zipf": pl.Int32, "flags": pl.Int32}


def _any_tag(tags: tuple[str, ...]) -> pl.Expr:
    return pl.any_horizontal(pl.col("tags").list.contains(t) for t in tags)


def _bit(cond: pl.Expr, bit: int) -> pl.Expr:
    return pl.when(cond.fill_null(False)).then(bit).otherwise(0)


def sort_rows(rows: pl.DataFrame) -> pl.DataFrame:
    """Sort by reversed word (code-point order), then stress, then flags (§8)."""
    return (
        rows.with_columns(_rev=pl.col("word").str.reverse())
        .sort("_rev", "stress", "flags").drop("_rev")
    )


def to_rows(entries: pl.DataFrame) -> pl.DataFrame:
    """ENTRIES -> output rows ``word, stress, zipf (Zipf × 100), flags``, sorted."""
    flags = (
        _bit(~pl.col("is_default"), schema.FLAG_NON_DEFAULT)  # null counts as default
        + _bit(pl.col("tier") == "predicted", schema.FLAG_PREDICTED)
        + _bit(_any_tag(schema.VULGAR_TAGS), schema.FLAG_VULGAR)
        + _bit(_any_tag(schema.ARCHAIC_TAGS), schema.FLAG_ARCHAIC)
        + _bit(pl.col("is_proper"), schema.FLAG_PROPER)
    )
    rows = entries.select(
        word=pl.col("form"),
        stress=pl.col("stress_idx"),
        zipf=(pl.col("zipf") * 100).round(0).clip(lower_bound=0).fill_null(0),
        flags=flags,
    )
    return sort_rows(schema.conform(rows, ROWS))


def render(rows: pl.DataFrame) -> bytes:
    """The CSV bytes: 3 fields, or 4 when flags ≠ 0; ``\\n`` line endings; no header."""
    three = pl.concat_str("word", "stress", "zipf", separator=",")
    line = pl.when(pl.col("flags") != 0).then(pl.concat_str(three, "flags", separator=",")).otherwise(three)
    return "".join(f"{s}\n" for s in rows.select(line).to_series()).encode("utf-8")


def write_csv(rows: pl.DataFrame, path: Path = config.OUT_CSV) -> str:
    """Write the dictionary atomically (rows re-sorted); return its sha256 hex."""
    data = render(sort_rows(rows))
    atomic_write(path, data)
    return hashlib.sha256(data).hexdigest()


def read_csv(source: Path | bytes) -> pl.DataFrame:
    """Read an output CSV (a path or its bytes), new or old (``word,stress,count``) format.

    Flags are 0 when absent; for the old format the third column holds raw
    counts, not Zipf × 100. A missing path or an empty file gives an empty frame.
    """
    data = source if isinstance(source, bytes) else source.read_bytes() if source.exists() else b""
    if not data.strip():
        return schema.empty(ROWS)
    rows = pl.read_csv(data, has_header=False, schema=ROWS, quote_char=None, missing_columns="insert")
    if rows["zipf"].null_count():
        raise ValueError(f"{source if isinstance(source, Path) else 'CSV'}: a line has fewer than 3 fields")
    return rows.with_columns(pl.col("flags").fill_null(0))


def attribution_text(sources: list[dict], lock: dict) -> str:
    """The Markdown of ATTRIBUTION.md (deterministic: dates come from the lock)."""
    out = [
        "# Attribution",
        "",
        "The dictionary `parole-accenti-frequenze.csv` is built from the sources below. "
        "It is a derivative of their data and is distributed under the terms of the "
        "[Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/) "
        "licence (CC BY-SA 4.0), as their licences require; anyone who shows or redistributes it "
        "must keep this notice or link to it. The build code is licensed under GPL-3.0-or-later.",
        "",
    ]
    for s in sources:
        e = lock.get(s["id"], {})
        out += [
            f"## {s['name']}", "",
            f"- **Provides:** {s['provides']}",
            f"- **Licence:** [{s['license']}]({s['license_url']})",
            f"- **Homepage:** <{s['homepage']}>",
            f"- **Attribution:** {s['attribution']}",
            "- **Cite:**",
            *(f"  - {c['text']} <{c['url']}>" if c.get("url") else f"  - {c['text']}" for c in s["cite"]),
        ]
        version = [
            (label, e.get(key)) for label, key in (
                ("URL", "url"), ("Version", "version"), ("File", "file"), ("SHA-256", "sha256"),
                ("Size", "size"), ("ETag", "etag"), ("Last-Modified", "last_modified"),
                ("Fetched", "fetched_at"), ("Copied from the repository mirror", "mirror"),
            ) if e.get(key) not in (None, "")
        ]
        if version:
            out.append("- **Version used:**")
            out += [f"  - {label}: `{value}`" for label, value in version]
        else:
            out.append("- **Version used:** not recorded")
        out.append("")
    return "\n".join(out)


def write_attribution(sources: list[dict], lock: dict, path: Path = config.OUT_ATTRIBUTION) -> None:
    """Write ATTRIBUTION.md: every source, its licence, citations and the fetched version."""
    atomic_write(path, attribution_text(sources, lock).encode("utf-8"))
