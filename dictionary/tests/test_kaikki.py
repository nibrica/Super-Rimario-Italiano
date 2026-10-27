"""kaikki_en / kaikki_it extractors on small real (trimmed) entries."""

import gzip
from pathlib import Path

import orjson
import polars as pl
import pytest

from rimario_build import schema
from rimario_build.sources import kaikki_en, kaikki_it
from rimario_build.sources.kaikki_common import (
    entry_tags, hyphenation_stress, ipa_stress, lemma_feats, map_tags, verb_feats,
)
from rimario_build.sources.kaikki_en import compound_reading, form_of_lemmas
from rimario_build.sources.kaikki_it import conj_tags, gloss_tags, sense_lemma

CONJ = "conjugation"


def _f(form, tags, link=None):
    out = {"form": form, "tags": tags, "source": CONJ}
    if link:
        out["links"] = [[form, link + "#Italian"]]
    return out


def _formof(word, pos, lemma, tags, hyph, ipa):
    return {"word": word, "pos": pos, "lang_code": "it",
            "sounds": [{"ipa": ipa}], "hyphenations": [{"parts": [hyph]}],
            "senses": [{"form_of": [{"word": lemma}], "tags": ["form-of", *tags]}]}


EN = [
    {"word": "capitare", "pos": "verb", "lang_code": "it",
     "forms": [
         {"form": "capitàre", "tags": ["canonical"], "links": [["capitàre", "capitare"]]},
         {"form": "no-table-tags", "tags": ["table-tags"], "source": CONJ},
         {"form": "it-conj", "tags": ["inflection-template"], "source": CONJ},
         {"form": "avére", "tags": ["auxiliary"], "source": CONJ},
         _f("càpito", ["first-person", "indicative", "present", "singular"], "capito"),
         _f("càpitano", ["indicative", "plural", "present", "third-person"], "capitano"),
         _f("capitò", ["historic", "indicative", "past", "singular", "third-person"]),
         _f("capitàndo", ["gerund"], "capitando"),
         _f("capitàto", ["participle", "past"], "capitato"),
         _f("non capitàre", ["imperative", "negative", "second-person", "singular"]),
     ],
     "sounds": [{"ipa": "/ka.piˈta.re/"}], "hyphenations": [{"parts": ["ca‧pi‧tà‧re"]}],
     "senses": [{"glosses": ["to happen"], "tags": ["intransitive"]}]},
    {"word": "capitano", "pos": "noun", "lang_code": "it",
     "head_templates": [{"name": "it-noun", "args": {"1": "m"}}],
     "forms": [{"form": "capitani", "tags": ["plural"]},
               {"form": "capitanio", "tags": ["alternative", "archaic"]}],
     "sounds": [{"ipa": "/ka.piˈta.no/"}], "hyphenations": [{"parts": ["ca‧pi‧tà‧no"]}],
     "senses": [{"glosses": ["captain"], "tags": ["masculine"]}]},
    _formof("capitano", "verb", "capitare", ["indicative", "plural", "present", "third-person"],
            "cà‧pi‧ta‧no", "/ˈka.pi.ta.no/"),
    {"word": "viola", "pos": "noun", "lang_code": "it",
     "sounds": [{"ipa": "/viˈɔ.la/"}, {"ipa": "/ˈvjɔ.la/"}],
     "hyphenations": [{"parts": ["vi", "ò", "la"]}, {"parts": ["viò", "la"]}],
     "senses": [{"glosses": ["viola"], "tags": ["feminine"]}]},
    _formof("viola", "verb", "violare", ["indicative", "present", "singular", "third-person"],
            "vì‧o‧la", "/ˈvi.o.la/"),
    {"word": "città", "pos": "noun", "lang_code": "it",
     "senses": [{"glosses": ["city"], "tags": ["feminine", "invariable"]}]},
    {"word": "perché", "pos": "conj", "lang_code": "it",
     "sounds": [{"ipa": "/perˈke/"}, {"note": "Lombardy", "ipa": "/perˈkɛ/"}],
     "hyphenations": [{"parts": ["per‧ché"]}], "senses": [{"glosses": ["because"]}]},
    {"word": "dare", "pos": "verb", "lang_code": "it",
     "forms": [_f("dò", ["first-person", "indicative", "present", "singular"], "do"),
               _f("dà", ["indicative", "present", "singular", "third-person"], "da"),
               _f("diède", ["historic", "indicative", "past", "singular", "third-person"], "diede")],
     "senses": [{"glosses": ["to give"]}]},
    _formof("dò", "verb", "dare", ["first-person", "indicative", "present", "singular"], "dò", "/ˈdɔ/"),
    _formof("dà", "verb", "dare", ["indicative", "present", "singular", "third-person"], "dà", "/da/"),
    {"word": "da", "pos": "prep", "lang_code": "it", "senses": [{"glosses": ["from"]}]},
    {"word": "fare", "pos": "verb", "lang_code": "it",
     "forms": [_f("fà", ["indicative", "present", "singular", "third-person"])],
     "senses": [{"glosses": ["to do"]}]},
    {"word": "fa", "pos": "adv", "lang_code": "it", "senses": [{"glosses": ["ago"]}]},
    {"word": "fà", "pos": "verb", "lang_code": "it",
     "senses": [{"glosses": ["misspelling of fa"], "tags": ["alt-of", "misspelling"],
                 "alt_of": [{"word": "fa"}]}]},
    {"word": "dimmelo", "pos": "verb", "lang_code": "it",
     "sounds": [{"ipa": "/ˈdim.me.lo/"}], "hyphenations": [{"parts": ["dìm‧me‧lo"]}],
     "senses": [{"glosses": ["compound of di', the second-person singular imperative form of "
                             "dire, with me (the conjunctive variant of mi) and lo"],
                 "tags": ["compound-of"], "compound_of": [{"word": "di'"}]}]},
    {"word": "cazzo", "pos": "noun", "lang_code": "it",
     "head_templates": [{"name": "tlb", "args": {"1": "it", "2": "vulgar"}}],
     "senses": [{"glosses": ["dick"], "tags": ["masculine", "vulgar"]},
                {"glosses": ["damn"], "tags": ["masculine"]}]},
    {"word": "Roma", "pos": "name", "lang_code": "it", "sounds": [{"ipa": "/ˈro.ma/"}],
     "senses": [{"glosses": ["Rome"]}]},
    {"word": "made in Italy", "pos": "phrase", "lang_code": "it", "senses": [{"glosses": ["x"]}]},
    # Stress-marked headwords: a twin of a known spelling is respelt (§4)...
    {"word": "abeto", "pos": "noun", "lang_code": "it", "sounds": [{"ipa": "/aˈbe.to/"}],
     "senses": [{"glosses": ["fir"], "tags": ["masculine"]}]},
    {"word": "abéto", "pos": "noun", "lang_code": "it", "forms": [{"form": "abéti", "tags": ["plural"]}],
     "senses": [{"glosses": ["fir"], "tags": ["masculine"]}]},
    {"word": "dei", "pos": "prep", "lang_code": "it", "senses": [{"glosses": ["of the"]}]},
    {"word": "dèi", "pos": "noun", "lang_code": "it", "hyphenations": [{"parts": ["dèi"]}],
     "senses": [{"glosses": ["plural of dio"], "tags": ["form-of", "masculine", "plural"],
                 "form_of": [{"word": "dio"}]}]},
    # ...a foreign spelling is kept, and its accent is no stress: /eˈlit/ maps with a silent e.
    {"word": "élite", "pos": "noun", "lang_code": "it", "sounds": [{"ipa": "/eˈlit/"}],
     "forms": [{"form": "élite", "tags": ["canonical"]}], "hyphenations": [{"parts": ["é‧li‧te"]}],
     "senses": [{"glosses": ["elite"], "tags": ["feminine", "invariable"]}]},
    # Garbled form_of target; a verb sense that is not an infinitive.
    {"word": "ha", "pos": "verb", "lang_code": "it", "sounds": [{"ipa": "/ˈa/"}],
     "senses": [{"glosses": ["third-person singular present indicative of avere and (obsolete) havere"],
                 "tags": ["form-of", "indicative", "present", "singular", "third-person"],
                 "form_of": [{"word": "avere and", "extra": "(obsolete) havere"}]}]},
    {"word": "possiamo", "pos": "verb", "lang_code": "it",
     "senses": [{"glosses": ["first-person plural present indicative/present subjunctive of potere"]}]},
    # A misspelling headword passes the tag to its forms, also those with their own entry.
    {"word": "scorazzare", "pos": "verb", "lang_code": "it",
     "head_templates": [{"name": "head", "args": {"1": "it", "2": "misspelling"}}],
     "forms": [_f("scorazzàndo", ["gerund"], "scorazzando")],
     "senses": [{"glosses": ["alternative spelling of scorrazzare"], "tags": ["alt-of", "alternative"]}]},
    {"word": "scorazzato", "pos": "verb", "lang_code": "it",
     "senses": [{"glosses": ["past participle of scorazzare"], "tags": ["form-of", "participle", "past"],
                 "form_of": [{"word": "scorazzare"}]}]},
    # A label qualifying one gender (f,m<l:archaic>) is not the word's.
    {"word": "stazione", "pos": "noun", "lang_code": "it",
     "head_templates": [{"name": "it-noun", "args": {"1": "f,m<l:archaic>"}}],
     "senses": [{"glosses": ["station"], "tags": ["archaic", "feminine", "masculine"]},
                {"raw_glosses": ["(archaic) position"], "glosses": ["position"],
                 "tags": ["archaic", "feminine", "masculine"]}]},
    {"word": "troia", "pos": "noun", "lang_code": "it",
     "senses": [{"glosses": ["sow"], "tags": ["feminine"]},
                {"raw_glosses": ["(derogatory, vulgar) slut"], "glosses": ["slut"],
                 "tags": ["derogatory", "feminine", "vulgar"]}]},
    {"word": "quebracho", "pos": "noun", "lang_code": "it",
     "senses": [{"glosses": ["ellipsis of legno quebracho"], "tags": ["abbreviation", "ellipsis"]}]},
    # "qu" + one vowel is no polysyllable (quà), but quassò is.
    {"word": "quassare", "pos": "verb", "lang_code": "it",
     "forms": [_f("quassò", ["historic", "indicative", "past", "singular", "third-person"])],
     "senses": [{"glosses": ["to shake"]}]},
    {"word": "quasso", "pos": "adj", "lang_code": "it", "senses": [{"glosses": ["shaken"]}]},
]

IT_VERB_FORM = "Voce verbale"
IT = [
    {"word": "viola", "lang_code": "it", "pos": "noun", "pos_title": "Sostantivo",
     "tags": ["feminine", "singular"], "hyphenations": [{"parts": ["vi", "ò", "la"]}],
     "sounds": [{"ipa": "/viˈɔ.la/"}, {"ipa": "/ˈvjɔ.la/"}],
     "senses": [{"glosses": ["pianta erbacea"]}], "forms": [{"form": "viole", "tags": ["plural"]}]},
    {"word": "viola", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM, "tags": ["form-of"],
     "hyphenations": [{"parts": ["vi", "ò", "la"]}], "sounds": [{"ipa": "/viˈɔ.la/"}],
     "senses": [{"glosses": ["terza persona singolare dell'indicativo presente di violare"],
                 "tags": ["form-of"], "form_of": [{"word": "violare"}]},
                {"glosses": ["seconda persona singolare dell'imperativo di violare"],
                 "tags": ["form-of"], "form_of": [{"word": "violare"}]}]},
    {"word": "ancora", "lang_code": "it", "pos": "adv", "pos_title": "Avverbio",
     "hyphenations": [{"parts": ["an", "có", "ra"], "sense": "avverbio"},
                      {"parts": ["àn", "co", "ra"], "sense": "sostantivo"},
                      {"parts": ["àn", "co", "ra"], "sense": "voce verbale"}],
     "senses": [{"glosses": ["un'altra volta"]}]},
    {"word": "ancora", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM, "tags": ["form-of"],
     "hyphenations": [{"parts": ["an", "có", "ra"], "sense": "avverbio"},
                      {"parts": ["àn", "co", "ra"], "sense": "voce verbale"}],
     "senses": [{"glosses": ["terza persona singolare dell'indicativo presente di ancorare"],
                 "tags": ["form-of"], "form_of": [{"word": "ancorare"}]}]},
    {"word": "belle", "lang_code": "it", "pos": "adj", "pos_title": "Aggettivo, forma flessa",
     "tags": ["feminine", "form-of", "plural"], "hyphenations": [{"parts": ["bèl", "le"]}],
     "sounds": [{"ipa": "/ˈbɛlle/"}],
     "senses": [{"glosses": ["femminile plurale di bello"], "tags": ["form-of"],
                 "form_of": [{"word": "bello"}]}]},
    {"word": "capito", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM, "tags": ["form-of"],
     "hyphenations": [{"parts": ["ca", "pì", "to"]}],
     "senses": [{"glosses": ["participio passato di capire"], "tags": ["form-of"],
                 "form_of": [{"word": "capire"}]},
                {"glosses": ["prima persona singolare dell'indicativo presente di capitare"],
                 "tags": ["form-of"], "form_of": [{"word": "capitare"}]}]},
    {"word": "città", "lang_code": "it", "pos": "noun", "pos_title": "Sostantivo",
     "senses": [{"glosses": ["centro abitato"]}]},
    {"word": "capitare", "lang_code": "it", "pos": "verb", "pos_title": "Verbo",
     "hyphenations": [{"parts": ["ca", "pi", "tà", "re"]}], "sounds": [{"ipa": "/kapiˈtare/"}],
     "senses": [{"glosses": ["accadere"]}],
     "forms": [{"form": f, "tags": t, "raw_tags": [r], "source": "Appendice:Coniugazioni/Italiano/capitare"}
               for f, t, r in [
                   ("essere", ["auxiliary"], "x"),
                   ("capitano", ["plural", "third-person", "present"], "essi/esse"),
                   ("capitò", ["singular", "third-person", "past-remote"], "lui/lei"),
                   ("è capitato", ["singular", "third-person", "past", "perfect"], "lui/lei"),
                   ("capiterebbe", ["present"], "lui/lei"),
                   ("capitino", ["present"], "che essi/che esse"),
                   ("capita", ["imperative"], "tu")]]},
    {"word": "Roma", "lang_code": "en", "pos": "name", "senses": [{"glosses": ["Rome"]}]},
    # A verb-form entry without the form-of tag or links: the gloss names the lemma (§0 applies).
    {"word": "argentino", "lang_code": "it", "pos": "adj", "pos_title": "Aggettivo",
     "hyphenations": [{"parts": ["ar", "gen", "tì", "no"]}], "senses": [{"glosses": ["d'argento"]}]},
    {"word": "argentino", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM,
     "hyphenations": [{"parts": ["ar", "gen", "tì", "no"]}],
     "senses": [{"glosses": ["terza persona plurale del congiuntivo presente di argentare"]}]},
    {"word": "tantissimo", "lang_code": "it", "pos": "adj", "pos_title": "Aggettivo",
     "tags": ["masculine", "singular"], "hyphenations": [{"parts": ["tan", "tis", "sì", "mo"]}],
     "senses": [{"glosses": ["Superlativo assoluto di tanto"]}],
     "forms": [{"form": "tantissimi", "tags": ["plural"]}]},
    {"word": "trincia", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM, "tags": ["form-of"],
     "senses": [{"glosses": ["seconda persona singolare dell'imperativo presente di trinciare"],
                 "tags": ["form-of"], "form_of": [{"word": "presente"}]}]},
    {"word": "bacia", "lang_code": "it", "pos": "verb", "pos_title": IT_VERB_FORM, "tags": ["form-of"],
     "senses": [{"glosses": ["terza persona singolare dell'indicativo presente di baciare"],
                 "tags": ["form-of"], "form_of": [{"word": "baciare"}]}]},
    {"word": "bacìa", "lang_code": "it", "pos": "adj", "pos_title": "Aggettivo, forma flessa",
     "tags": ["feminine", "form-of", "singular"], "hyphenations": [{"parts": ["ba", "cì", "a"]}],
     "senses": [{"glosses": ["femminile di bacìo"], "tags": ["form-of"], "form_of": [{"word": "bacìo"}]}]},
    {"word": "bacio", "lang_code": "it", "pos": "noun", "pos_title": "Sostantivo",
     "senses": [{"glosses": ["atto di baciare"]}]},
]


def _write(tmp_path: Path, name: str, entries: list[dict]) -> Path:
    with gzip.open(tmp_path / name, "wb") as f:
        f.write(b"\n".join(orjson.dumps(e) for e in entries) + b"\n")
    return tmp_path


@pytest.fixture(scope="module")
def en(tmp_path_factory) -> pl.DataFrame:
    return kaikki_en.extract(_write(tmp_path_factory.mktemp("en"), kaikki_en.FILE, EN))


@pytest.fixture(scope="module")
def it(tmp_path_factory) -> pl.DataFrame:
    return kaikki_it.extract(_write(tmp_path_factory.mktemp("it"), kaikki_it.FILE, IT))


def rows(df: pl.DataFrame, form: str, **eq) -> set[tuple]:
    """(lemma, feats, stress_idx, quality, evidence) of ``form``'s rows matching ``eq``."""
    sel = df.filter(pl.col("form") == form, *[pl.col(k) == v for k, v in eq.items()])
    return set(sel.select("lemma", "feats", "stress_idx", "quality", "evidence").iter_rows())


# --- helpers -----------------------------------------------------------------

@pytest.mark.parametrize("form, ipa, expected", [
    ("viola", "/viˈɔ.la/", (2, "open")),
    ("viola", "/ˈvjɔ.la/", (2, "open")),          # glide j = spelling i
    ("viola", "/ˈvi.o.la/", (1, None)),
    ("piede", "/ˈpjɛ.de/", (2, "open")),
    ("figlio", "/ˈfiʎ.ʎo/", (1, None)),           # gli + vowel: silent i
    ("gli", "/ʎi/", (2, None)),
    ("scienza", "/ˈʃɛn.t͡sa/", (3, "open")),      # sci + vowel
    ("lasciare", "/laʃˈʃa.re/", (5, None)),
    ("quando", "/ˈkwan.do/", (2, None)),          # qu = kw
    ("acqua", "/ˈak.kwa/", (0, None)),
    ("ciao", "/ˈt͡ʃa.o/", (2, None)),
    ("farmacia", "/far.maˈt͡ʃi.a/", (6, None)),
    ("aiuto", "/aˈju.to/", (2, None)),
    ("pesca", "/ˈpes.ka/", (1, "closed")),
    ("pesca", "/ˈpɛs.ka/", (1, "open")),
    ("città", "/t͡ʃitˈta/", (4, None)),
    ("perché", "/per.ˈke/", (5, "closed")),
    ("dà", "/da/", (1, None)),                    # monosyllable without a stress mark
    ("mai", "/ˈmai̯/", (1, None)),
    ("ancora", "/ˈaŋkoːra/", (0, None)),
    ("pizza", "/ˈpit.t͡sa/", (1, None)),
    ("yogurt", "/ˈjɔ.ɡurt/", (1, "open")),        # IPA glide from a consonant letter
    ("baseball", "/ˈbɛz.bol/", None),             # loanword: no consistent alignment
    ("julienne", "/ʒyˈljɛn/", None),
    ("casa", "/ka.za/", None),                    # no stress mark, two vowels
    ("sogniate", "/soɲˈɲa.te/", (5, None)),       # gn + vowel: silent i
    ("traduzione", "/tra.du(t)ˈt͡sjo.ne/", (7, "closed")),   # optional consonant
    ("performance", "/perˈfɔr.mans/", None),      # silent vowels only in the loose mode
])
def test_ipa_stress(form, ipa, expected):
    assert ipa_stress(form, ipa) == expected


@pytest.mark.parametrize("form, ipa, expected", [
    ("performance", "/perˈfɔr.mans/", (4, "open")),   # silent final e
    ("élite", "/eˈlit/", (2, None)),
    ("routine", "/ruˈtin/", (4, None)),               # ou = u
    ("governance", "/ˈɡɔ.ver.nans/", (1, "open")),
    ("viola", "/ˈvi.o.la/", (1, None)),               # strict alignments still win
    ("anopluri", "ri/", None),                        # truncated IPA: a, o, u cannot all be silent
    ("tape", "/ˈtejp/", None),
])
def test_ipa_stress_silent_vowels(form, ipa, expected):
    assert ipa_stress(form, ipa, 3) == expected


def test_hyphenation_stress():
    assert hyphenation_stress("viola", "vi‧ò‧la") == (2, "open")
    assert hyphenation_stress("casa", "càsa") == (1, None)
    assert hyphenation_stress("città", "cit‧tà") == (4, None)
    assert hyphenation_stress("casa", "ca‧sa") is None
    assert hyphenation_stress("casa", "cò‧sa") is None
    assert hyphenation_stress("élite", "é‧li‧te") is None      # the spelling's own accent
    assert hyphenation_stress("bacìa", "ba‧cì‧a") is None


def test_form_of_lemmas_and_lemma_feats():
    assert form_of_lemmas("avere and") == ["avere"]
    assert form_of_lemmas("fondare and fondere") == ["fondare", "fondere"]
    assert form_of_lemmas("uovo m") == ["uovo"]
    assert form_of_lemmas("(archaic) redurre") == ["redurre"]
    assert form_of_lemmas("italo-americano") == []
    assert [lemma_feats(f, "verb") for f in ("andare", "porre", "trarsi", "andarsene", "farcela")] \
        == ["inf+pres"] * 5
    assert lemma_feats("possiamo", "verb") is None and lemma_feats("andare", "noun") is None
    assert sense_lemma({"glosses": ["Superlativo assoluto di tanto"]}) == "tanto"
    assert sense_lemma({"glosses": ["plurale di profilattico"]}) == "profilattico"
    assert sense_lemma({"glosses": ["seconda persona singolare dell'imperativo di decimare"],
                        "form_of": [{"word": "imperativo"}]}) == "decimare"
    assert sense_lemma({"glosses": ["persona debole, priva di energia"]}) is None


@pytest.mark.parametrize("senses, expected", [
    ([["vulgar"], ["vulgar"]], {"vulgar"}),
    ([[], ["derogatory", "vulgar"]], {"derogatory", "vulgar"}),     # troia: one of two senses
    ([["vulgar"], [], []], set()),                                  # one of three
    ([["derogatory"]], set()),                                      # napoli, nessuno: derogatory alone
    ([["slur"], ["offensive"]], {"offensive"}),
    ([["mildly", "vulgar"]], set()),                                # cristo
    ([["archaic", "poetic"], ["archaic"]], {"archaic"}),            # the rest: every sense
])
def test_entry_tags(senses, expected):
    assert entry_tags([map_tags(s) for s in senses]) == expected


def test_feats_and_tags():
    assert verb_feats({"first-person", "indicative", "present", "singular"}) == "ind+pres+1+s"
    assert verb_feats({"historic", "past", "third-person", "plural"}) == "ind+past+3+p"
    assert verb_feats({"gerund"}) == "ger+pres"
    assert verb_feats({"participle", "past", "feminine", "plural"}) == "part+past+p+f"
    assert verb_feats({"imperative", "second-person", "singular"}) == "impr+pres+2+s"
    assert verb_feats({"conditional", "first-person", "plural"}) == "cond+pres+1+p"
    assert map_tags(["abbreviation", "apocopic"]) == set()
    assert map_tags(["abbreviation", "ellipsis"]) == set()
    assert map_tags(["misspelling", "alt-of", "vulgar"]) == {"misspelling", "vulgar"}
    assert compound_reading("compound of the infinitive dare with me (the conjunctive "
                            "variant of mi) and lo") == ("dare", "inf+pres+me+lo")
    assert compound_reading("compound of portando, the gerund of portare, with glie and lo") \
        == ("portare", "ger+pres+glie+lo")
    assert gloss_tags("terza persona singolare dell'indicativo presente di violare") == \
        {"third-person", "singular", "indicative", "present"}
    assert verb_feats(gloss_tags("1ª persona singolare del presente semplice indicativo di venire")) \
        == "ind+pres+1+s"
    assert verb_feats(gloss_tags("participio passato femminile plurale di capire")) == "part+past+p+f"
    src = "Appendice:Coniugazioni/Italiano/x"
    assert verb_feats(conj_tags({"tags": ["present"], "raw_tags": ["lui/lei"], "source": src})) \
        == "cond+pres+3+s"
    assert verb_feats(conj_tags({"tags": ["present"], "raw_tags": ["che essi/che esse"]})) \
        == "sub+pres+3+p"
    assert verb_feats(conj_tags({"tags": ["imperative"], "raw_tags": ["tu"]})) == "impr+pres+2+s"


# --- kaikki_en ---------------------------------------------------------------

def test_en_schema_and_order(en):
    assert en.schema == pl.Schema(schema.FORMS)
    keys = ["form", "lemma", "pos", "feats", "evidence", "stress_idx", "quality"]
    assert en.select(keys).equals(en.select(keys).sort(keys, nulls_last=True))
    assert set(en["source"]) == {"kaikki_en"}
    assert not en["form"].str.contains(r"[ '\-]").any()
    assert "non capitare" not in set(en["form"]) and "capitanio" not in set(en["form"])
    assert {"no-table-tags", "avere", "it-conj"}.isdisjoint(set(en["form"]))


def test_en_capitare_table(en):
    assert rows(en, "capito", evidence="table") == {("capitare", "ind+pres+1+s", 1, None, "table")}
    assert rows(en, "capitò") == {("capitare", "ind+past+3+s", 5, "open", "table")}
    assert rows(en, "capitare", evidence="table") == {("capitare", "inf+pres", 5, None, "table")}
    assert ("capitare", "ger+pres", 5, None, "table") in rows(en, "capitando")
    assert rows(en, "capitato") == {("capitare", "part+past+s+m", 5, None, "table")}


def test_en_capitano_homograph(en):
    assert rows(en, "capitano") == {
        ("capitano", None, 5, None, "hyphenation"), ("capitano", None, 5, None, "ipa"),
        ("capitare", "ind+pres+3+p", 1, None, "hyphenation"),
        ("capitare", "ind+pres+3+p", 1, None, "ipa"),
        ("capitare", "ind+pres+3+p", 1, None, "table"),
    }
    assert rows(en, "capitani") == {("capitano", "m+p", None, None, "none")}


def test_en_viola(en):
    assert rows(en, "viola", pos="noun") == {
        ("viola", None, 2, "open", "hyphenation"), ("viola", None, 2, "open", "ipa")}
    assert rows(en, "viola", pos="verb") == {
        ("violare", "ind+pres+3+s", 1, None, "hyphenation"),
        ("violare", "ind+pres+3+s", 1, None, "ipa")}


def test_en_orthographic_spellings(en):
    assert rows(en, "città") == {("città", None, 4, None, "ortho")}
    # The Lombard /perˈkɛ/ (with a note) is ignored: quality stays closed.
    assert rows(en, "perché") == {("perché", None, 5, "closed", "hyphenation"),
                                  ("perché", None, 5, "closed", "ipa")}
    assert rows(en, "diede") == {("dare", "ind+past+3+s", 2, "open", "table")}
    # Monosyllables: the known accented spelling wins over the stripped link (dà is not da)...
    assert ("dare", "ind+pres+3+s", 1, None, "table") in rows(en, "dà")
    assert ("dare", "ind+pres+1+s", 1, "open", "table") in rows(en, "dò")
    assert rows(en, "da") == {("da", None, None, None, "none")}
    # ...but a misspelling headword is not a known spelling: fà -> fa.
    assert ("fare", "ind+pres+3+s", 1, None, "table") in rows(en, "fa")
    assert rows(en, "fà") == {("fà", None, 1, None, "ortho")}
    assert en.filter(pl.col("form") == "fà")["tags"].to_list() == [["misspelling"]]


def test_en_tags_and_compounds(en):
    assert rows(en, "dimmelo") == {("dire", "impr+pres+2+s+me+lo", 1, None, "hyphenation"),
                                   ("dire", "impr+pres+2+s+me+lo", 1, None, "ipa")}
    # Head-level tlb tag counts even though one sense is not vulgar.
    assert en.filter(pl.col("form") == "cazzo")["tags"].to_list() == [["vulgar"]]
    roma = en.filter(pl.col("form") == "roma")
    assert roma["pos"].to_list() == ["name"] and roma["tags"].to_list() == [["proper"]]
    assert roma["stress_idx"].to_list() == [1]
    assert en.filter(pl.col("form") == "stazione")["tags"].to_list() == [[]]
    assert en.filter(pl.col("form") == "troia")["tags"].to_list() == [["derogatory", "vulgar"]]
    assert en.filter(pl.col("form") == "quebracho")["tags"].to_list() == [[]]


def test_en_stress_marked_spellings(en):
    """§4: abéto and dèi are respelt; élite keeps its accent, which is no stress."""
    forms = set(en["form"])
    assert {"abéto", "abéti", "dèi"}.isdisjoint(forms) and "abeti" not in forms
    assert rows(en, "abeto") == {("abeto", None, 2, "closed", "ipa")}
    assert ("dio", "m+p", 1, "open", "table") in rows(en, "dei")
    assert rows(en, "élite") == {("élite", None, 2, None, "ipa")}
    assert rows(en, "quassò") == {("quassare", "ind+past+3+s", 5, "open", "table")}


def test_en_lemmas_and_misspellings(en):
    assert rows(en, "ha") == {("avere", "ind+pres+3+s", 1, None, "ipa")}
    assert rows(en, "possiamo") == {("possiamo", None, None, None, "none")}
    for form in ("scorazzando", "scorazzato"):
        assert en.filter(pl.col("form") == form)["tags"].to_list() == [["misspelling"]]


# --- kaikki_it ---------------------------------------------------------------

def test_it_schema(it):
    assert it.schema == pl.Schema(schema.FORMS)
    assert set(it["source"]) == {"kaikki_it"}
    assert "roma" not in set(it["form"])               # lang_code "en" line skipped
    assert "è capitato" not in set(it["form"]) and "essere" not in set(it["form"])


def test_it_page_stress_not_given_to_verb_forms(it):
    """§0: viola has one {{-sill-}} (viòla); the verb form of violare must not get it."""
    assert rows(it, "viola", pos="noun") == {("viola", None, 2, None, "hyphenation"),
                                            ("viola", None, 2, "open", "ipa")}
    assert rows(it, "viola", pos="verb") == {("violare", "ind+pres+3+s", None, None, "none"),
                                            ("violare", "impr+pres+2+s", None, None, "none")}


def test_it_labelled_and_formof_only_pages(it):
    assert rows(it, "ancora", pos="adv") == {("ancora", None, 3, None, "hyphenation")}
    # A hyphenation labelled "voce verbale" is the verb form's own.
    assert rows(it, "ancora", pos="verb") == {("ancorare", "ind+pres+3+s", 0, None, "hyphenation")}
    # A page with only a form-of entry keeps its stress...
    assert rows(it, "belle") == {("bello", "pos+f+p", 1, None, "hyphenation"),
                                 ("bello", "pos+f+p", 1, "open", "ipa")}
    # ...unless the entry is a form of several lemmas (capìto / càpito).
    assert {r[2] for r in rows(it, "capito")} == {None}
    assert rows(it, "città") == {("città", None, 4, None, "ortho")}


def test_it_conjugation_appendix(it):
    assert rows(it, "capitano") == {("capitare", "ind+pres+3+p", None, None, "none")}
    assert rows(it, "capitò") == {("capitare", "ind+past+3+s", 5, "open", "ortho")}
    assert rows(it, "capiterebbe") == {("capitare", "cond+pres+3+s", None, None, "none")}
    assert rows(it, "capitino") == {("capitare", "sub+pres+3+p", None, None, "none")}
    assert rows(it, "capita") == {("capitare", "impr+pres+2+s", None, None, "none")}
    assert rows(it, "viole") == {("viola", "f+p", None, None, "none")}


def test_it_gloss_form_of(it):
    # No form-of tag or link, but the gloss is a verb form's: §0 withholds the page stress.
    assert rows(it, "argentino", pos="verb") == {("argentare", "sub+pres+3+p", None, None, "none")}
    assert rows(it, "tantissimo") == {("tanto", "sup+m+s", 7, None, "hyphenation")}
    assert rows(it, "tantissimi") == {("tanto", "sup+m+p", None, None, "none")}
    assert rows(it, "trincia") == {("trinciare", "impr+pres+2+s", None, None, "none")}
    # bacìa (of the adjective bacìo) is respelt; its accent is the stress.
    assert "bacìa" not in set(it["form"])
    assert ("bacio", "pos+f+s", 3, None, "table") in rows(it, "bacia")
