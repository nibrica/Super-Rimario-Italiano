"""FORMS from English-Wiktionary Italian entries (kaikki_en, OVERHAUL-PLAN §1, §4, §5.1).

One row per (form, lemma, pos, feats, evidence): the headword of every entry
(lemma rows, or form-of rows with the target as lemma) and every inflected
form of its conjugation/inflection table. Stress comes from stress-marked
table/head forms ("table"), hyphenation ("hyphenation") and IPA ("ipa"), one
row per evidence type so vote.py sees them separately. Stress-marked
spellings (table cells, headwords such as ``abéto``, lemmas such as
``destinàre``) become real spellings (§4).
"""

import functools
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import orjson
import polars as pl

from .. import schema, text
from .kaikki_common import (
    TAG_MAP, Rows, Stress, agreement, clean, entry_tags, feats_for, finish,
    hyphenation_stress, hyphenations, inherit_misspelling, ipa_candidates, ipa_list, lemma_feats, log_stats,
    map_pos, map_tags, merge_stress, parallel_map, respell, sense_tag_sets, stress_marked,
    verb_feats,
)

log = logging.getLogger(__name__)

SOURCE = "kaikki_en"
FILE = "kaikki.org-dictionary-Italian.jsonl.gz"

# Form tags describing an inflection; a form with any other tag (alternative,
# diminutive, superlative, table metadata...) is not emitted.
INFLECTION_TAGS = frozenset({
    "plural", "singular", "feminine", "masculine",
    "first-person", "second-person", "third-person",
    "indicative", "subjunctive", "conditional", "imperative",
    "present", "imperfect", "past", "historic", "past-remote", "future",
    "participle", "gerund", "infinitive",
})
# Register-like form tags that may accompany an inflection.
FORM_REGISTER_TAGS = frozenset(TAG_MAP) | {"traditional", "Traditional", "dated", "Tuscany"}
VERB_TAGS = INFLECTION_TAGS - {"plural", "singular", "feminine", "masculine"}

_CLITICS = re.compile(r"\b(me|te|se|ce|ve|glie|mi|ti|si|ci|vi|gli|lo|la|li|le|ne)\b")
_COMPOUND = re.compile(
    r"compound of (?:the (?P<kind>infinitive|gerund) (?P<inf>\w+)"
    r"|\S+?,? the (?P<desc>[\w\s-]+?) of (?P<lemma>\w+),?) with (?P<rest>.+)$", re.I)
_QUALIFIER = re.compile(r"<[lq]:[^>]*>")          # f,m<l:archaic>: a label of one gender only
FLAG_TAGS = frozenset(schema.VULGAR_TAGS + schema.ARCHAIC_TAGS)


def compound_reading(gloss: str) -> tuple[str, str] | None:
    """(lemma, feats) of an enclitic compound gloss (``dimmelo`` -> dire, impr+pres+2+s+me+lo)."""
    m = _COMPOUND.match(gloss)
    if not m:
        return None
    clitics = _CLITICS.findall(re.sub(r"\(.*?\)", "", m["rest"]))
    if not clitics:
        return None
    if m["kind"]:
        lemma, host = m["inf"], verb_feats({m["kind"]})
    else:
        lemma, host = m["lemma"], verb_feats(set(m["desc"].split()))
    if host is None:
        return None
    return text.norm(lemma), "+".join([host, *clitics])


def form_of_lemmas(word: str) -> list[str]:
    """Clean lemmas of a ``form_of`` target: ``avere and`` -> avere, ``uovo m`` -> uovo,
    ``fondare and fondere`` -> both, ``(archaic) redurre`` -> redurre."""
    word = re.sub(r"^\(.*?\)\s*", "", word)
    heads = [part.split()[0] for part in word.split(" and ") if part.split()]
    return [text.norm(h) for h in heads if clean(h)]


def _gender(entry: dict) -> str | None:
    gs = set()
    for s in entry.get("senses", ()):
        gs |= {"m" if t == "masculine" else "f" for t in s.get("tags", ()) if t in ("masculine", "feminine")}
    for h in entry.get("head_templates", ()):
        if h.get("name") == "it-noun":
            g = str(h.get("args", {}).get("1", ""))
            gs |= {c for c in g[:2] if c in "mf"}
    return gs.pop() if len(gs) == 1 else None


def _head_tags(entry: dict) -> list[str]:
    out = []
    for h in entry.get("head_templates", ()):
        args = h.get("args", {})
        if h.get("name") in ("tlb", "lb"):
            out.extend(str(v) for k, v in args.items() if k != "1")
        elif h.get("name") == "head" and str(args.get("2", "")).startswith("misspelling"):
            out.append("misspelling")
    return out


def _tags(entry: dict, pos: str) -> set[str]:
    """Usage tags of an entry (``entry_tags``).

    wiktextract also copies a label onto every sense when it qualifies one
    gender in the head (stazione ``f,m<l:archaic>``) or belongs to another
    entry of the page (the archaic adjective *gente* onto the noun, the vulgar
    noun *spagnola* onto the adjective form). So a flag tag (schema.VULGAR_TAGS,
    schema.ARCHAIC_TAGS) counts only if the sense's own text or the entry's
    head line names it, or the sense opens with a label, or is an alternative
    form.
    """
    head = _QUALIFIER.sub("", " ".join(
        str(v) for h in entry.get("head_templates", ()) for v in h.get("args", {}).values()).lower())

    def keep(sense: dict, tag: str) -> bool:
        if TAG_MAP.get(tag) not in FLAG_TAGS:
            return True
        own = " ".join([*sense.get("raw_glosses", ()), *sense.get("glosses", ())]).lower()
        return tag in own or tag in head or own.startswith("(") or "alt-of" in sense.get("tags", ())

    tags = entry_tags(sense_tag_sets(entry.get("senses", ()), keep), _head_tags(entry))
    return tags | ({"proper"} if pos == "name" else set())


def _readings(entry: dict, form: str, pos: str, gender: str | None) -> tuple[set[tuple[str, str | None]], bool]:
    """(lemma, feats) readings of the headword and whether any sense is a lemma sense."""
    out: set[tuple[str, str | None]] = set()
    has_lemma = False
    for s in entry.get("senses") or [{}]:
        tags = set(s.get("tags", ()))
        if "compound-of" in tags and (r := compound_reading((s.get("glosses") or [""])[0])):
            out.add(r)
        elif "form-of" in tags and s.get("form_of"):
            feats = feats_for(pos, tags, gender)
            out |= {(lemma, feats) for lemma in form_of_lemmas(s["form_of"][0]["word"])}
        elif "alt-of" in tags or "misspelling" in tags:
            out.add((form, None))                         # own lexeme, not an infinitive
        else:
            has_lemma = True
    if has_lemma or not out:
        out.add((form, lemma_feats(form, pos)))
    return out, has_lemma or (form, None) in out


def _stress_evidence(entry: dict, form: str, stats: Counter) -> list[tuple[Stress, str]]:
    """Stress readings of the headword, one list item per (stress, evidence)."""
    table = [s for f in entry.get("forms", ()) if "canonical" in f.get("tags", ())
             and (s := hyphenation_stress(form, f["form"]))]
    hyph = [s for h, _ in hyphenations(entry) if (s := hyphenation_stress(form, h))]
    check = {i for i, _ in table + hyph}
    ipa = [s for s in ipa_candidates(form, ipa_list(entry.get("sounds", ())), check, stats) if s]
    return [(s, ev) for ev, cands in (("table", table), ("hyphenation", hyph), ("ipa", ipa))
            for s in merge_stress(cands)]


def _en_worker(chunk: bytes) -> dict:
    rows = Rows()
    pending: list[tuple] = []
    known: set[str] = set()
    stats: Counter = Counter()
    for line in chunk.splitlines():
        entry = orjson.loads(line)
        if entry.get("lang_code") != "it":
            continue
        senses = entry.get("senses", ())
        form = text.norm(entry.get("word", ""))
        if not all("misspelling" in s.get("tags", ()) for s in senses):
            known.add(form)
        pos = map_pos(entry.get("pos"))
        if pos is None or not clean(form):
            continue
        tags = _tags(entry, pos)
        evidence = _stress_evidence(entry, form, stats)
        agreement(stats, evidence)
        gender = _gender(entry)
        readings, has_lemma = _readings(entry, form, pos, gender)
        for lemma, feats in sorted(readings, key=str):
            for stress, ev in evidence or [(None, "none")]:
                rows.add(form, lemma, pos, feats, stress, ev, tags)
        # Inflected forms: lemma is the entry word, or the target of a pure form-of entry.
        lemmas = {lm for lm, _ in readings}
        form_lemma = form if has_lemma or len(lemmas) != 1 else next(iter(lemmas))
        inherit = tags - {"abbreviation"}              # itagliano's itagliani is misspelt too
        participle = pos == "verb" and any(f and f.startswith("part+past") for _, f in readings)
        for f in entry.get("forms", ()):
            ftags = set(f.get("tags", ()))
            infl = ftags - FORM_REGISTER_TAGS
            if not infl or not infl <= INFLECTION_TAGS:
                continue
            marked = text.norm(f.get("form", ""))
            if not clean(marked):
                continue
            if participle and not ftags & VERB_TAGS:
                ftags |= {"participle", "past"}               # capito: capita, capiti...
            feats = feats_for(pos, ftags, gender)
            ftag_set = inherit | map_tags(ftags) | ({"archaic"} if ftags & {"traditional", "Traditional"} else set())
            if text.accent_positions(marked):
                links = f.get("links") or []
                link = text.norm(links[0][1].split("#")[0]) if links and len(links[0]) > 1 else None
                pending.append((marked, link, form_lemma, pos, feats, sorted(ftag_set)))
            else:
                rows.add(marked, form_lemma, pos, feats, None, "none", ftag_set)
    return {"rows": rows.frame(), "pending": pending, "known": known, "stats": stats}


def _resolve(marked: str, link: str | None, is_known: Callable[[str], bool]) -> tuple | None:
    """Real spelling + stress of a stress-marked table form (§4).

    The table's link target is the real spelling when present (unless it is
    stress-marked itself: ``alchìmie``), except for monosyllables, whose links
    drop the accent mechanically (``dà`` -> ``da``, a different word): those
    use the known spellings. Otherwise a polysyllable stressed on its last
    vowel keeps the accent (``traiettò`` must not become the known
    ``traietto``; but ``quà``, ``quì`` are no polysyllables); anything else
    goes through ``text.resolve_spelling`` (known spellings first: ``dò``,
    ``fà`` -> ``fa``).
    """
    s = text.marked_stress(marked)
    if s is None:
        return None
    vowels = text.vowel_positions(marked)
    if link in (marked, text.strip_accents(marked)) and len(vowels) > 1 and not stress_marked(link):
        return link, *s
    if s[0] == vowels[-1] and len(vowels) > 1 and not (marked.startswith("qu") and len(vowels) == 2):
        return marked, *s
    return text.resolve_spelling(marked, is_known) or text.resolve_spelling(marked)


def resolve_pending(pending: list[tuple], known: set[str]) -> tuple[pl.DataFrame, int]:
    """Rows for stress-marked table forms, resolved to real spellings."""
    rows = Rows()
    plain = {w for w in known if not stress_marked(w)}
    resolve = functools.cache(lambda marked, link: _resolve(marked, link, plain.__contains__))
    dropped = 0
    for marked, link, lemma, pos, feats, tags in pending:
        r = resolve(marked, link)
        if r is None or not clean(r[0]):
            dropped += 1
            continue
        rows.add(r[0], lemma, pos, feats, (r[1], r[2]), "table", tags)
    return rows.frame(), dropped


def extract(raw_dir: Path) -> pl.DataFrame:
    """FORMS table from the kaikki_en raw directory (``data/raw/kaikki_en``)."""
    t0 = time.perf_counter()
    results = parallel_map(raw_dir / FILE, _en_worker)
    rows = pl.concat([r["rows"] for r in results], how="vertical_relaxed")
    pending = [p for r in results for p in r["pending"]]
    known = set().union(*(r["known"] for r in results)) | {p[1] for p in pending if p[1]}
    stats = sum((r["stats"] for r in results), Counter())
    table, dropped = resolve_pending(pending, known)
    log.info("%s: %d stress-marked table forms, %d unresolved", SOURCE, len(pending), dropped)
    df, respelt = respell(pl.concat([rows, table], how="vertical_relaxed"), known)
    log.info("%s: %d stress-marked headword/lemma spellings respelt (§4)", SOURCE, respelt)
    df = finish(inherit_misspelling(df), SOURCE)
    log_stats(SOURCE, stats, df, t0)
    return df
