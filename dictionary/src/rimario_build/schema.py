"""Table schemas shared by every stage (OVERHAUL-PLAN §4).

Every stage is a pure function from polars DataFrames to polars DataFrames.
A stage that produces more than one table returns ``dict[str, pl.DataFrame]``
so that ``cache.py`` can store each table as its own parquet file.

Conventions used by every table:

* ``form`` is the real spelling: NFC, lowercase, with orthographic accents
  kept (``città``, ``perché``, ``dà``). Never a stress-marked dictionary
  spelling such as ``càpitano``; see ``text.resolve_spelling``.
* ``stress_idx`` is the character index of the stressed vowel in ``form``
  (NFC, so every accented vowel is one code point).
* ``quality`` is the quality of the stressed vowel: ``"open"`` (è, ò, ɛ, ɔ),
  ``"closed"`` (é, ó, e, o) or null (a, i, u, or unknown). Extraction and
  voting keep it (it is shown in the report's conflicts); ``lexicon.py``
  drops it, so vowel-quality variants are one output row (§5.4).
"""

import polars as pl

# Normalized part-of-speech values. Extractors map their source's labels here.
POS_VALUES = (
    "noun", "verb", "adj", "adv", "name", "pron", "det", "article", "prep",
    "conj", "intj", "num", "particle", "affix", "phrase", "other",
)

# Normalized usage tags. Extractors map their source's labels here and drop
# everything else. ``lexicon.py`` turns them into output flags or filters.
TAG_VALUES = (
    "vulgar", "offensive", "derogatory",               # FLAG_VULGAR
    "archaic", "poetic", "literary", "obsolete",       # FLAG_ARCHAIC; minor homograph reading
    "abbreviation", "misspelling",                     # excluded (§7)
    "proper",                                          # proper noun (FLAG_PROPER)
    "rare",                                            # minor homograph reading (§6.4)
    "regional", "dialectal",                           # no effect on the output
)

# Where a stress value comes from.
EVIDENCE_VALUES = (
    "ipa",           # stress mark in an IPA transcription
    "hyphenation",   # stress-marked hyphenation (kaikki_en `grà‧tis`, kaikki_it `cà`,`sa`)
    "table",         # stress-marked conjugation/inflection table or head form
    "sill",          # it.wiktionary {{-sill-}} section
    "ortho",         # the spelling itself carries the accent (città, perché)
    "none",          # no stress information (stress_idx is null)
)

# Tiers, best first: ties between readings go to the earlier tier.
TIER_ORDER = ("override", "attested", "propagated", "predicted")

# Tag groups behind FLAG_VULGAR and FLAG_ARCHAIC.
VULGAR_TAGS = ("vulgar", "offensive", "derogatory")
ARCHAIC_TAGS = ("archaic", "poetic", "literary", "obsolete")

# ``feats``: Morph-it-style feature string, the part after the colon in a
# Morph-it tag. Verbs: "ind+pres+1+s", "sub+impf+3+p", "cond+pres+2+s",
# "ind+past+3+s" (passato remoto), "ind+fut+1+p", "impr+pres+2+s",
# "inf+pres", "ger+pres", "part+pres+s+m", "part+past+p+f"; clitics are
# appended as in Morph-it: "inf+pres+me+lo", "ger+pres+lo", "impr+pres+2+p+vi".
# Nouns: "m+s", "f+p". Adjectives: "pos+m+s", "sup+f+p". Null when unknown.

# One row per (source, form, lemma, pos, feats) reading. Produced by
# sources/kaikki_en.py, sources/kaikki_it.py, sources/morphit.py.
FORMS = {
    "form": pl.String,
    "lemma": pl.String,             # NFC lowercase; equal to form for a lemma entry
    "pos": pl.String,               # POS_VALUES
    "feats": pl.String,             # see above; nullable
    "stress_idx": pl.Int16,         # nullable
    "quality": pl.String,           # nullable
    "evidence": pl.String,          # EVIDENCE_VALUES
    "tags": pl.List(pl.String),     # TAG_VALUES, sorted, unique
    "source": pl.String,            # source id from sources.toml
}

# Word counts or Zipf values from one frequency source. Produced by
# sources/wordfreq_it.py, sources/opensubtitles.py, sources/leipzig.py
# under the key "freq".
FREQ = {
    "form": pl.String,              # NFC lowercase token
    "count": pl.Int64,              # raw count; null for wordfreq
    "zipf": pl.Float64,             # log10(count / total_tokens * 1e9), or wordfreq's Zipf
    "cap_count": pl.Int64,          # leipzig only: capitalized, not sentence-initial occurrences
    "lower_count": pl.Int64,        # leipzig only: all-lowercase occurrences
    "source": pl.String,
}

# One row per frequency source, under the key "meta" next to "freq".
FREQ_META = {
    "source": pl.String,
    "total_tokens": pl.Int64,       # null for wordfreq
    "floor_zipf": pl.Float64,       # Zipf of one occurrence, or wordfreq's cutoff
    "complete": pl.Boolean,         # True if a missing word means "below floor" (§6.2)
    "truncated": pl.Boolean,        # True if the list was cut at a cutoff
}

# Preceding-word counts from the Leipzig sentences, under the key "contexts".
# ``cue`` is restricted to config.CUE_CANDIDATES; homographs.py classifies cues.
CONTEXTS = {
    "form": pl.String,
    "cue": pl.String,               # the lowercase token right before ``form``
    "count": pl.Int64,
}

# The group key of a stress reading: stress/vote.py votes and stress/paradigm.py
# propagates per (form, lemma, pos).
READING_KEY = ["form", "lemma", "pos"]

# Stress readings. stress/vote.py produces tier "attested"; paradigm.py adds
# "propagated"; model.py adds "predicted" (with confidence < 1).
# vote.py and paradigm.py return them in ``sort_readings`` order.
READINGS = {
    "form": pl.String,
    "stress_idx": pl.Int16,
    "quality": pl.String,           # nullable
    "lemma": pl.String,
    "pos": pl.String,
    "tier": pl.String,              # TIER_ORDER
    "confidence": pl.Float64,       # 1.0 except for "predicted"
    "evidence": pl.String,          # strongest evidence for this reading
    "sources": pl.List(pl.String),  # sorted source ids that support it
}

# Stress conflicts between sources (§5.1, stress/vote.py): a source's own vote
# missing from the readings of a form with a single (lemma, pos), or a
# kaikki_it-only reading that kaikki_en contradicts (that reading is dropped).
CONFLICTS = {
    "form": pl.String,
    "lemma": pl.String,
    "pos": pl.String,
    "readings": pl.String,          # human-readable, e.g. "kaikki_en:càpito kaikki_it:capìto"
}

# Merged per-spelling frequency (frequency/merge.py, key "form_zipf").
FORM_ZIPF = {
    "form": pl.String,
    "zipf": pl.Float64,             # merged estimate (§6.3), or the §6.5 fallback
    "n_sources": pl.Int8,           # corpora that actually contain the form
    "n_lexicons": pl.Int8,          # lexicons that contain the form (tie-breaker, §6.5)
    "estimate": pl.String,          # "corpus" | "lexicon_only"
}

# One row per output row, before export. Built by lexicon.py (inclusion +
# collapsing readings), then frequency/homographs.py fills zipf/share/is_default.
ENTRIES = {
    "form": pl.String,
    "stress_idx": pl.Int16,
    "quality": pl.String,           # always null: vowel quality never splits rows (§5.4)
    "lemmas": pl.List(pl.String),   # sorted
    "pos": pl.List(pl.String),      # sorted
    "tier": pl.String,              # best tier among collapsed readings
    "confidence": pl.Float64,
    "tags": pl.List(pl.String),     # sorted union of usage tags
    "is_proper": pl.Boolean,
    "provenance": pl.String,        # e.g. "kaikki_en:ipa,kaikki_it:hyphenation"
    "zipf": pl.Float64,             # reading Zipf (§6.4)
    "share": pl.Float64,            # 1.0 for non-homographs
    "share_method": pl.String,      # "single" | "capitalization" | "function_word" | "minor" | "participle"
                                    # | "context" | "lemma_ratio" | "even" (rule of the top-level split)
    "is_default": pl.Boolean,
}

# Output flag bits (§8), summed in the CSV's 4th field.
FLAG_NON_DEFAULT = 1    # not the default reading of a homograph
FLAG_PREDICTED = 2      # stress predicted by the model (tier "predicted")
FLAG_VULGAR = 4         # VULGAR_TAGS: vulgar / offensive / derogatory
FLAG_ARCHAIC = 8        # ARCHAIC_TAGS: archaic / poetic / literary
FLAG_PROPER = 16        # proper noun


def sort_readings(df: pl.DataFrame) -> pl.DataFrame:
    """The canonical order of a READINGS-like frame: READING_KEY, stress_idx, quality."""
    return df.sort(*READING_KEY, "stress_idx", "quality", nulls_last=True)


def empty(schema: dict) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def conform(df: pl.DataFrame, schema: dict) -> pl.DataFrame:
    """Select and cast ``df`` to exactly ``schema``; fails on a missing column."""
    return df.select([pl.col(name).cast(dtype) for name, dtype in schema.items()])
