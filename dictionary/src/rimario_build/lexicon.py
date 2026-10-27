"""Which forms go in (§7): inclusion rules, collapsing readings into output rows, overrides (§5.5)."""

import math
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import polars as pl
from wordfreq import get_frequency_dict

from . import config, schema, text

OVERRIDES = {
    "form": pl.String,
    "stress_idx": pl.Int16,
    "action": pl.String,            # add | remove | fix
    "note": pl.String,
}
EXCLUDED = {"form": pl.String, "reason": pl.String}

ACTIONS = ("add", "remove", "fix")
TIER_RANK = {t: i for i, t in enumerate(schema.TIER_ORDER)}
OVERRIDE_PROVENANCE = "override:curation"
KAIKKI = ("kaikki_en", "kaikki_it")
SINGLE_VOWEL = "paradigm.single_vowel"     # paradigm's rule for one-vowel words: no lemma behind it

# Why a form is left out. A form with no kept reading gets the first reason
# (in this order) among its readings; a form with no reading at all gets
# "chars", "low_confidence" (the model's prediction was withheld) or "no_stress".
REASONS = (
    "chars", "abbreviation", "misspelling", "roman_numeral", "loanword", "proper_no_kaikki",
    "proper_no_freq", "low_confidence", "not_in_lexicon", "no_stress", "override_remove",
)

_LOANWORD_RE = "[" + "".join(sorted(config.LOANWORD_CHARS)) + "]"
_ITALIAN_SUFFIX_RE = (
    f"^.{{{config.LOANWORD_MIN_STEM},}}(" + "|".join(config.LOANWORD_ITALIAN_SUFFIXES) + ")$"
)
_ROMAN_RE = "^[ivxlcdm]+$"
_EMPTY_TAGS = pl.lit([], dtype=pl.List(pl.String))


def read_tsv(path: Path, columns: dict) -> Iterator[tuple[int, str, list[str]]]:
    """(line number, line, stripped fields padded to ``columns``) of a curation TSV.

    Skips blank lines, ``#`` comments and the header line (first field equal to
    the first column name); raises ValueError on a line with too many fields.
    """
    header = next(iter(columns))
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = [f.strip() for f in line.split("\t")]
        if len(fields) > len(columns):
            raise ValueError(f"{path}:{n}: expected at most {len(columns)} tab-separated fields: {line!r}")
        if fields[0] != header:
            yield n, line, fields + [""] * (len(columns) - len(fields))


def stress_error(form: str, idx: str) -> str | None:
    """Why ``idx`` (as written in a TSV) is not a valid stress of ``form``, or None."""
    if not idx.isdigit():
        return "stress_idx must be a non-negative integer"
    stress = int(idx)
    if stress >= len(form) or form[stress] not in text.VOWELS:
        return f"stress_idx {stress} is not a vowel of {form!r}"
    accents = text.accent_positions(form)
    if accents and accents[-1] != stress:
        return "stress_idx disagrees with the accent written in the form"
    return None


def load_overrides(path: Path = config.OVERRIDES_TSV) -> pl.DataFrame:
    """Read and validate ``overrides.tsv``; raise ValueError naming the bad line.

    A missing file means no overrides.
    """
    if not path.exists():
        return schema.empty(OVERRIDES)
    rows = []
    for n, line, (form, idx, action, note) in read_tsv(path, OVERRIDES):
        form = text.norm(form)
        error = None
        if action not in ACTIONS:
            error = f"action must be one of {', '.join(ACTIONS)}"
        elif not text.is_allowed(form):
            error = "form has characters outside config.ALLOWED_CHARS"
        elif idx:
            error = stress_error(form, idx)
        elif action != "remove":
            error = f"{action} needs a stress_idx"
        if error:
            raise ValueError(f"{path}:{n}: {error}: {line!r}")
        rows.append((form, int(idx) if idx else None, action, note or None))
    return pl.DataFrame(rows, schema=OVERRIDES, orient="row")


def _flag(keys: pl.DataFrame, name: str) -> pl.DataFrame:
    """Unique ``keys`` with a True column ``name``, for left-join membership tests."""
    return keys.unique().with_columns(pl.lit(True).alias(name))


def _reading_tags(forms: pl.DataFrame) -> pl.DataFrame:
    """Usage tags of each (form, lemma, pos) reading.

    Within a source a tag needs every row of the reading: one archaic table
    cell (siète, "traditional") doesn't flag essere's siete, nor one clipping
    or derogatory sense (auto, pizzo) the whole noun. A form-of entry inherits
    a vulgar tag from its lemma's entry, so there one row is enough. Sources
    are then united, except that an archaic-family tag on a lemma entry both
    Kaikki sources have needs both (kaikki_en marks a whole page archaic for an
    archaic gender: stazione, gente).
    """
    by_source = ["form", "lemma", "pos", "source"]
    reading = ["form", "lemma", "pos"]
    n_kaikki = (
        forms.filter(pl.col("source").is_in(KAIKKI)).group_by(reading)
        .agg(n_kaikki=pl.col("source").n_unique())
    )
    tag, lemma_entry = pl.col("tags"), pl.col("form").eq_missing(pl.col("lemma"))
    return (
        forms.select(*by_source, "tags").with_columns(n=pl.len().over(by_source))
        .explode("tags").drop_nulls("tags")
        .group_by(*by_source, "tags").agg(c=pl.len(), n=pl.col("n").first())
        .filter((pl.col("c") == pl.col("n")) | (tag.is_in(schema.VULGAR_TAGS) & ~lemma_entry))
        .group_by(*reading, "tags").agg(k=pl.col("source").is_in(KAIKKI).sum())
        .join(n_kaikki, on=reading, how="left", nulls_equal=True)
        .filter(~(tag.is_in(schema.ARCHAIC_TAGS) & lemma_entry & (pl.col("n_kaikki") == len(KAIKKI))).fill_null(True)
                | (pl.col("k") == len(KAIKKI)))
        .group_by(reading).agg(tag.sort())
    )


def _zipf(lang: str) -> pl.DataFrame:
    """wordfreq's Zipf of every word of ``lang``, in a column named ``lang``."""
    words = get_frequency_dict(lang, config.WORDFREQ_LIST)
    return pl.DataFrame(
        {"form": list(words), lang: [math.log10(f * 1e9) for f in words.values()]},
        schema={"form": pl.String, lang: pl.Float64},
    )


def _loanwords(r: pl.DataFrame) -> pl.DataFrame:
    """Forms left out as loanwords (§7), judged on all their stressed readings ``r``.

    Only forms with no attested reading and no reading propagated from a lemma
    (their stress is predicted or from the single-vowel rule) are suspects.
    Such a form is out when it is spelled with j/k/w/x/y and has no Italian
    suffix (jihadisti stays), or when English uses it clearly more than
    Italian (the, time, performance) and it is no Italian function word (i).
    """
    tier = pl.col("tier")
    suspects = r.group_by("form").agg(
        italian=((tier == "attested")
                 | ((tier == "propagated") & ~pl.col("sources").list.contains(SINGLE_VOWEL))).any(),
        function_word=pl.col("pos").is_in(config.LOANWORD_ITALIAN_POS).any(),
    ).filter(~pl.col("italian"))
    form = pl.col("form")
    return (
        suspects.join(_zipf("en"), on="form", how="left").join(_zipf("it"), on="form", how="left")
        .with_columns(pl.col("en", "it").fill_null(0.0))
        .filter((form.str.contains(_LOANWORD_RE) & ~form.str.contains(_ITALIAN_SUFFIX_RE))
                | ((pl.col("en") > pl.col("it") + config.LOANWORD_EN_MARGIN) & ~pl.col("function_word")))
        .select("form", is_loanword=pl.lit(True))
    )


def select(
    forms: pl.DataFrame,
    readings: pl.DataFrame,
    freq_forms: pl.DataFrame,
    overrides: pl.DataFrame,
    low_confidence: pl.DataFrame,
) -> dict[str, pl.DataFrame]:
    """Apply the §7 inclusion rules and collapse readings into ENTRIES rows (zipf etc. null).

    ``low_confidence`` (form, stress_idx, confidence) holds the model's withheld
    predictions: a form left without any reading because of it gets that reason.
    """
    lex = _flag(forms.select("form"), "in_lex")
    freq = _flag(freq_forms.select("form"), "in_freq")
    kaikki_name = _flag(
        forms.filter(pl.col("source").is_in(KAIKKI) & (pl.col("pos") == "name")).select("form"),
        "kaikki_name",
    )
    # kaikki_en's own entries call it a misspelling, even if Morph-it lists it.
    misspelled = _flag(
        forms.filter(pl.col("source") == "kaikki_en").group_by("form")
        .agg(m=pl.col("tags").list.contains("misspelling").all()).filter("m").select("form"),
        "misspelled",
    )
    stressed = readings.filter(pl.col("stress_idx").is_not_null())
    r = (
        stressed
        .join(_reading_tags(forms), on=["form", "lemma", "pos"], how="left", nulls_equal=True)
        .join(lex, on="form", how="left").join(freq, on="form", how="left")
        .join(kaikki_name, on="form", how="left").join(misspelled, on="form", how="left")
        .join(_loanwords(stressed), on="form", how="left")
        .with_columns(
            pl.col("tags").fill_null(_EMPTY_TAGS),
            pl.col("in_lex", "in_freq", "kaikki_name", "misspelled", "is_loanword").fill_null(False),
            proper=(pl.col("pos") == "name").fill_null(False),
        )
    )
    tags = pl.col("tags")
    r = r.with_columns(
        reason=pl.when(~pl.col("form").str.contains(text.ALLOWED_RE)).then(pl.lit("chars"))
        .when(tags.list.contains("abbreviation")).then(pl.lit("abbreviation"))
        .when(tags.list.contains("misspelling") | pl.col("misspelled")).then(pl.lit("misspelling"))
        .when((pl.col("pos") == "num") & pl.col("form").str.contains(_ROMAN_RE)).then(pl.lit("roman_numeral"))
        .when(pl.col("is_loanword")).then(pl.lit("loanword"))
        .when(pl.col("proper") & ~pl.col("kaikki_name")).then(pl.lit("proper_no_kaikki"))
        .when(pl.col("proper") & ~pl.col("in_freq")).then(pl.lit("proper_no_freq"))
        .when(~pl.col("in_lex") & (pl.col("tier") != "propagated")).then(pl.lit("not_in_lexicon"))
    )
    kept = r.filter(pl.col("reason").is_null())
    # A proper reading with the spelling and stress of a common one adds nothing.
    common = _flag(kept.filter(~pl.col("proper")).select("form", "stress_idx"), "has_common")
    kept = (
        kept.join(common, on=["form", "stress_idx"], how="left")
        .filter(~(pl.col("proper") & pl.col("has_common").fill_null(False)))
    )

    entries = _collapse(kept)
    entries, removed = _apply_overrides(entries, overrides)
    excluded = _excluded(forms, r, low_confidence, entries, removed)
    return {"entries": entries, "excluded": excluded}


def _collapse(kept: pl.DataFrame) -> pl.DataFrame:
    """One row per (form, stress_idx); vowel quality is not kept (quality null).

    A tag survives if every collapsed reading carries it. A vulgar-family tag
    also survives if any reading other than a verb inflection carries it
    (cazzo: the noun, not cazzare's 1sg; but chiavi, keys, not chiavare's 2sg).
    """
    key = ["form", "stress_idx"]
    spreads = ~((pl.col("pos") == "verb") & pl.col("form").ne_missing(pl.col("lemma")))
    base = kept.group_by(key).agg(
        tier_rank=pl.col("tier").replace_strict(TIER_RANK, return_dtype=pl.Int8).min(),
        confidence=pl.col("confidence").max(),
        lemmas=pl.col("lemma").drop_nulls().unique().sort(),
        pos=pl.col("pos").drop_nulls().unique().sort(),
        is_proper=pl.col("proper").all(),
        n=pl.len(),
    )
    tags = (
        kept.select(*key, "tags", spreads=spreads.fill_null(True)).with_columns(rid=pl.int_range(pl.len()))
        .explode("tags").drop_nulls("tags")
        .group_by(*key, "tags").agg(c=pl.col("rid").n_unique(), spreads=pl.col("spreads").any())
        .join(base.select(*key, "n"), on=key)
        .filter((pl.col("c") == pl.col("n")) | (pl.col("tags").is_in(schema.VULGAR_TAGS) & pl.col("spreads")))
        .group_by(key).agg(pl.col("tags").sort())
    )
    provenance = (
        kept.select(*key, "evidence", "sources").explode("sources").drop_nulls("sources")
        .select(*key, pair=pl.col("sources") + ":" + pl.col("evidence").fill_null("none"))
        .unique().group_by(key).agg(provenance=pl.col("pair").sort().str.join(","))
    )
    out = (
        base.join(tags, on=key, how="left").join(provenance, on=key, how="left")
        .with_columns(
            quality=pl.lit(None, pl.String),
            tier=pl.col("tier_rank").replace_strict(dict(enumerate(schema.TIER_ORDER)),
                                                    return_dtype=pl.String),
            tags=pl.col("tags").fill_null(_EMPTY_TAGS),
            provenance=pl.col("provenance").fill_null(""),
            zipf=pl.lit(None), share=pl.lit(None), share_method=pl.lit(None), is_default=pl.lit(None),
        )
    )
    return _sorted(schema.conform(out, schema.ENTRIES))


def _sorted(entries: pl.DataFrame) -> pl.DataFrame:
    return entries.sort("form", "stress_idx")


def _override_row(o: dict, pool: list[dict]) -> dict:
    """An ENTRIES row for override ``o``, keeping lemmas/POS/tags of same-stress rows in ``pool``."""
    same = [e for e in pool if e["stress_idx"] == o["stress_idx"]]
    tags = set.intersection(*(set(e["tags"]) for e in same)) if same else set()
    provenance = {p for e in same for p in e["provenance"].split(",") if p} | {OVERRIDE_PROVENANCE}
    return {
        "form": o["form"], "stress_idx": o["stress_idx"], "quality": None,
        "lemmas": sorted({x for e in same for x in e["lemmas"]}),
        "pos": sorted({x for e in same for x in e["pos"]}),
        "tier": "override", "confidence": 1.0, "tags": sorted(tags),
        "is_proper": bool(same) and all(e["is_proper"] for e in same),
        "provenance": ",".join(sorted(provenance)),
        "zipf": None, "share": None, "share_method": None, "is_default": None,
    }


def _apply_overrides(entries: pl.DataFrame, overrides: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Apply ``fix`` lines, then ``add``, then ``remove`` (independent of line order).

    Returns the new entries and the forms whose every row was removed.
    """
    if overrides.is_empty():
        return entries, []
    affected = overrides.get_column("form").unique().sort()
    touched = entries.filter(pl.col("form").is_in(affected.implode()))
    by_form: dict[str, list[dict]] = defaultdict(list)
    for e in touched.to_dicts():
        by_form[e["form"]].append(e)
    lines: dict[str, list[dict]] = defaultdict(list)
    for o in overrides.to_dicts():
        lines[o["form"]].append(o)

    out, removed = [], []
    for form in affected:
        rows = by_form.get(form, [])
        had_rows = bool(rows)
        fixes = [o for o in lines[form] if o["action"] == "fix"]
        if fixes:
            rows = [_override_row(o, rows) for o in fixes]
        for o in (o for o in lines[form] if o["action"] == "add"):
            hits = [e for e in rows if e["stress_idx"] == o["stress_idx"]]
            for e in hits:
                e.update(_override_row(o, [e]))
            if not hits:
                rows.append(_override_row(o, rows))
        for o in (o for o in lines[form] if o["action"] == "remove"):
            rows = [e for e in rows if o["stress_idx"] is not None and e["stress_idx"] != o["stress_idx"]]
        if had_rows and not rows:
            removed.append(form)
        out.extend(rows)
    rest = entries.filter(~pl.col("form").is_in(affected.implode()))
    return _sorted(pl.concat([rest, pl.DataFrame(out, schema=schema.ENTRIES)])), removed


def _excluded(forms: pl.DataFrame, r: pl.DataFrame, low_confidence: pl.DataFrame,
              entries: pl.DataFrame, removed: list[str]) -> pl.DataFrame:
    """One row per lexicon or reading form left out of ``entries``, with the reason."""
    rank = {reason: i for i, reason in enumerate(REASONS)}
    by_reading = r.group_by("form").agg(
        rank=pl.col("reason").replace_strict(rank, default=len(REASONS), return_dtype=pl.Int16).min()
    )
    no_reading = (
        pl.when(~pl.col("form").str.contains(text.ALLOWED_RE)).then(rank["chars"])
        .when(pl.col("low").fill_null(False)).then(rank["low_confidence"])
        .otherwise(rank["no_stress"])
    )
    candidates = (
        pl.concat([forms.select("form").unique(), r.select("form").unique()]).unique()
        .join(by_reading, on="form", how="left")
        .join(_flag(low_confidence.select("form"), "low"), on="form", how="left")
        .select("form", rank=pl.coalesce("rank", no_reading).cast(pl.Int16))
    )
    candidates = pl.concat([
        candidates.filter(~pl.col("form").is_in(pl.Series(removed, dtype=pl.String).implode())),
        pl.DataFrame({"form": removed, "rank": [rank["override_remove"]] * len(removed)},
                     schema={"form": pl.String, "rank": pl.Int16}),
    ])
    return (
        candidates.join(entries.select("form").unique(), on="form", how="anti")
        .filter(pl.col("rank") < len(REASONS))
        .select("form", reason=pl.col("rank").replace_strict(dict(enumerate(REASONS)), return_dtype=pl.String))
        .sort("form")
    )
