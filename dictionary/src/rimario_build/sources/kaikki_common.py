"""Helpers shared by the kaikki_en and kaikki_it extractors.

Reading the JSONL in parallel chunks, POS/tag mapping, feature strings,
hyphenation and IPA stress, stress-marked spellings, and the FORMS frame.
"""

import gzip
import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import polars as pl

from .. import config, schema, text

log = logging.getLogger(__name__)

# --- Mapping tables ----------------------------------------------------------

POS_MAP = {
    "noun": "noun", "verb": "verb", "adj": "adj", "adv": "adv", "name": "name",
    "pron": "pron", "det": "det", "article": "article", "prep": "prep",
    "conj": "conj", "intj": "intj", "num": "num", "particle": "particle",
    "suffix": "affix", "prefix": "affix", "affix": "affix", "infix": "affix",
    "interfix": "affix", "phrase": "phrase", "prep_phrase": "phrase",
    "adv_phrase": "phrase", "proverb": "phrase", "contraction": "other",
    "abbrev": "other",
}
SKIP_POS = frozenset({"character", "symbol", "punct", "romanization"})

# Kaikki tag -> schema.TAG_VALUES ("proper" is set from the POS).
TAG_MAP = {
    "vulgar": "vulgar", "offensive": "offensive", "slur": "offensive",
    "derogatory": "derogatory", "pejorative": "derogatory",
    "archaic": "archaic", "poetic": "poetic", "literary": "literary",
    "obsolete": "obsolete", "abbreviation": "abbreviation",
    "initialism": "abbreviation", "acronym": "abbreviation",
    "misspelling": "misspelling", "regional": "regional",
    "dialectal": "dialectal", "rare": "rare", "uncommon": "rare",
}
# Whole words although wiktextract also tags them "abbreviation": apocopes,
# clippings (auto, bici), contractions (degli) and ellipses (quebracho).
NOT_ABBREVIATION_TAGS = frozenset({"apocopic", "clipping", "contraction", "ellipsis"})
# Sense tags that make a sense empty (left out of the sense rules).
EMPTY_SENSE_TAGS = frozenset({"no-gloss", "empty-gloss"})

PERSON = {"first-person": "1", "second-person": "2", "third-person": "3"}


def clean(form: str) -> bool:
    """A single word: no spaces, apostrophes, hyphens, dots or digits."""
    return form.isalpha() and "ʼ" not in form


def map_pos(pos: str | None) -> str | None:
    """Kaikki POS -> schema.POS_VALUES; None for entries to skip."""
    if pos is None or pos in SKIP_POS:
        return None
    return POS_MAP.get(pos, "other")


def map_tags(tags: Iterable[str]) -> set[str]:
    """Kaikki tags -> schema.TAG_VALUES; a "mildly" vulgar sense (cristo) is not vulgar."""
    tags = set(tags)
    out = {TAG_MAP[t] for t in tags if t in TAG_MAP}
    if tags & NOT_ABBREVIATION_TAGS:
        out.discard("abbreviation")
    if tags & config.KAIKKI_MILD_TAGS:
        out -= set(schema.VULGAR_TAGS)
    return out


def entry_tags(sense_tags: list[set[str]], extra: Iterable[str] = ()) -> set[str]:
    """Tags of an entry from its (non-empty) senses' mapped tags, plus entry/head-level ones.

    A usage tag must be on every sense, except the vulgar family
    (schema.VULGAR_TAGS): those mark the entry when at least
    config.KAIKKI_VULGAR_SHARE of its senses are vulgar or offensive (troia:
    1 of 2; not nano, 1 of 3). "derogatory" alone flags nothing (napoli,
    pizzo, nessuno are labelled so): it is kept only on a vulgar or offensive
    entry.
    """
    out = map_tags(extra)
    if not sense_tags:
        return out
    out |= set.intersection(*sense_tags) - set(schema.VULGAR_TAGS)
    strong = sum(bool(s & {"vulgar", "offensive"}) for s in sense_tags)
    if strong and strong >= config.KAIKKI_VULGAR_SHARE * len(sense_tags):
        out |= set().union(*sense_tags) & set(schema.VULGAR_TAGS)
    if not out & {"vulgar", "offensive"}:
        out.discard("derogatory")
    return out


def sense_tag_sets(senses: Iterable[dict], keep: Callable[[dict, str], bool] | None = None) -> list[set[str]]:
    """Mapped tags of each non-empty sense; ``keep(sense, kaikki_tag)`` filters the raw tags."""
    out = []
    for s in senses:
        tags = s.get("tags", ())
        if EMPTY_SENSE_TAGS & set(tags):
            continue
        out.append(map_tags(t for t in tags if keep is None or keep(s, t)))
    return out


def verb_feats(tags: set[str]) -> str | None:
    """Morph-it feature string of a verb form from Kaikki tags (schema.py)."""
    if "infinitive" in tags:
        return "inf+pres"
    if "gerund" in tags:
        return "ger+pres"
    num = "p" if "plural" in tags else "s"
    if "participle" in tags:
        if "present" not in tags:                         # "feminine singular of preavvertito"
            return f"part+past+{num}+{'f' if 'feminine' in tags else 'm'}"
        gen = "+f" if "feminine" in tags else "+m" if "masculine" in tags else ""
        return f"part+pres+{num}{gen}"
    if "conditional" in tags:
        mood, tense = "cond", "pres"
    elif "imperative" in tags:
        mood, tense = "impr", "pres"
    else:
        mood = "sub" if "subjunctive" in tags else "ind"
        if "historic" in tags or "past-remote" in tags:
            tense = "past"
        elif "imperfect" in tags:
            tense = "impf"
        elif "future" in tags:
            tense = "fut"
        elif "present" in tags:
            tense = "pres"
        else:
            return None
    person = next((PERSON[t] for t in sorted(tags) if t in PERSON), None)
    if person is None or not ({"singular", "plural"} & tags):
        return f"{mood}+{tense}"
    return f"{mood}+{tense}+{person}+{num}"


def nominal_feats(pos: str, tags: set[str], gender: str | None = None) -> str | None:
    """Morph-it feature string of a noun/adjective form ("f+p", "pos+m+s")."""
    g = "f" if "feminine" in tags and "masculine" not in tags else \
        "m" if "masculine" in tags and "feminine" not in tags else gender
    n = "p" if "plural" in tags else "s"
    base = f"{g}+{n}" if g else n
    if pos == "adj":
        return ("sup+" if "superlative" in tags else "pos+") + base
    if pos == "noun":
        return base
    return None


def feats_for(pos: str, tags: set[str], gender: str | None = None) -> str | None:
    if pos == "verb":
        return verb_feats(tags)
    return nominal_feats(pos, tags, gender)


# An infinitive, possibly with clitics (andare, porre, trarsi, andarsene, farcela).
_INFINITIVE = re.compile(r"r(?:e|si)?(?:mi|ti|ci|vi|si|gli|ne|l[aeio]|(?:me|te|ce|ve|se|glie)(?:l[aeio]|ne))?$")


def lemma_feats(form: str, pos: str) -> str | None:
    """Feats of a headword read as its own lemma: ``inf+pres`` for an infinitive verb."""
    return "inf+pres" if pos == "verb" and _INFINITIVE.search(form) else None


# --- Stress from hyphenation and IPA -----------------------------------------

Stress = tuple[int, str | None]


def hyphenation_stress(form: str, marked: str) -> Stress | None:
    """Stress of ``form`` from a stress-marked hyphenation (``grà‧tis``, ``cà``+``sa``).

    The hyphenation must spell the same letters as ``form`` and carry exactly
    one accent; otherwise None. The accent that a stress-marked or foreign
    spelling already has (``é‧li‧te`` of *élite*) says nothing more: None.
    """
    m = text.norm(marked).replace("‧", "").replace("·", "").replace("-", "")
    if text.strip_accents(m) != text.strip_accents(form):
        return None
    s = text.marked_stress(m)
    own = text.marked_stress(form) if stress_marked(form) else None
    return None if s and own and s[0] == own[0] else s


def hyphenations(entry: dict) -> list[tuple[str, str | None]]:
    """(joined hyphenation, its "sense" label) of an entry, skipping qualified variants."""
    out = []
    for h in entry.get("hyphenations", ()):
        joined = "".join(h.get("parts") or [])
        if joined and "(" not in joined and ")" not in joined:
            out.append((joined, h.get("sense")))
    return out


IPA_VOWELS = {"a": "a", "e": "e", "ɛ": "e", "i": "i", "o": "o", "ɔ": "o", "u": "u"}
IPA_QUALITY = {"ɛ": "open", "e": "closed", "ɔ": "open", "o": "closed"}
IPA_GLIDES = {"j": "i", "w": "u"}
IPA_REJECT = frozenset("əøyæɑɐʊɪœɜʌɒɘɵɨʉäõĩ()|~‿*̞̃̆ ,")   # loanword vowels, options, phrases
IPA_STRESS = "ˈ'"
_IPA_OPTIONAL = re.compile(r"\([^()aeiouɛɔəøyæɑɐʊɪœɜʌɒɘɵɨʉ]*\)")   # optional consonants: du(t)ˈt͡sjo


def _ipa_tokens(ipa: str) -> list[list] | None:
    """[kind ("V"|"G"), symbol, stressed] for each vowel/glide of an IPA string."""
    s = _IPA_OPTIONAL.sub("", ipa.strip().strip("/[]"))
    toks: list[list] = []
    pending = False
    for ch in s:
        if ch in IPA_REJECT:
            return None
        if ch in IPA_STRESS:
            pending = True
        elif ch in IPA_VOWELS:
            toks.append(["V", ch, pending])
            pending = False
        elif ch in IPA_GLIDES:
            toks.append(["G", ch, False])
        elif ch == "̯" and toks and toks[-1][1] in "iu":      # i̯ u̯: non-syllabic
            toks[-1] = ["G", "j" if toks[-1][1] == "i" else "w", False]
    n_stressed = sum(t[2] for t in toks if t[0] == "V")
    vowels = [t for t in toks if t[0] == "V"]
    if n_stressed == 0 and len(vowels) == 1:
        vowels[0][2] = True
    elif n_stressed != 1:
        return None
    return toks


def ipa_stress(form: str, ipa: str, max_silent: int = 0) -> Stress | None:
    """Map the stressed vowel of an IPA transcription onto ``form``'s letters.

    Spelling vowels are aligned with IPA vowels and glides: ``i``/``u`` may be
    glides (j/w: ``piede``, ``quando``), ``i`` is silent between c/g/sc/gl/gn
    and a vowel (``ciao``, ``figlio``, ``sogniate``), and an IPA glide may come
    from a consonant letter (``yogurt``). Consonants are ignored, so geminates
    and ``ts``/``dz`` need no special case. Up to ``max_silent`` other spelling
    vowels may be silent (loanwords: ``performance`` /perˈfɔr.mans/); the
    alignments with the fewest silent vowels count. Returns None unless they
    all agree on one stressed letter.
    """
    toks = _ipa_tokens(ipa)
    if toks is None:
        return None
    letters = text.vowel_positions(form)
    found: dict[int, set[Stress]] = {}            # silent vowels -> stressed letters
    seen: set[tuple] = set()

    def walk(li: int, ti: int, hit: Stress | None, silent: int) -> None:
        if (li, ti, hit, silent) in seen:
            return
        seen.add((li, ti, hit, silent))
        if li == len(letters):
            if all(t[0] == "G" for t in toks[ti:]) and hit is not None:
                found.setdefault(silent, set()).add(hit)
            return
        i = letters[li]
        c = form[i]
        base = text.strip_accents(c)
        if ti < len(toks):
            kind, sym, stressed = toks[ti]
            if kind == "V" and IPA_VOWELS[sym] == base:
                q = IPA_QUALITY.get(sym) if base in "eo" else None
                walk(li + 1, ti + 1, (i, q) if stressed else hit, silent)
            if kind == "G":
                if IPA_GLIDES[sym] == base and c == base:
                    walk(li + 1, ti + 1, hit, silent)
                walk(li, ti + 1, hit, silent)             # glide from a consonant letter
        if (c == "i" and i > 0 and form[i + 1:i + 2] in text.VOWELS
                and (form[i - 1] in "cg" or form[i - 2:i] in ("gl", "gn"))):
            walk(li + 1, ti, hit, silent)                 # silent i: ciao, giallo, figlio
        elif silent < max_silent and _may_be_silent(form, i):
            walk(li + 1, ti, hit, silent + 1)

    walk(0, 0, None, 0)
    hits = found[min(found)] if found else set()
    return hits.pop() if len(hits) == 1 else None


def _may_be_silent(form: str, i: int) -> bool:
    """A loanword vowel that may be silent: next to another vowel (routine,
    break) or a last e (performance, detectives). Not just any vowel, so a
    truncated IPA (``ri/`` for *anopluri*) does not align."""
    if form[i - 1:i] in text.VOWELS or form[i + 1:i + 2] in text.VOWELS:
        return True
    return form[i] == "e" and not any(c in text.VOWELS for c in form[i + 1:])


def ipa_candidates(form: str, ipas: Iterable[str], check: set[int], stats: Counter) -> list[Stress | None]:
    """Stress of each IPA string of ``form`` (None where it does not map).

    An IPA that only maps with silent vowels counts only if it agrees with
    ``check``, the hyphenation/table stress indexes, when there are any.
    """
    out = []
    for ipa in ipas:
        stats["ipa_strings"] += 1
        s = ipa_stress(form, ipa)
        if s is None and (s := ipa_stress(form, ipa, config.IPA_MAX_SILENT_VOWELS)):
            stats["ipa_silent"] += 1
            if check:
                stats["ipa_silent_checked"] += 1
                stats["ipa_silent_agree"] += s[0] in check
                s = s if s[0] in check else None
        stats["ipa_mapped"] += s is not None
        out.append(s)
    return out


def merge_stress(cands: Iterable[Stress]) -> list[Stress]:
    """Distinct stress indexes; the quality is kept only where all agree."""
    by_idx: dict[int, set] = {}
    for idx, q in cands:
        by_idx.setdefault(idx, set()).add(q)
    return [(idx, qs.pop() if len(qs) == 1 else None) for idx, qs in sorted(by_idx.items())]


def ipa_list(sounds: list[dict]) -> list[str]:
    """IPA strings of ``sounds``: unqualified ones if any, else all of them."""
    with_ipa = [s for s in sounds if s.get("ipa")]
    plain = [s for s in with_ipa if not (s.get("tags") or s.get("note") or s.get("raw_tags"))]
    out = []
    for s in plain or with_ipa:
        out.extend(p.strip() for p in s["ipa"].split(","))
    return out


def agreement(stats: Counter, ev: list[tuple[Stress, str]]) -> None:
    """Count entries where IPA and hyphenation/table give one stress each, and agreement."""
    by: dict[str, set[int]] = {}
    for (idx, _), e in ev:
        by.setdefault(e, set()).add(idx)
    if "ipa" in by and len(by["ipa"]) == 1:
        for other in ("hyphenation", "table"):
            if other in by and len(by[other]) == 1:
                stats[f"ipa_vs_{other}"] += 1
                stats[f"ipa_vs_{other}_agree"] += by["ipa"] == by[other]


# --- Stress-marked spellings -------------------------------------------------

def stress_marked(form: str) -> bool:
    """An accent before the last letter: a dictionary stress mark (abéto) or a foreign one (élite)."""
    return any(i != len(form) - 1 for i in text.accent_positions(form))


def respell(df: pl.DataFrame, known: set[str]) -> tuple[pl.DataFrame, int]:
    """Replace stress-marked spellings in ``form`` and ``lemma`` by the real spelling.

    ``dèi``, ``bacìa`` and ``destinàre`` become ``dei``, ``bacia`` and
    ``destinare``, the unaccented twin among the ``known`` spellings
    (``text.resolve_spelling``); a spelling without one (élite) stays. Its
    accent is then a stress mark: rows without other stress evidence take it
    ("table"). A stress-marked headword read as its own lemma is dropped with
    its inflections: its twin has its own entry (abéto: abeto), or is another
    word (the Italo-Australian bàrista "barrister"). Returns the frame and the
    number of spellings replaced.
    """
    plain = {w for w in known if not stress_marked(w)}
    words = set(df["form"]) | set(df["lemma"].drop_nulls())
    real = {w: r for w in words
            if stress_marked(w) and (r := text.resolve_spelling(w, plain.__contains__))}
    if not real:
        return df, 0
    marks = pl.DataFrame(
        [(w, r[0], r[1], r[2]) for w, r in real.items()], orient="row",
        schema={"form": pl.String, "real": pl.String, "m_idx": pl.Int16, "m_q": pl.String})
    unstressed = pl.col("stress_idx").is_null() & pl.col("m_idx").is_not_null()
    own = df.filter(pl.col("form").is_in(list(real)) & (pl.col("lemma") == pl.col("form")))["form"]
    df = (
        df.filter(~pl.col("lemma").is_in(own.unique().to_list()).fill_null(False))
        .join(marks, on="form", how="left")
        .with_columns(
            pl.when(unstressed).then(pl.lit("table")).otherwise(pl.col("evidence")).alias("evidence"),
            pl.when(unstressed).then(pl.col("m_q")).otherwise(pl.col("quality")).alias("quality"),
            pl.coalesce("stress_idx", "m_idx").alias("stress_idx"),
            pl.coalesce("real", "form").alias("form"),
            pl.col("lemma").replace({w: r[0] for w, r in real.items()}),
        )
        .drop("real", "m_idx", "m_q")
    )
    return df, len(real)


def inherit_misspelling(df: pl.DataFrame) -> pl.DataFrame:
    """Tag "misspelling" every row whose lemma is only a misspelling headword.

    The forms of its own table inherit the tag in the workers; this covers
    those with their own form-of entries (scorazzato, of the misspelt
    scorazzare).
    """
    missp = pl.col("tags").list.contains("misspelling")
    bad = (df.filter(pl.col("form") == pl.col("lemma")).group_by("form").agg(missp.all())
           .filter("tags")["form"].to_list())
    return df.with_columns(
        pl.when(pl.col("lemma").is_in(bad).fill_null(False) & ~missp)
        .then(pl.concat_list("tags", pl.lit(["misspelling"])).list.sort())
        .otherwise("tags").alias("tags"))


# --- Parallel JSONL reading --------------------------------------------------

def iter_chunks(path: Path, chunk_bytes: int = config.KAIKKI_CHUNK_BYTES) -> Iterator[bytes]:
    """Stream a gzip JSONL file as blocks of whole lines."""
    rest = b""
    with gzip.open(path, "rb") as f:
        while block := f.read(chunk_bytes):
            block = rest + block
            cut = block.rfind(b"\n") + 1
            if cut == 0:
                rest = block
                continue
            rest = block[cut:]
            yield block[:cut]
    if rest.strip():
        yield rest


def parallel_map(path: Path, worker: Callable[[bytes], dict]) -> list[dict]:
    """Run ``worker`` (a top-level function) on every chunk of ``path`` in a process pool, in order."""
    with ProcessPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        return list(pool.map(worker, iter_chunks(path)))


# --- FORMS frame -------------------------------------------------------------

class Rows:
    """Column buffers for FORMS rows (plus optional extra columns)."""

    COLS = ("form", "lemma", "pos", "feats", "stress_idx", "quality", "evidence", "tags")

    def __init__(self, extra: tuple[str, ...] = ()) -> None:
        self.cols = {c: [] for c in self.COLS + extra}

    def add(self, form, lemma, pos, feats, stress: Stress | None, evidence, tags, **extra) -> None:
        c = self.cols
        c["form"].append(form)
        c["lemma"].append(lemma)
        c["pos"].append(pos)
        c["feats"].append(feats)
        c["stress_idx"].append(stress[0] if stress else None)
        c["quality"].append(stress[1] if stress else None)
        c["evidence"].append(evidence if stress else "none")
        c["tags"].append(sorted(tags))
        for k, v in extra.items():
            c[k].append(v)

    def frame(self) -> pl.DataFrame:
        sch = {k: v for k, v in schema.FORMS.items() if k in self.cols}
        return pl.DataFrame(self.cols, schema_overrides=sch, strict=False)


def finish(df: pl.DataFrame, source: str) -> pl.DataFrame:
    """Orthographic stress for unstressed rows, dedupe, conform, sort."""
    forms = df.filter(pl.col("stress_idx").is_null())["form"].unique().to_list()
    ortho = {f: s for f in forms if (s := text.orthographic_stress(f))}
    o = pl.DataFrame(
        {"form": list(ortho), "o_idx": [s[0] for s in ortho.values()],
         "o_q": [s[1] for s in ortho.values()]},
        schema={"form": pl.String, "o_idx": pl.Int16, "o_q": pl.String},
    )
    df = df.join(o, on="form", how="left").with_columns(
        pl.when(pl.col("stress_idx").is_null() & pl.col("o_idx").is_not_null())
        .then(pl.lit("ortho")).otherwise(pl.col("evidence")).alias("evidence"),
        pl.coalesce("stress_idx", "o_idx").alias("stress_idx"),
        pl.when(pl.col("stress_idx").is_null()).then(pl.col("o_q"))
        .otherwise(pl.col("quality")).alias("quality"),
    )
    df = df.with_columns(pl.lit(source).alias("source"))
    df = schema.conform(df, schema.FORMS).unique()
    return df.sort(["form", "lemma", "pos", "feats", "evidence", "stress_idx", "quality",
                    pl.col("tags").list.join(",")], nulls_last=True)


def log_stats(source: str, stats: Counter, df: pl.DataFrame, t0: float) -> None:
    if stats["ipa_strings"]:
        log.info("%s: %d/%d IPA transcriptions mapped to a stressed letter (%.1f%%)", source,
                 stats["ipa_mapped"], stats["ipa_strings"], 100 * stats["ipa_mapped"] / stats["ipa_strings"])
    if stats["ipa_silent"]:
        log.info("%s: %d IPA mapped only with silent vowels; %d/%d agree with the hyphenation/table",
                 source, stats["ipa_silent"], stats["ipa_silent_agree"], stats["ipa_silent_checked"])
    for other in ("hyphenation", "table"):
        n = stats[f"ipa_vs_{other}"]
        if n:
            log.info("%s: IPA vs %s stress agreement %.2f%% (%d entries)", source, other,
                     100 * stats[f"ipa_vs_{other}_agree"] / n, n)
    by_ev = dict(df.group_by("evidence").len().sort("evidence").iter_rows())
    log.info("%s: %d rows, %d forms, evidence %s, %.1fs", source, df.height,
             df["form"].n_unique(), by_ev, time.perf_counter() - t0)
