"""FORMS from Italian-Wiktionary entries (kaikki_it).

it.wiktionary has one {{-sill-}} and one pronunciation per page, and kaikki
copies them onto every POS entry of the page. A page such as ``viola`` or
``capitano`` also holds a verb-form section whose stress differs (*vìola*,
*càpitano*), so page-level stress is not given to form-of entries of a page
that also has a non-form-of entry: those rows get no stress and paradigm/vote
decide. A hyphenation or IPA labelled with a POS (``"sense": "voce verbale"``)
goes to the entries of that POS only. Conjugation tables are not
stress-marked here, so their forms carry only orthographic stress.

A sense is form-of when it links its lemma or its gloss names it
(``terza persona singolare … di cresimare``, ``superlativo assoluto di
tanto``). Editors write the hyphenation accent grave by default, so it gives
the stress but no vowel quality (IPA does).
"""

import logging
import re
import time
from collections import Counter
from pathlib import Path

import orjson
import polars as pl

from .. import text
from .kaikki_common import (
    Rows, Stress, agreement, clean, entry_tags, feats_for, finish, hyphenation_stress,
    hyphenations, inherit_misspelling, ipa_candidates, ipa_list, lemma_feats, log_stats, map_pos, merge_stress,
    parallel_map, respell, sense_tag_sets,
)

log = logging.getLogger(__name__)

SOURCE = "kaikki_it"
FILE = "it-extract.jsonl.gz"
LANG_NEEDLE = b'"it"'                # cheap pre-filter before parsing a line

# Forms that are compound tenses, auxiliaries or other degrees (other lemmas).
SKIP_FORM_TAGS = frozenset({"auxiliary", "perfect", "pluperfect", "positive", "superlative",
                            "absolute", "comparative"})

# Words of a hyphenation/IPA "sense" label -> POS it applies to.
LABEL_POS = {
    "avverbi": "adv", "aggettiv": "adj", "sostantiv": "noun", "nome": "noun",
    "verb": "verb", "preposizion": "prep", "congiunzion": "conj",
    "interiezion": "intj", "pronom": "pron", "articol": "article",
}

# Gloss keywords of form-of senses ("terza persona singolare dell'indicativo presente di violare").
_GLOSS_PERSON = {"prima": "first-person", "seconda": "second-person", "terza": "third-person",
                 "1ª": "first-person", "2ª": "second-person", "3ª": "third-person"}
_GLOSS_TAGS = {
    "singolare": "singular", "plurale": "plural", "plurali": "plural", "plural": "plural",
    "maschile": "masculine", "femminile": "feminine", "feminine": "feminine",
    "indicativo": "indicative", "congiuntivo": "subjunctive", "condizionale": "conditional",
    "imperativo": "imperative", "participio": "participle", "gerundio": "gerund",
    "infinito": "infinitive", "presente": "present", "imperfetto": "imperfect",
    "futuro": "future", "remoto": "historic", "superlativo": "superlative",
}
_WORDS = re.compile(r"[\wª]+")
# A form-of gloss without a link: "<person/participle/plural/...> ... di <lemma>".
_FORM_OF_GLOSS = re.compile(
    r"(?:(?:prima|seconda|terza|[123]ª) persona|participio|gerundio|infinito|plurale|femminile"
    r"|maschile|superlativo)\b.*\bdi (?P<lemma>\w+)$")

# Pronoun raw_tags of the conjugation appendix -> person/number.
_PRONOUN = {"io": ("first-person", "singular"), "tu": ("second-person", "singular"),
            "lui/lei": ("third-person", "singular"), "noi": ("first-person", "plural"),
            "voi": ("second-person", "plural"), "essi/esse": ("third-person", "plural")}


def gloss_tags(gloss: str) -> set[str]:
    """Kaikki-style tags from an Italian form-of gloss."""
    words = _WORDS.findall(gloss.lower())
    return {_GLOSS_TAGS[w] for w in words if w in _GLOSS_TAGS} | \
        {_GLOSS_PERSON[w] for w in words if w in _GLOSS_PERSON}


def sense_lemma(sense: dict) -> str | None:
    """Lemma of a form-of sense: its link, else the "… di X" of its gloss; None for other senses.

    A link to a grammar word ("presente", "congiuntivo") is a parsing error.
    """
    link = text.norm(sense["form_of"][0]["word"]) if sense.get("form_of") else ""
    if clean(link) and link not in _GLOSS_TAGS and link not in _GLOSS_PERSON:
        return link
    m = _FORM_OF_GLOSS.match((sense.get("glosses") or [""])[0].strip().rstrip(".;").lower())
    return m["lemma"] if m and clean(m["lemma"]) else None


def conj_tags(form: dict) -> set[str]:
    """Tags of a conjugation-appendix form; the mood is implied by the table layout.

    Indicative rows carry person tags, subjunctive rows a "che io" pronoun,
    conditional rows only a tense and a bare pronoun.
    """
    own = set(form.get("tags", ()))
    if own & {"gerund", "participle", "infinitive", "auxiliary"}:
        return own
    raw = " ".join(form.get("raw_tags", ())).strip()
    tags = own | set(_PRONOUN.get(raw.replace("che ", "").split(" ")[0], ()))
    if "past-remote" in tags:
        tags.add("historic")
    if "imperative" in tags:
        return tags
    if raw.startswith("che "):
        return tags | {"subjunctive"}
    return tags | ({"indicative"} if own & {"first-person", "second-person", "third-person"} else {"conditional"})


def label_pos(label: str | None) -> set[str]:
    """POS named by a hyphenation/IPA label ("aggettivo ed avverbio" -> adj, adv)."""
    words = _WORDS.findall((label or "").lower())
    return {pos for key, pos in LABEL_POS.items() if any(w.startswith(key) for w in words)}


def _candidates(entry: dict, form: str, stats: Counter) -> list[tuple[Stress, str, set[str]]]:
    """(stress, evidence, POS of its label) for each hyphenation/IPA of the page."""
    out = [((s[0], None), "hyphenation", label_pos(label)) for h, label in hyphenations(entry)
           if (s := hyphenation_stress(form, h))]
    check = {s[0] for s, _, _ in out}
    for snd in entry.get("sounds", ()):
        for s in ipa_candidates(form, ipa_list([snd]), check, stats):
            if s:
                out.append((s, "ipa", label_pos(snd.get("sense"))))
    return out


def _it_worker(chunk: bytes) -> dict:
    rows = Rows(extra=("page", "generic_formof"))
    pages: dict[str, bool] = {}          # page title -> has a non-form-of entry
    known: set[str] = set()
    stats: Counter = Counter()
    for line in chunk.splitlines():
        if LANG_NEEDLE not in line:
            continue
        entry = orjson.loads(line)
        if entry.get("lang_code") != "it":
            continue
        page = entry.get("word", "")
        senses = entry.get("senses", ())
        etags = set(entry.get("tags", ()))
        lemma_of = [sense_lemma(s) for s in senses]
        form_of = "form-of" in etags or (bool(senses) and all(lemma_of))
        pages[page] = pages.get(page, False) or not form_of
        form = text.norm(page)
        known.add(form)
        pos = map_pos(entry.get("pos"))
        if pos is None or not clean(form):
            continue
        tags = entry_tags(sense_tag_sets(senses), etags)
        tags |= {"proper"} if pos == "name" else set()
        tags |= {"abbreviation"} if entry.get("pos") == "abbrev" else set()

        # Readings of the headword.
        readings: set[tuple[str, str | None]] = set()
        for s, lemma in zip(senses, lemma_of):
            if lemma:
                readings.add((lemma, feats_for(pos, gloss_tags(" ".join(s.get("glosses", ()))) | etags)))
        if not form_of or not readings:
            readings.add((form, None if form_of else lemma_feats(form, pos)))
        lemmas = {lm for lm, _ in readings}

        # Stress: POS-labelled candidates win; generic ones are page-level.
        cands = _candidates(entry, form, stats)
        labelled = [(s, ev) for s, ev, lp in cands if pos in lp]
        generic = [(s, ev) for s, ev, lp in cands if not lp]
        chosen, is_generic = (labelled, False) if labelled else (generic, True)
        evidence = [(s, ev) for ev in ("hyphenation", "ipa")
                    for s in merge_stress(s for s, e in chosen if e == ev)]
        if len({s[0] for s, _ in evidence}) > 1 and (is_generic or form_of):
            evidence = []                # several stresses, no way to tell which is this entry's
        if form_of and is_generic and len(lemmas) > 1:
            evidence = []                # capito: capire (capìto) and capitare (càpito)
        agreement(stats, evidence)
        generic_formof = form_of and is_generic
        for lemma, feats in sorted(readings, key=str):
            for stress, ev in evidence or [(None, "none")]:
                rows.add(form, lemma, pos, feats, stress, ev, tags,
                         page=page, generic_formof=generic_formof and stress is not None)

        # Inflected forms (unmarked in it.wiktionary tables).
        form_lemma = form if not form_of or len(lemmas) != 1 else next(iter(lemmas))
        superlative = any(f and f.startswith("sup+") for _, f in readings)   # tantissimo: tantissimi
        inherit = tags - {"abbreviation"}
        genders = etags & {"masculine", "feminine"}
        gender = genders.pop()[0] if len(genders) == 1 else None
        for f in entry.get("forms", ()):
            ftags = conj_tags(f) if str(f.get("source", "")).startswith("Appendice") \
                else set(f.get("tags", ()))
            if not ftags or ftags & SKIP_FORM_TAGS:
                continue
            fform = text.norm(f.get("form", ""))
            if not clean(fform):
                continue
            feats = feats_for(pos, ftags | ({"superlative"} if superlative else set()), gender)
            rows.add(fform, form_lemma, pos, feats, None, "none", inherit,
                     page=page, generic_formof=False)
    return {"rows": rows.frame(), "pages": pages, "known": known, "stats": stats}


def extract(raw_dir: Path) -> pl.DataFrame:
    """FORMS table from the kaikki_it raw directory (``data/raw/kaikki_it``)."""
    t0 = time.perf_counter()
    results = parallel_map(raw_dir / FILE, _it_worker)
    rows = pl.concat([r["rows"] for r in results], how="vertical_relaxed")
    stats = sum((r["stats"] for r in results), Counter())
    lemma_pages = sorted({p for r in results for p, has in r["pages"].items() if has})
    # Page-level stress is not evidence for form-of entries of a page with a lemma entry.
    drop = pl.col("generic_formof") & pl.col("page").is_in(lemma_pages)
    log.info("%s: page-level stress withheld from %d form-of rows", SOURCE,
             rows.filter(drop).height)
    rows = rows.with_columns(
        pl.when(drop).then(None).otherwise(pl.col("stress_idx")).alias("stress_idx"),
        pl.when(drop).then(None).otherwise(pl.col("quality")).alias("quality"),
        pl.when(drop).then(pl.lit("none")).otherwise(pl.col("evidence")).alias("evidence"),
    )
    rows, respelt = respell(rows, set().union(*(r["known"] for r in results)))
    log.info("%s: %d stress-marked headword/lemma spellings respelt", SOURCE, respelt)
    df = finish(inherit_misspelling(rows), SOURCE)
    log_stats(SOURCE, stats, df, t0)
    return df
