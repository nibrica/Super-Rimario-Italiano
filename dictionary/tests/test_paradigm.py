"""stress/paradigm.py on tiny hand-made frames."""

import polars as pl
import pytest

from rimario_build import config, schema, text
from rimario_build.stress import paradigm


def _forms(*rows: tuple[str, str, str, str | None]) -> pl.DataFrame:
    """FORMS rows (form, lemma, pos, feats) without stress."""
    return schema.conform(pl.DataFrame(
        [(f, l, p, ft, None, None, "none", [], "morphit") for f, l, p, ft in rows],
        schema=schema.FORMS, orient="row"), schema.FORMS)


def _readings(*rows: tuple[str, str, str, str]) -> pl.DataFrame:
    """Attested READINGS from stress-marked spellings: (marked, lemma, pos)."""
    out = []
    for marked, lemma, pos in rows:
        form, idx, quality = text.resolve_spelling(marked)
        out.append((form, idx, quality, lemma, pos, "attested", 1.0, "table", ["kaikki_en"]))
    return pl.DataFrame(out, schema=schema.READINGS, orient="row")


def _run(forms, readings, extra=()) -> dict[tuple[str, str, str], set[str]]:
    spellings = pl.concat([forms.select("form"), pl.DataFrame({"form": list(extra)}, schema={"form": pl.String})])
    out = paradigm.propagate(forms, readings, spellings)
    assert out.columns == list(schema.READINGS)
    assert set(out["tier"]) <= {"propagated"}
    res: dict[tuple[str, str, str], set[str]] = {}
    for f, i, q, l, p in out.select("form", "stress_idx", "quality", "lemma", "pos").iter_rows():
        res.setdefault((f, l, p), set()).add(text.mark_stress(f, i, q))
    return res


def test_capitano_homograph():
    forms = _forms(
        ("capitano", "capitano", "noun", "m+s"),
        ("capitano", "capitare", "verb", "ind+pres+3+p"),
        ("capito", "capitare", "verb", "ind+pres+1+s"),
        ("capiti", "capitare", "verb", "sub+pres+2+s"),
        ("capitare", "capitare", "verb", "inf+pres"),
        ("capitavano", "capitare", "verb", "ind+impf+3+p"),
    )
    res = _run(forms, _readings(("capitàno", "capitano", "noun"), ("càpito", "capitare", "verb")))
    assert res[("capitano", "capitare", "verb")] == {"càpitano"}
    assert res[("capiti", "capitare", "verb")] == {"càpiti"}
    assert res[("capitare", "capitare", "verb")] == {"capitàre"}
    assert res[("capitavano", "capitare", "verb")] == {"capitàvano"}
    assert ("capitano", "capitano", "noun") not in res      # already attested


def test_finire_isc_and_endings():
    forms = _forms(
        ("finisco", "finire", "verb", "ind+pres+1+s"),
        ("finisce", "finire", "verb", "ind+pres+3+s"),
        ("finiscono", "finire", "verb", "ind+pres+3+p"),
        ("finiamo", "finire", "verb", "ind+pres+1+p"),
        ("finii", "finire", "verb", "ind+past+1+s"),
        ("finito", "finire", "verb", "part+past+s+m"),
        ("finirebbero", "finire", "verb", "cond+pres+3+p"),
        ("finivate", "finire", "verb", "ind+impf+2+p"),
    )
    res = _run(forms, _readings(("finìsco", "finire", "verb")))
    assert res[("finisce", "finire", "verb")] == {"finìsce"}
    assert res[("finiscono", "finire", "verb")] == {"finìscono"}
    assert res[("finiamo", "finire", "verb")] == {"finiàmo"}
    assert res[("finii", "finire", "verb")] == {"finìi"}
    assert res[("finito", "finire", "verb")] == {"finìto"}
    assert res[("finirebbero", "finire", "verb")] == {"finirèbbero"}
    assert res[("finivate", "finire", "verb")] == {"finivàte"}


def test_stem_changes_and_quality():
    forms = _forms(
        ("tengo", "tenere", "verb", "ind+pres+1+s"),
        ("tieni", "tenere", "verb", "ind+pres+2+s"),
        ("tengono", "tenere", "verb", "ind+pres+3+p"),
        ("tenevo", "tenere", "verb", "ind+impf+1+s"),
        ("assorbisco", "assorbire", "verb", "ind+pres+1+s"),
        ("assorbe", "assorbire", "verb", "ind+pres+3+s"),
    )
    res = _run(forms, _readings(("tèngo", "tenere", "verb"), ("assorbìsco", "assorbire", "verb")))
    assert res[("tieni", "tenere", "verb")] == {"tièni"}
    assert res[("tengono", "tenere", "verb")] == {"tèngono"}
    assert res[("tenevo", "tenere", "verb")] == {"tenévo"}    # quality from the ending
    assert res[("assorbe", "assorbire", "verb")] == {"assòrbe"}


def test_enclitics_and_attestation_filter():
    forms = _forms(
        ("di'", "dire", "verb", "impr+pres+2+s"),
        ("portando", "portare", "verb", "ger+pres"),
        ("portare", "portare", "verb", "inf+pres"),
        ("guardate", "guardare", "verb", "impr+pres+2+p"),
        ("guardatevi", "guardare", "verb", "impr+pres+2+p+vi"),
        ("porre", "porre", "verb", "inf+pres"),
    )
    readings = _readings(("portàndo", "portare", "verb"), ("portàre", "portare", "verb"), ("pórre", "porre", "verb"))
    res = _run(forms, readings, extra=("dimmelo", "portandoglielo", "portarlo", "porlo"))
    assert res[("dimmelo", "dire", "verb")] == {"dìmmelo"}
    assert res[("portandoglielo", "portare", "verb")] == {"portàndoglielo"}
    assert res[("guardatevi", "guardare", "verb")] == {"guardàtevi"}
    assert res[("portarlo", "portare", "verb")] == {"portàrlo"}
    assert res[("porlo", "porre", "verb")] == {"pórlo"}
    # Valid spellings that no lexicon or corpus has are never generated.
    assert not any(f in ("portarmela", "dammi", "guardatemi") for f, _, _ in res)


def test_apocopated_infinitive_host():
    """portar (Morph-it) is a host as it stands: portàrlo, never porta+mi with its stress (portàmi)."""
    forms = _forms(("portare", "portare", "verb", "inf+pres"), ("portar", "portare", "verb", "inf+pres"),
                   ("porto", "portare", "verb", "ind+pres+1+s"), ("porta", "portare", "verb", "impr+pres+2+s"))
    readings = _readings(("pòrto", "portare", "verb"), ("portàre", "portare", "verb"))
    res = _run(forms, readings, extra=("portami", "portarlo"))
    assert res[("portar", "portare", "verb")] == {"portàr"}
    assert res[("portami", "portare", "verb")] == {"pòrtami"}
    assert res[("portarlo", "portare", "verb")] == {"portàrlo"}


def test_participle_with_unmarked_clitic():
    """kaikki lists tenutasi as plain part+past: stressed like tenuta, not on the clitic."""
    forms = _forms(("tenuta", "tenere", "verb", "part+past+s+f"), ("tenutasi", "tenere", "verb", "part+past+s+f"),
                   ("frusta", "frustare", "verb", "part+past+s+f"),
                   ("frustati", "frustare", "verb", "part+past+p+m"))
    res = _run(forms, _readings())
    assert res[("tenutasi", "tenere", "verb")] == {"tenùtasi"}
    assert res[("frustati", "frustare", "verb")] == {"frustàti"}     # regular, not frùsta+ti


def test_no_second_stress_for_a_slot_attested_under_another_lemma():
    forms = _forms(("adempii", "adempire", "verb", "ind+past+1+s"), ("adempii", "adempiere", "verb", "ind+past+1+s"),
                   ("chiamati", "chiamarsi", "verb", "impr+pres+2+s"),
                   ("chiamati", "chiamare", "verb", "part+past+p+m"))
    res = _run(forms, _readings(("adempìi", "adempire", "verb"), ("chiàmati", "chiamarsi", "verb")))
    assert ("adempii", "adempiere", "verb") not in res              # adèmpii from the strong-past rule
    assert res[("chiamati", "chiamare", "verb")] == {"chiamàti"}    # another slot: a real homograph


def test_irregular_verb_endings():
    forms = _forms(("solito", "solere", "verb", "part+past+s+m"), ("guaito", "guaire", "verb", "part+past+s+m"),
                   ("guaivano", "guaire", "verb", "ind+impf+3+p"), ("guaii", "guaire", "verb", "ind+past+1+s"),
                   ("guairai", "guaire", "verb", "ind+fut+2+s"),
                   ("finisco", "finire", "verb", "ind+pres+1+s"), ("finiscon", "finire", "verb", "ind+pres+3+p"),
                   ("compisco", "compiere", "verb", "ind+pres+1+s"), ("compisce", "compiere", "verb", "ind+pres+3+s"))
    res = _run(forms, _readings(("finìsco", "finire", "verb"), ("compìsco", "compiere", "verb")))
    assert res[("solito", "solere", "verb")] == {"sòlito"}         # config.PARADIGM_PARTICIPLE_RUN
    assert res[("guaito", "guaire", "verb")] == {"guaìto"}
    assert res[("guaivano", "guaire", "verb")] == {"guaìvano"}
    assert res[("guaii", "guaire", "verb")] == {"guaìi"}
    assert res[("guairai", "guaire", "verb")] == {"guairài"}        # not the stem run
    assert res[("finiscon", "finire", "verb")] == {"finìscon"}
    assert res[("compisce", "compiere", "verb")] == {"compìsce"}


def test_no_stress_against_a_written_final_accent():
    res = _run(_forms(("parlò", "parlare", "verb", "ind+past+3+s")), _readings())
    assert ("parlò", "parlare", "verb") not in res                  # ending() reads pàrlo


def test_enclitic_skips_lexicon_words_of_another_kind():
    forms = _forms(("federa", "federare", "verb", "impr+pres+2+s"),
                   ("federati", "federare", "verb", "part+past+p+m"))
    res = _run(forms, _readings(("fèdero", "federare", "verb")))
    assert res[("federati", "federare", "verb")] == {"federàti"}     # the participle, not fèdera+ti


def test_nominal_inflection():
    forms = _forms(
        ("uomo", "uomo", "noun", "m+s"), ("uomini", "uomo", "noun", "m+p"),
        ("amico", "amico", "noun", "m+s"), ("amici", "amico", "noun", "m+p"), ("amiche", "amico", "noun", "f+p"),
        ("bello", "bello", "adj", "pos+m+s"), ("belle", "bello", "adj", "pos+f+p"),
        ("bellissime", "bello", "adj", "sup+f+p"),
        ("orletto", "orlo", "noun", None), ("orlo", "orlo", "noun", "m+s"),
        ("energie", "energia", "noun", "f+p"), ("zii", "zio", "noun", "m+p"), ("eroi", "eroe", "noun", "m+p"),
        ("citta", "città", "noun", "f+p"),
    )
    res = _run(forms, _readings(("uòmo", "uomo", "noun"), ("amìco", "amico", "noun"),
                                ("bèllo", "bello", "adj"), ("órlo", "orlo", "noun"), ("energìa", "energia", "noun"),
                                ("zìo", "zio", "noun"), ("eròe", "eroe", "noun"), ("città", "città", "noun")))
    assert res[("uomini", "uomo", "noun")] == {"uòmini"}
    assert res[("amici", "amico", "noun")] == {"amìci"}
    assert res[("amiche", "amico", "noun")] == {"amìche"}
    assert res[("belle", "bello", "adj")] == {"bèlle"}
    assert res[("bellissime", "bello", "adj")] == {"bellìssime"}
    assert ("orletto", "orlo", "noun") not in res               # derived, not an inflection
    assert res[("energie", "energia", "noun")] == {"energìe"}   # stressed hiatus: last vowel changes
    assert res[("zii", "zio", "noun")] == {"zìi"}
    assert res[("eroi", "eroe", "noun")] == {"eròi"}
    assert ("citta", "città", "noun") not in res                # oxytone lemma


@pytest.fixture
def low_support(monkeypatch):
    monkeypatch.setattr(config, "PARADIGM_SUFFIX_MIN_SUPPORT", 1)


def test_suffixes(low_support):
    forms = _forms(
        ("lentamente", "lentamente", "adv", None), ("stazione", "stazione", "noun", "f+s"),
        ("vicino", "vicino", "adj", "pos+m+s"),
    )
    readings = _readings(
        ("rapidaménte", "rapidamente", "adv"), ("nazióne", "nazione", "noun"),
        ("cammìno", "cammino", "noun"), ("àsino", "asino", "noun"),   # -ìno: 50% precision, unused
    )
    res = _run(forms, readings)
    assert res[("lentamente", "lentamente", "adv")] == {"lentaménte"}
    assert res[("stazione", "stazione", "noun")] == {"stazióne"}
    assert ("vicino", "vicino", "adj") not in res
    prec = paradigm.suffix_precision(readings).filter(pl.col("suffix") == "ìno")
    assert prec["precision"][0] == 0.5


def test_suffix_variants_gated_separately(low_support):
    """-óso is reliable, -ósi is not (diàgnosi): only the variant that passes is used."""
    forms = _forms(("geloso", "geloso", "adj", "pos+m+s"), ("tubercolosi", "tubercolosi", "noun", "f+s"))
    res = _run(forms, _readings(("famóso", "famoso", "adj"), ("diàgnosi", "diagnosi", "noun")))
    assert res[("geloso", "geloso", "adj")] == {"gelóso"}
    assert ("tubercolosi", "tubercolosi", "noun") not in res


def test_suffix_skips_spellings_with_a_reading(low_support, monkeypatch):
    """sàbato (noun) is attested; the name Sabato must not get -àto from the suffix rule."""
    monkeypatch.setattr(config, "PARADIGM_SUFFIX_MIN_PRECISION", 0.5)    # sàbato itself is a miss
    forms = _forms(("sabato", "sabato", "noun", "m+s"), ("sabato", "sabato", "name", None),
                   ("mandato", "mandato", "noun", "m+s"))
    res = _run(forms, _readings(("sàbato", "sabato", "noun"), ("prelàto", "prelato", "noun")))
    assert ("sabato", "sabato", "name") not in res
    assert res[("mandato", "mandato", "noun")] == {"mandàto"}


def test_no_unwritten_final_stress():
    """Morph-it's devi (deviare, for devii) would map devìo onto the final i: dropped."""
    forms = _forms(("devio", "deviare", "verb", "ind+pres+1+s"), ("devi", "deviare", "verb", "ind+pres+2+s"),
                   ("devia", "deviare", "verb", "ind+pres+3+s"))
    res = _run(forms, _readings(("devìo", "deviare", "verb")))
    assert res[("devia", "deviare", "verb")] == {"devìa"}
    assert ("devi", "deviare", "verb") not in res


def test_single_vowel():
    res = _run(_forms(("del", "del", "prep", "s"), ("sui", "su", "prep", "p")), _readings())
    assert res == {("del", "del", "prep"): {"dèl"}}           # sùi has two vowels: left to the model


def test_spelling_helpers():
    assert paradigm.ending("trasformavan", "ind+impf+3+p", "trasformare") == 8    # apocope
    assert paradigm.ending("presi", "ind+past+1+s", "prendere") == 2               # strong past
    assert paradigm.ending("prendere", "inf+pres", "prendere") is None            # -ere: unknown
    assert paradigm.rhizotonic("coordino", 2, "coordini") == 2
    assert paradigm.rhizotonic("muoio", 2, "muori") == 2
    assert paradigm.host_stem("fa'", "impr+pres+2+s") == ("fa", True)
    assert paradigm.host_stem("portare", "inf+pres") == ("portar", False)
    assert paradigm.host_stem("portar", "inf+pres") == ("portar", False)
    assert paradigm.nominal("teorie", "teoria", 3) == 3
    assert paradigm.nominal("teorici", "teoria", 3) is None
    assert paradigm.suffix_variants("ìstico|a|i|he") == ["ìstico", "ìstica", "ìstici", "ìstiche"]


def test_deterministic():
    forms = _forms(("capito", "capitare", "verb", "ind+pres+1+s"), ("capita", "capitare", "verb", "ind+pres+3+s"),
                   ("capitate", "capitare", "verb", "ind+pres+2+p"))
    readings = _readings(("càpito", "capitare", "verb"))
    a = paradigm.propagate(forms, readings, forms.select("form"))
    b = paradigm.propagate(forms.reverse(), readings, forms.select("form").reverse())
    assert a.equals(b)
