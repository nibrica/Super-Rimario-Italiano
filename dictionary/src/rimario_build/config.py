"""Paths, weights and thresholds: every tunable number of the build lives here."""

from pathlib import Path

# --- Paths -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]          # dictionary/
SOURCES_TOML = ROOT / "sources.toml"
SOURCES_LOCK = ROOT / "sources.lock.json"
CURATION_DIR = ROOT / "curation"
OVERRIDES_TSV = CURATION_DIR / "overrides.tsv"
GOLD_TSV = CURATION_DIR / "gold.tsv"
FREQ_PAIRS_TSV = CURATION_DIR / "freq_pairs.tsv"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"                           # raw/<source id>/
CACHE_DIR = DATA_DIR / "cache"                       # parquet output of each stage
WEB_DIR = ROOT.parent / "web"                        # the site: the CSV and attribution are served from here
OUT_CSV = WEB_DIR / "parole-accenti-frequenze.csv"
OUT_ATTRIBUTION = WEB_DIR / "ATTRIBUTION.md"
OUT_REPORT = ROOT / "report.md"                      # QA report, not a site file
UV_LOCK = ROOT / "uv.lock"                           # its sha256 is part of every cache key
RAW_HASHES_JSON = "raw_sha256.json"                  # under CACHE_DIR: raw file sha256 by path, size, mtime

# --- Text --------------------------------------------------------------------

# Letters allowed in an output form: the Latin alphabet plus the accented
# vowels Italian spelling uses. Anything else excludes the form.
ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzàèéìíòóùú")

# --- Fetch, cache and parallelism --------------------------------------------

HTTP_TIMEOUT_S = 60
HTTP_USER_AGENT = "rimario-build (+https://github.com/nibrica/Super-Rimario-Italiano)"
MAX_WORKERS = None                 # ProcessPoolExecutor default (CPU count)

# --- Sources -----------------------------------------------------------------

# kaikki_en, kaikki_it
KAIKKI_CHUNK_BYTES = 32 << 20      # decompressed JSONL bytes per parallel parse task
# An entry is vulgar/offensive when at least this share of its senses is (troia: 1 of 2).
KAIKKI_VULGAR_SHARE = 0.5
KAIKKI_MILD_TAGS = frozenset({"mildly"})   # a "mildly vulgar" sense (cristo, madonna) is not vulgar
# IPA alignment fallback: spelling vowels that may be silent (performance /perˈfɔr.mans/).
IPA_MAX_SILENT_VOWELS = 3

# morphit
MORPHIT_ARCHIVE = "morph-it.tgz"
MORPHIT_MEMBER = "current_version/morph-it_048.txt"
MORPHIT_DROP_CATEGORIES = frozenset({"PON", "SENT", "SYM", "SMI"})   # punctuation, emoticons
MORPHIT_VERB_CATEGORIES = frozenset({"VER", "AUX", "MOD", "CAU", "ASP"})
MORPHIT_POS = {
    **dict.fromkeys(MORPHIT_VERB_CATEGORIES, "verb"),
    "ADJ": "adj", "ADV": "adv", "NPR": "name", "PRE": "prep", "CON": "conj", "INT": "intj",
    "WH": "adv", "WH-CHE": "conj", "NE": "pron", "SI": "pron", "CI": "pron", "CE": "pron",
    "TALE": "det", "DET-NUM-CARD": "num", "PRO-NUM": "num", "ABL": "other",
}
MORPHIT_POS_PREFIXES = (           # checked in order, after MORPHIT_POS
    ("NOUN-", "noun"), ("ARTPRE-", "prep"), ("ART-", "article"), ("DET-", "det"), ("PRO-", "pron"),
)
# Compound clitic tokens (Morph-it "inf+pres+melo") are split like single ones ("me+lo").
MORPHIT_CLITIC_COMPOUNDS = {
    a + b: (a, b) for a in ("me", "te", "se", "ce", "ve", "glie") for b in ("lo", "la", "li", "le", "ne")
}
# Spelling quirk: grave for acute after "ch"/"tr" (perchè -> perché, ventitrè -> ventitré).
MORPHIT_ACUTE_ENDINGS = (("chè", "ché"), ("trè", "tré"))
# Forms (or every form of a lemma) tagged misspelling; accent-glyph twins (piú/più) are found by rule.
MORPHIT_MISSPELLINGS = frozenset({
    "pò", "ke", "caffé", "ahimé", "ohimé", "striscie", "angoscie", "fascie", "proveniendo", "accellerare",
})
# Accent-glyph twins (same lemma and tag) whose acute spelling is the standard one; otherwise the grave one is.
MORPHIT_ACUTE_STANDARD = frozenset({
    "sé", "viceré", "scimpanzé", "coupé", "pavé", "defilé", "tournée", "josé", "élite", "élites", "équipe",
})
# French spellings whose non-final accent is not a stress mark (élite is elìte), even with a plain twin.
MORPHIT_FOREIGN_ACCENTS = frozenset({
    "élite", "élites", "èlite", "èlites", "équipe", "èquipe", "crédit", "débacle", "ménage", "ménages", "réclame",
})
MORPHIT_LEMMA_FIXES = {"dimmi": "dire"}       # form -> lemma where Morph-it lists the form as its own lemma

# wordfreq_it, opensubtitles, leipzig
WORDFREQ_LIST = "large"                             # wordfreq wordlist used for Italian
OPENSUBTITLES_FILE = "it_full.txt"                  # `word count` per line
LEIPZIG_TARBALL_RE = r"ita_news_(\d{4})_1M\.tar\.gz"   # newest year on disk wins
LEIPZIG_CHUNK_LINES = 50_000                       # sentence lines per parallel parse task
LEIPZIG_SENTENCES_SUFFIX = "-sentences.txt"         # the only member read
# A capitalized word right after one of these (or first in the sentence) is
# sentence-initial, so its capital doesn't count toward cap_count.
SENTENCE_BREAK_CHARS = frozenset(".!?:…\"'«»“”„")
# Elided cue (left of the apostrophe in l'amica, dell'uomo, c'è) -> canonical
# cue in CUE_CANDIDATES. Elided words not listed here are kept as they are.
ELIDED_CUES = {
    "l": "l", "gl": "gli", "un": "una", "quest": "questa", "quell": "quella",
    "dell": "della", "all": "alla", "dall": "dalla", "nell": "nella", "sull": "sulla",
    "nessun": "nessuna", "alcun": "alcuna",
    "m": "mi", "t": "ti", "s": "si", "c": "ci", "v": "vi", "n": "ne",
}

# --- Stress ------------------------------------------------------------------

# Voting on attested stress (stress/vote.py). Source priority: earlier wins.
STRESS_SOURCE_PRIORITY = ("kaikki_en", "kaikki_it")
VOTE_EVIDENCE_PRIORITY = ("ortho", "table", "hyphenation", "ipa", "sill")   # inside one source, earlier wins
# Without a written accent, a polysyllable is never stressed on one of these final
# vowels (congelatò, triviò), so such evidence is dropped. Final -u is left out:
# polysyllables in -u are loanwords, often final-stressed (menu, parvenu, katmandu).
VOTE_UNSTRESSED_FINALS = "aeio"

# Paradigm propagation (stress/paradigm.py). Rhizotonic verb features, in order of preference
# as a stress source.
PARADIGM_RHIZOTONIC = (
    "ind+pres+1+s", "ind+pres+3+s", "ind+pres+2+s", "ind+pres+3+p",
    "sub+pres+1+s", "sub+pres+2+s", "sub+pres+3+s", "sub+pres+3+p", "impr+pres+2+s",
)
# Every other verb form: stressed vowel run counted from the end (1 = last).
# ind+past+1+s is decided in paradigm.ending (weak -ài/-éi/-ìi: 1, strong: 2).
PARADIGM_ENDING_RUN = {
    **dict.fromkeys(("ind+impf+1+s", "ind+impf+2+s", "ind+impf+3+s", "ind+impf+1+p", "ind+impf+2+p"), 2),
    "ind+impf+3+p": 3,
    **dict.fromkeys(("ind+past+2+s", "ind+past+3+s", "ind+past+1+p", "ind+past+2+p"), 2),
    "ind+past+3+p": 3,
    **dict.fromkeys(("ind+fut+1+s", "ind+fut+2+s", "ind+fut+3+s"), 1),
    **dict.fromkeys(("ind+fut+1+p", "ind+fut+2+p", "ind+fut+3+p"), 2),
    "cond+pres+1+s": 1,
    **dict.fromkeys(("cond+pres+2+s", "cond+pres+3+s", "cond+pres+1+p", "cond+pres+2+p"), 2),
    "cond+pres+3+p": 3,
    **dict.fromkeys(("sub+impf+1+s", "sub+impf+2+s", "sub+impf+3+s", "sub+impf+2+p"), 2),
    **dict.fromkeys(("sub+impf+1+p", "sub+impf+3+p"), 3),
    **dict.fromkeys(("ind+pres+1+p", "sub+pres+1+p", "impr+pres+1+p", "ind+pres+2+p",
                     "sub+pres+2+p", "impr+pres+2+p"), 2),
    **dict.fromkeys(("ger+pres", "part+pres", "part+past", "inf+pres"), 2),
}
# Lemmas whose past participle is proparoxytone (sòlito, lécito): its stressed run from the end.
PARADIGM_PARTICIPLE_RUN = {"solere": 3, "licere": 3, "lecere": 3}
# Quality of the stressed e of a verb_ending form: (mood+tense, rest of the word
# from the stressed vowel) -> quality. Each is >= 99.4% pure on the kaikki_en
# conjugation tables; -erèbbe/-erébbe (50/50) and strong pasts stay null.
PARADIGM_ENDING_QUALITY = {
    ("cond+pres", "ei"): "open", ("ger+pres", "endo"): "open",
    ("part+pres", "ente"): "open", ("part+pres", "enti"): "open",
    **dict.fromkeys((("cond+pres", e) for e in ("esti", "emmo", "este")), "closed"),
    **dict.fromkeys((("ind+past", e) for e in ("ei", "esti", "emmo", "este", "erono")), "closed"),
    **dict.fromkeys((("ind+fut", e) for e in ("emo", "ete")), "closed"),
    **dict.fromkeys((("ind+impf", e) for e in ("evo", "evi", "eva", "evano")), "closed"),
    **dict.fromkeys((("sub+impf", e) for e in ("essi", "esse", "essimo", "este", "essero")), "closed"),
    **dict.fromkeys((("ind+pres", "ete"), ("impr+pres", "ete"), ("sub+pres", "ete")), "closed"),
}
# Nominal plurals that change the stem: form -> stress index (applied when the
# lemma has a reading; uòmo → uòmini, bùe → buòi, dìo → dèi, mìlle → mìla).
PARADIGM_NOMINAL_EXCEPTIONS = {"uomini": 1, "buoi": 2, "dei": 1, "mila": 1, "templi": 1, "ali": 0, "armi": 0}
# Enclitic hosts and clitic combinations.
PARADIGM_CLITIC_HOSTS = ("impr+pres+2+s", "impr+pres+2+p", "impr+pres+1+p", "ger+pres", "inf+pres")
PARADIGM_CLITICS = (
    "mi", "ti", "si", "ci", "vi", "ne", "lo", "la", "li", "le", "gli",
    *(f"{a}+{b}" for a in ("me", "te", "se", "ce", "ve", "glie") for b in ("lo", "la", "li", "le", "ne")),
)
# Productive suffix families, stressed vowel marked: "ìssimo|a|i|e" is -ìssimo,
# -ìssima, -ìssimi, -ìssime (each variant replaces the last letter). Each family
# is validated at build time on the attested non-verb readings and used only if
# its stress precision and support reach the minimums below; its vowel quality
# only if the quality precision does too. Longest match wins.
PARADIGM_SUFFIXES = (
    "ménte", "ménto|i", "zióne|i", "sióne|i", "ità", "ìsmo|i", "ìsta|i|e", "ìssimo|a|i|e",
    "ìno|a|i|e", "étto|a|i|e", "èllo|a|i|e", "óso|a|i|e", "tóre|i", "trìce", "ézza|e",
    "ànza|e", "ènza|e", "àggio|i", "àbile|i", "ìbile|i", "ière|i|a", "àrio|i", "òrio|a|i|e",
    "ùra|e", "àle|i", "ìstico|a|i|he", "ésimo|a|i|e", "logìa|e", "grafìa|e", "ìccio|a|i|e",
    "òtto|a|i|e", "óne|i", "àccio|a|i|e", "ùccio|a|i|e", "àstro|a|i|e", "àio|a", "àto|a|i|e",
    "ìvo|a|i|e", "ènte|i", "ànte|i", "ìfico|a",
)
PARADIGM_SUFFIX_MIN_PRECISION = 0.98
PARADIGM_SUFFIX_MIN_SUPPORT = 50

# Learned fallback (stress/model.py).
MODEL_SEED = 1234
MODEL_FOLDS = 5                    # 1 / MODEL_FOLDS of the attested lemma groups is held out
MODEL_CONTEXT_CHARS = 3            # characters on each side of the candidate vowel
MODEL_SUFFIX_NGRAMS = (1, 2, 3, 4, 5)
MODEL_MAX_TRAIN_FORMS = 300_000    # deterministic subsample above this (speed), non-verbs first
MODEL_SUFFIX_VOCAB = 254           # most frequent suffixes per n-gram size; the rest share one code
MODEL_MAX_ITER = 300
MODEL_LEARNING_RATE = 0.2
MODEL_MAX_LEAF_NODES = 127
# Without it, leaves with a near-zero hessian get huge values once the fit set
# is large (300k forms): logits reach ±1e6 and -mma words come out final-stressed
# (programmà), although CV on the smaller folds looks fine. 1.0 keeps CV accuracy.
MODEL_L2_REGULARIZATION = 1.0
MODEL_TARGET_ACCURACY = 0.98       # the thresholds are tuned so held-out accuracy above them reaches this
# Ship a prediction only when its confidence reaches its POS's threshold,
# MODEL_MIN_CONFIDENCE for the POS not listed. Held-out attested accuracy above
# them (coverage): nouns 98.8% (88%), adjectives 99.4% (95%), verbs 99.9% (98%),
# names 98.8% (63%; at 0.90 only ~97%). Each POS must reach MODEL_TARGET_ACCURACY.
MODEL_MIN_CONFIDENCE = 0.90
MODEL_MIN_CONFIDENCE_BY_POS = {"noun": 0.90, "adj": 0.90, "verb": 0.90, "name": 0.97}

# --- Frequency ---------------------------------------------------------------

# Merge (frequency/merge.py).
SOURCE_WEIGHTS = {"wordfreq": 1.0, "opensubtitles": 1.0, "leipzig_news": 1.0}   # W_s, the source weight
RELIABLE_COUNT = 20                # r_s = min(1, count / RELIABLE_COUNT): how reliable a count is
WORDFREQ_RELIABLE_ZIPF = 2.0       # wordfreq r_s = 1 above this, falls toward its cutoff
MISSING_OFFSET = 0.5               # a missing word counts at floor - MISSING_OFFSET
MISSING_WEIGHT_FACTOR = 0.5        # ...with this fraction of the source's weight
# wordfreq r_s ramps linearly from this at its floor (cutoff) to 1 at
# WORDFREQ_RELIABLE_ZIPF: a value at the cutoff counts like ~4 occurrences.
WORDFREQ_MIN_RELIABILITY = 0.2
OUTLIER_DISTANCE = 1.5             # robustness check: the weight cut starts here...
OUTLIER_RAMP = 1.0                 # ...and reaches OUTLIER_WEIGHT_FACTOR this much farther
OUTLIER_AGREEMENT = 0.5
OUTLIER_WEIGHT_FACTOR = 0.25
LEXICON_ONLY_OFFSET = 0.5          # lexicon-only forms get min_floor - this
# Lexicon-only Zipf: min_floor - LEXICON_ONLY_OFFSET for the forms in
# the most lexicons, LEXICON_ONLY_STEP less per missing lexicon, and never below
# LEXICON_ONLY_MIN_ZIPF. With the real floors (OpenSubtitles 0.61) min_floor - 0.5
# is ~0.11, so the minimum applies (0.32-0.34): it keeps a 50/50 split
# (-log10 2 = -0.301) of a lexicon-only form >= 0 with its n_lexicons step still
# visible after round(zipf * 100). Corpus estimates stay above it (min ~0.38).
LEXICON_ONLY_MIN_ZIPF = 0.31
LEXICON_ONLY_STEP = 0.01
# The unaccented spelling of a final-accent word (cosi/così) is capped at the
# twin's merged Zipf plus their difference in this source (edited news: few
# accent-dropping typos; OpenSubtitles has cosi about as often as così).
ACCENT_TWIN_REFERENCE = "leipzig_news"
ACCENT_TWIN_MIN_GAP = 0.5          # ...only where it is this much rarer there (papa/papà: 0.14, kept)
DISAGREEMENTS_KEEP = 2000          # largest |zipf_source - zipf_others| kept for the report

# Homograph split (frequency/homographs.py).
CONTEXT_PRIOR = 2.0                # α, additive smoothing of cue counts
NOMINAL_CUES = frozenset({
    "il", "un", "una", "uno", "i", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "quel", "quei", "quegli",
    "del", "dello", "della", "dei", "degli", "delle",
    "al", "allo", "alla", "ai", "agli", "alle",
    "dal", "dallo", "dalla", "dai", "dagli", "dalle",
    "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle",
    "mio", "mia", "tuo", "tua", "suo", "sua", "nostro", "nostra", "vostro", "vostra",
    "ogni", "qualche", "nessun", "nessuna", "alcun", "alcuna",
})
VERBAL_CUES = frozenset({
    "mi", "ti", "si", "ci", "vi", "ne", "non",
    "io", "tu", "lui", "lei", "noi", "voi", "egli", "ella", "esso", "essa",
    "me", "te", "se", "ce", "ve",
})
# Ignored cues: clitic or article, and "loro" (subject pronoun or possessive,
# il loro compito).
AMBIGUOUS_CUES = frozenset({"la", "lo", "le", "li", "gli", "l", "loro"})
# leipzig.py counts only these preceding tokens (keeps the contexts table small).
CUE_CANDIDATES = NOMINAL_CUES | VERBAL_CUES | AMBIGUOUS_CUES
# The capitalization rule needs at least this many Leipzig occurrences of known
# case (capitalized mid-sentence or all lowercase); below it the next rule decides.
CAPITALIZATION_MIN_COUNT = 3
# Function-word rows take no cue side. Against content-word rows they get
# this share outright: a function word is the common reading of its spelling
# (glìe "glia" vs the clitic glie).
FUNCTION_POS = frozenset({"prep", "conj", "article", "det", "pron"})
FUNCTION_WORD_SHARE = 0.99
# Rows tagged archaic, poetic, literary, obsolete or rare against untagged rows
# get this share (fìero of "fire" vs fièro, desidèro vs desìdero).
MINOR_READING_SHARE = 0.02
# Participle vs imperative + clitic (trovàti/tròvati, moderàti/mòderati,
# autorizzàti/autorìzzati): a form ending in one of these, with a row stressed
# on the vowel before "ti" and every other row a verb-only reading stressed
# earlier, gives that row this share; the participle is far the more common.
PARTICIPLE_ENDINGS = ("ati", "iti", "uti")
PARTICIPLE_SHARE = 0.9
# Context sides: a row is nominal if it has a noun or name reading, or
# an adjective reading without a verb one (a participle tagged adj + verb is
# verbal); verbal if it has a verb or adverb reading (verbal cues such as "non",
# "mi" precede both). A row with both a noun and a verb reading (àncora,
# ìndica) is on both sides and takes part in both cue shares.
NOMINAL_POS = frozenset({"noun", "name"})
VERBAL_POS = frozenset({"verb", "adv"})
# The context rule needs at least this many nominal + verbal cues for the form;
# below it the next rule decides. Cues rarely precede adverbs, participles and
# infinitives (capìto: 2 cues in 1,397 occurrences), so a handful of them only
# reflects whichever reading takes articles, not the readings' real shares.
CONTEXT_MIN_CUES = 50
# A reading's Zipf is never below this (1 after × 100): a rare reading of a
# frequent spelling (dèttagli, detta+gli, share 4e-6) or a three-way split of a
# lexicon-only form would otherwise fall below 0 and be written as 0.
READING_MIN_ZIPF = 0.01

# --- Lexicon, export and report ----------------------------------------------

# Unstressed function words: the articles and the clitic pronouns. They never
# carry stress of their own, so they can't end a line or rhyme, and their high
# frequency puts them above the real rhymes (si, mi, ci, ti before così). The
# whole form goes, with its other readings (the note la, the letter i, glìe
# plural of glia): frequencies are split among readings later, so a reading
# left alone would get the clitic's whole frequency. Stressed pronouns (me, te,
# sé, lui, noi) and uno/una (also numerals: nessuno, luna) are good rhymes and stay.
ATONIC_FORMS = frozenset({
    "il", "lo", "la", "i", "gli", "le", "un",
    "mi", "ti", "si", "ci", "vi", "li", "ne", "ce", "ve", "glie",
})

# Loanwords among forms whose stress is only predicted or from the
# single-vowel rule, unless they have a reading in LOANWORD_ITALIAN_POS (me):
# out if spelled with LOANWORD_CHARS and not ending in an Italian suffix after
# at least LOANWORD_MIN_STEM letters (juventini, mixare), or if wordfreq's
# English Zipf exceeds the Italian one by more than LOANWORD_EN_MARGIN. At 0.25
# it drops the, one, time, performance, governance, apple, jack; below 0.1 it
# starts to drop Italian words (micro, bio, mono: +0.04..0.08). online (-0.02)
# can't be told apart this way.
LOANWORD_CHARS = frozenset("jkwxy")
LOANWORD_ITALIAN_POS = frozenset({"article", "prep", "conj", "pron", "det"})
LOANWORD_MIN_STEM = 3
LOANWORD_ITALIAN_SUFFIXES = (
    "ese", "esi", "ano", "ana", "ani", "ane", "ino", "ina", "ini", "ine", "ismo", "ismi",
    "ista", "iste", "isti", "ale", "ali", "ico", "ica", "ici", "iche", "ato", "ata", "ati",
    "ate", "are", "ando", "zione", "zioni", "mente", "ità", "oso", "osa", "osi", "ose",
    "ario", "aria", "ari", "ezza",
)
LOANWORD_EN_MARGIN = 0.25
# A form found in no corpus needs at least this many lexicons (of Morph-it! and
# the two Wiktionaries) to stay, unless paradigm derived it as a verb + clitics
# (portàndoglielo: regular, and rhymes). At 2 it drops ~318k forms that only one
# lexicon lists, 5.8 of the 15.8 MB of the CSV: mostly generated inflections, and
# the lexicons' typos (muoiaa, indebitaa in Wiktionary inflection tables) with
# them. 1 keeps every form; overrides.tsv `add` lines bring a reading back.
UNSEEN_MIN_LEXICONS = 2
REPORT_TOP_N = 50                  # rows per bounded list in report.md
REPORT_UNATTESTED_N = 200          # most frequent forms without attested stress
REPORT_ZIPF_BANDS = (1, 2, 3, 4, 5, 6)   # band edges for row counts by Zipf

# --- Curation tests (tests/test_curation.py) ---------------------------------

GOLD_MIN_ACCURACY = 0.90           # share of curation/gold.tsv rows the output must satisfy
FREQ_PAIRS_MIN_AGREEMENT = 0.85    # share of curation/freq_pairs.tsv pairs in the right order
