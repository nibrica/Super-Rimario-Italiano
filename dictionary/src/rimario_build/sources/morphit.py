"""Morph-it! lexicon: ~505k inflected forms with lemma and features (FORMS).

Stress comes only from the spelling itself: a final accent (evidence "ortho")
or a dictionary stress mark on a word that also exists unmarked (evidence
"table"); see paradigm.py for the rules that turn Morph-it's paradigms into
stress readings.
"""

import tarfile
from pathlib import Path

import polars as pl

from .. import config, schema, text

SOURCE = "morphit"
_GRAVE = str.maketrans("áéíóú", "àèìòù")   # accent glyph -> grave, to find glyph twins


def _read_lines(raw_dir: Path) -> list[list[str]]:
    """The lexicon's ``form, lemma, tag`` triples (malformed lines repaired or skipped)."""
    path = raw_dir / config.MORPHIT_ARCHIVE
    with tarfile.open(path, "r:gz") as tar:
        f = tar.extractfile(config.MORPHIT_MEMBER)
        if f is None:
            raise FileNotFoundError(f"{path}: no member {config.MORPHIT_MEMBER}")
        data = f.read().decode("iso-8859-1")
    rows = []
    for line in data.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            parts = line.split()             # one line uses spaces ("seppur seppure CON")
        if len(parts) == 3:
            rows.append(parts)
    return rows


def _accent_apostrophe(word: str) -> str:
    """``citta'`` -> ``città``: a final apostrophe written for a grave accent."""
    if len(word) > 2 and word[-1] == "'" and word[-2] in "aeiou" and len(text.vowel_positions(word)) > 1:
        return word[:-2] + text.MARK[(word[-2], None)]
    return word


def _acute_ending(word: str) -> str:
    """``perchè`` -> ``perché``, ``ventitrè`` -> ``ventitré``."""
    for grave, acute in config.MORPHIT_ACUTE_ENDINGS:
        if word.endswith(grave) and len(word) > len(grave):
            return word[: -len(grave)] + acute
    return word


def _fix_spelling(form: str, lemma: str, verb: bool) -> tuple[str, str]:
    """Morph-it spelling quirks of a (form, lemma) pair: ``citta'`` -> ``città``, ``perchè`` -> ``perché``.

    A final apostrophe stands for an accent when the lemma is the form itself or
    its accented spelling (``attivita'``, ``citta'``/città), or on a verb, where
    it drops an unstressed -i after the stress (``rifa'`` = rifai, so rifà). On
    other words it is an apocope: ``dotto'`` (dottore) is not dottò.
    """
    accented = _accent_apostrophe(form)
    if verb or lemma == form or text.strip_accents(lemma) == text.strip_accents(accented):
        form, lemma = accented, _accent_apostrophe(lemma)
    return _acute_ending(form), _acute_ending(lemma)


def _stress_mark(word: str) -> tuple[str, int, str | None] | None:
    """A non-final accent that may be a stress mark (àncora, princìpi): (plain spelling, index, quality).

    French accents are not stress marks (``élite`` is elìte).
    """
    stress = text.marked_stress(word)
    if stress is None or stress[0] == len(word) - 1 or word in config.MORPHIT_FOREIGN_ACCENTS:
        return None
    return text.strip_accents(word), *stress


def _glyph_misspellings(entries: list[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    """Entries spelled with the wrong accent glyph of a twin with the same lemma and tag (piú beside più).

    The standard twin is the grave one (più, è, cioè), except for
    config.MORPHIT_ACUTE_STANDARD (sé, viceré): so piú, é, sè, cioé, mó are misspellings.
    """
    groups: dict[tuple[str, str, str], set[tuple[str, str, str]]] = {}
    for form, lemma, tag in entries:
        groups.setdefault((form.translate(_GRAVE), lemma.translate(_GRAVE), tag), set()).add((form, lemma, tag))
    bad = set()
    for (grave, _, _), twins in groups.items():
        if len({f for f, _, _ in twins}) > 1:
            standard = next((f for f, _, _ in twins if f in config.MORPHIT_ACUTE_STANDARD), grave)
            bad |= {t for t in twins if t[0] != standard}
    return bad


def _pos(cat: str) -> str | None:
    """Morph-it category (the part of the tag before ':') -> schema.POS_VALUES."""
    if cat in config.MORPHIT_DROP_CATEGORIES:
        return None
    if cat in config.MORPHIT_POS:
        return config.MORPHIT_POS[cat]
    for prefix, pos in config.MORPHIT_POS_PREFIXES:
        if cat.startswith(prefix):
            return pos
    return "other"


def _feats(tag: str) -> str | None:
    """Morph-it feature string, normalized as documented in schema.py."""
    cat, _, feats = tag.partition(":")
    if cat.startswith("NOUN-"):
        return f"{cat[-1].lower()}+{feats}" if feats else None
    if feats:
        parts = feats.split("+")
        if cat in config.MORPHIT_VERB_CATEGORIES and parts[-1] in config.MORPHIT_CLITIC_COMPOUNDS:
            parts[-1:] = config.MORPHIT_CLITIC_COMPOUNDS[parts[-1]]
        return "+".join(parts)
    # PRO-PERS-CLI-3-F-S -> "3+f+s"
    tail = [p.lower() for p in cat.split("-")[1:] if p in ("1", "2", "3", "M", "F", "S", "P")]
    return "+".join(tail) or None


def extract(raw_dir: Path) -> pl.DataFrame:
    """FORMS rows for every Morph-it word (punctuation and emoticons dropped).

    ``raw_dir`` is the source's own directory (data/raw/morphit).
    """
    entries = []
    for form, lemma, tag in _read_lines(raw_dir):
        cat = tag.split(":", 1)[0]
        if _pos(cat) is None:
            continue
        form, lemma = _fix_spelling(text.norm(form), text.norm(lemma), cat in config.MORPHIT_VERB_CATEGORIES)
        lemma = config.MORPHIT_LEMMA_FIXES.get(form, lemma)
        if cat in config.MORPHIT_VERB_CATEGORIES and tag.endswith("ind+past+3+s") and form.endswith("è"):
            form = form[:-1] + "é"           # credè -> credé (the -ere past is written with é)
        entries.append((form, lemma, tag))

    # A stress-marked spelling (ancóra, àncora, èra, princìpi) becomes its plain
    # twin when that is a Morph-it word too, or when its lemma was one (àncore of
    # àncora); otherwise it is kept, unstressed. The mark is a lexicographer's
    # stress annotation, as reliable as a stress-marked table, hence evidence "table".
    known = {f for f, _, _ in entries} | {lemma for _, lemma, _ in entries}
    resolved = []
    for form, lemma, tag in entries:
        lemma_mark = _stress_mark(lemma)
        if lemma_mark and lemma_mark[0] in known:
            lemma = lemma_mark[0]
        else:
            lemma_mark = None
        mark = _stress_mark(form)
        if mark and (mark[0] in known or lemma_mark):
            resolved.append((mark[0], lemma, tag, mark[1:]))
        else:
            resolved.append((form, lemma, tag, None))
    glyph_bad = _glyph_misspellings([(f, lemma, tag) for f, lemma, tag, _ in resolved])

    out = []
    for form, lemma, tag, mark in resolved:
        cat = tag.split(":", 1)[0]
        tags = []
        if cat == "NPR":
            tags.append("proper")
        if cat == "ABL":
            tags.append("abbreviation")
        if form in config.MORPHIT_MISSPELLINGS or lemma in config.MORPHIT_MISSPELLINGS or (
            (form, lemma, tag) in glyph_bad
        ) or (
            form != lemma and text.accent_positions(lemma)
            and text.strip_accents(form) == text.strip_accents(lemma)
        ):
            tags.append("misspelling")       # perche, perchè (lemma perché); piú (più)
        stress = mark or text.orthographic_stress(form)
        evidence = "table" if mark else "ortho" if stress else "none"
        out.append((
            form, lemma, _pos(cat), _feats(tag), stress[0] if stress else None,
            stress[1] if stress else None, evidence, sorted(tags), SOURCE,
        ))
    # One row per reading: a stressed row (dei < dèi) replaces its unstressed twin.
    stressed = {r[:4] for r in out if r[4] is not None}
    out = [r for r in out if r[4] is not None or r[:4] not in stressed]
    df = pl.DataFrame(out, schema=schema.FORMS, orient="row")
    # dèmone/démone, pièce/piéce: one reading whose two marks disagree on the quality.
    reading = ["form", "lemma", "pos", "feats", "stress_idx"]
    df = df.with_columns(quality=pl.when(pl.col("quality").n_unique().over(reading) > 1)
                         .then(None).otherwise(pl.col("quality"))).unique()
    return df.sort(["form", "lemma", "pos", "feats", "evidence", "stress_idx", "quality",
                    pl.col("tags").list.join(","), "source"], nulls_last=True)
