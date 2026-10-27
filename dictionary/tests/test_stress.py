"""stress/vote.py and stress/model.py on tiny hand-made tables."""

import random

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from rimario_build import config, schema, text
from rimario_build.stress import model, vote


def forms(*rows: tuple) -> pl.DataFrame:
    """FORMS rows from (form, lemma, pos, stress_idx, quality, evidence, source)."""
    cols = ["form", "lemma", "pos", "stress_idx", "quality", "evidence", "source"]
    df = pl.DataFrame([dict(zip(cols, r)) for r in rows], schema={c: schema.FORMS[c] for c in cols})
    return schema.conform(
        df.with_columns(feats=pl.lit(None, pl.String), tags=pl.lit([], pl.List(pl.String))), schema.FORMS)


def readings_of(out: dict, form: str) -> list[tuple]:
    return out["readings"].filter(pl.col("form") == form).select(
        "stress_idx", "quality", "lemma", "pos", "evidence", "sources").rows()


# --- vote --------------------------------------------------------------------

def test_source_priority_and_conflict():
    out = vote.vote(forms(
        ("salubre", "salubre", "adj", 3, None, "hyphenation", "kaikki_en"),
        ("salubre", "salubre", "adj", 1, None, "hyphenation", "kaikki_it"),
    ))
    assert readings_of(out, "salubre") == [(3, None, "salubre", "adj", "hyphenation", ["kaikki_en"])]
    assert out["conflicts"].rows() == [("salubre", "salubre", "adj", "kaikki_en:salùbre kaikki_it:sàlubre")]
    assert out["readings"].schema == pl.Schema(schema.READINGS)
    assert out["conflicts"].schema == pl.Schema(schema.CONFLICTS)


def test_evidence_priority_inside_a_source():
    out = vote.vote(forms(
        ("convellere", "convellere", "verb", 6, "closed", "table", "kaikki_en"),
        ("convellere", "convellere", "verb", 3, "open", "ipa", "kaikki_en"),
        ("convellere", "convellere", "verb", 6, None, "hyphenation", "kaikki_it"),
    ))
    assert readings_of(out, "convellere") == [
        (6, "closed", "convellere", "verb", "table", ["kaikki_en", "kaikki_it"])]
    assert out["conflicts"].is_empty()   # a weaker row of the same source is not a vote


def test_homographs_kept_and_multi_lemma_disagreement_not_a_conflict():
    out = vote.vote(forms(
        ("capitano", "capitano", "noun", 5, None, "hyphenation", "kaikki_en"),
        ("capitano", "capitare", "verb", 1, None, "table", "kaikki_en"),
        ("capitano", "capitare", "verb", 5, None, "sill", "kaikki_it"),   # page-level syllabification
    ))
    assert readings_of(out, "capitano") == [
        (5, None, "capitano", "noun", "hyphenation", ["kaikki_en"]),
        (1, None, "capitare", "verb", "table", ["kaikki_en"]),
    ]
    assert out["conflicts"].is_empty()


def test_quality():
    out = vote.vote(forms(
        # sources disagree on quality: kaikki_en wins
        ("pesca", "pesca", "noun", 1, "open", "ipa", "kaikki_en"),
        ("pesca", "pesca", "noun", 1, "closed", "hyphenation", "kaikki_it"),
        # quality from a weaker row that agrees on the index
        ("bene", "bene", "adv", 1, None, "hyphenation", "kaikki_en"),
        ("bene", "bene", "adv", 1, "open", "ipa", "kaikki_en"),
        # the deciding source lists both: unknown
        ("prenderebbe", "prendere", "verb", 7, "open", "table", "kaikki_en"),
        ("prenderebbe", "prendere", "verb", 7, "closed", "table", "kaikki_en"),
    ))
    assert readings_of(out, "pesca")[0][:2] == (1, "open")
    assert readings_of(out, "bene")[0][:2] == (1, "open")
    assert readings_of(out, "bene")[0][4] == "hyphenation"
    assert readings_of(out, "prenderebbe") == [(7, None, "prendere", "verb", "table", ["kaikki_en"])]
    assert out["conflicts"].is_empty()


def test_variants_of_the_winning_source_are_kept():
    out = vote.vote(forms(
        ("edile", "edile", "adj", 0, "open", "hyphenation", "kaikki_en"),
        ("edile", "edile", "adj", 2, None, "hyphenation", "kaikki_en"),
    ))
    assert [r[0] for r in readings_of(out, "edile")] == [0, 2]
    assert out["conflicts"].is_empty()


def test_variant_with_less_support_is_dropped():
    out = vote.vote(forms(   # a stray conjugation-table cell: credére
        ("credere", "credere", "verb", 2, "closed", "table", "kaikki_en"),
        ("credere", "credere", "verb", 4, "closed", "table", "kaikki_en"),
        ("credere", "credere", "verb", 2, None, "hyphenation", "kaikki_en"),
        ("credere", "credere", "verb", 2, "closed", "ipa", "kaikki_en"),
        ("credere", "credere", "verb", 2, None, "hyphenation", "kaikki_it"),
        # 2 rows against 1, at a lower rank: still dropped
        ("caduco", "caduco", "adj", 3, None, "hyphenation", "kaikki_en"),
        ("caduco", "caduco", "adj", 1, None, "hyphenation", "kaikki_en"),
        ("caduco", "caduco", "adj", 3, None, "sill", "kaikki_it"),
    ))
    assert [r[0] for r in readings_of(out, "credere")] == [2]
    assert [r[0] for r in readings_of(out, "caduco")] == [3]
    assert out["conflicts"].filter(pl.col("form") == "credere")["readings"].to_list() == [
        "kaikki_en:crédere kaikki_en:credére kaikki_it:crèdere"]


def test_impossible_stress_is_dropped():
    out = vote.vote(forms(
        ("congelato", "congelato", "adj", 8, None, "ipa", "kaikki_it"),         # unaccented final vowel
        ("tranquilla", "tranquillo", "adj", 5, None, "hyphenation", "kaikki_it"),  # u of qu
        ("perniciosità", "perniciosità", "noun", 7, None, "ipa", "kaikki_en"),   # not the written accent
        ("perniciosità", "perniciosità", "noun", 11, None, "hyphenation", "kaikki_en"),
        ("menu", "menu", "noun", 3, None, "ipa", "kaikki_en"),                   # final -u: a loanword
        ("blu", "blu", "adj", 2, None, "ipa", "kaikki_en"),                     # monosyllable
        ("qui", "qui", "adv", 2, None, "ipa", "kaikki_en"),
    ))
    got = out["readings"].select("form", "stress_idx").rows()
    assert got == [("blu", 2), ("menu", 3), ("perniciosità", 11), ("qui", 2)]


def test_possible():
    cases = [("congelato", 8, False), ("congelato", 6, True), ("portar", 4, True), ("tranquilla", 5, False),
             ("tranquilla", 6, True), ("città", 4, True), ("città", 1, False), ("menu", 3, True),
             ("qui", 2, True), ("zio", 2, True), ("quota", 2, True)]
    df = pl.DataFrame({"form": [c[0] for c in cases], "idx": [c[1] for c in cases]})
    assert df.select(vote.possible(pl.col("form"), pl.col("idx"))).to_series().to_list() == [c[2] for c in cases]


def test_kaikki_it_only_reading_contradicting_kaikki_en_is_a_conflict():
    out = vote.vote(forms(
        # same (form, lemma), different POS
        ("novantotto", "novantotto", "num", 6, None, "hyphenation", "kaikki_en"),
        ("novantotto", "novantotto", "adj", 3, None, "hyphenation", "kaikki_it"),
        # kaikki_en lists the plural unstressed: the lemma's stress counts
        ("brivido", "brivido", "noun", 2, None, "hyphenation", "kaikki_en"),
        ("brividi", "brivido", "noun", None, None, "none", "kaikki_en"),
        ("brividi", "brivido", "noun", 4, None, "hyphenation", "kaikki_it"),
        # agreeing, or under another lemma: kept
        ("cinque", "cinque", "num", 2, None, "ipa", "kaikki_en"),
        ("cinque", "cinque", "noun", 2, None, "hyphenation", "kaikki_it"),
        ("capitano", "capitano", "noun", 5, None, "hyphenation", "kaikki_en"),
        ("capitano", "capitare", "verb", 1, None, "hyphenation", "kaikki_it"),
    ))
    got = out["readings"].select("form", "pos", "stress_idx").rows()
    assert got == [("brivido", "noun", 2), ("capitano", "noun", 5), ("capitano", "verb", 1),
                   ("cinque", "noun", 2), ("cinque", "num", 2), ("novantotto", "num", 6)]
    assert out["conflicts"].rows() == [
        ("brividi", "brivido", "noun", "kaikki_en:brìvidi kaikki_it:brivìdi"),
        ("novantotto", "novantotto", "adj", "kaikki_en:novantòtto kaikki_it:novàntotto"),
    ]


def test_ortho_and_unstressed():
    out = vote.vote(forms(
        ("città", "città", "noun", 4, None, "ortho", "morphit"),
        ("città", "città", "noun", 4, None, "hyphenation", "kaikki_en"),
        ("perché", "perché", "conj", 5, "closed", "ortho", "morphit"),
        ("andare", "andare", "verb", None, None, "none", "morphit"),
        ("tavolo", "tavolo", "noun", None, None, "none", "kaikki_it"),
    ))
    assert readings_of(out, "città") == [(4, None, "città", "noun", "ortho", ["kaikki_en", "morphit"])]
    assert readings_of(out, "perché") == [(5, "closed", "perché", "conj", "ortho", ["morphit"])]
    assert out["readings"]["form"].to_list() == ["città", "perché"]
    assert set(out["readings"]["tier"]) == {"attested"}
    assert set(out["readings"]["confidence"]) == {1.0}


def test_vote_is_order_independent():
    df = forms(
        ("viola", "viola", "noun", 2, "open", "hyphenation", "kaikki_en"),
        ("viola", "violare", "verb", 1, None, "table", "kaikki_en"),
        ("viola", "viola", "noun", 2, None, "hyphenation", "kaikki_it"),
        ("salubre", "salubre", "adj", 3, None, "hyphenation", "kaikki_en"),
        ("salubre", "salubre", "adj", 1, None, "hyphenation", "kaikki_it"),
        ("novantotto", "novantotto", "num", 6, None, "hyphenation", "kaikki_en"),
        ("novantotto", "novantotto", "adj", 3, None, "hyphenation", "kaikki_it"),
    )
    a, b = vote.vote(df), vote.vote(df.reverse())
    for key in ("readings", "conflicts"):
        assert_frame_equal(a[key], b[key])


# --- model -------------------------------------------------------------------

def synthetic_readings(n: int, seed: int = 0) -> pl.DataFrame:
    """Pseudo-words: paroxytone, except "-ico"/"-ica" words which are proparoxytone."""
    rng = random.Random(seed)
    rows = set()
    while len(rows) < n:
        stem = "".join(rng.choice("bcdfglmnprstv") + rng.choice("aeiou") for _ in range(rng.randint(1, 3)))
        end = rng.choice(["ico", "ica", "ato", "ata", "ore", "ino"])
        form = stem + rng.choice("cdlmnrt") + end
        vowels = text.vowel_positions(form)
        rows.add((form, vowels[-3] if end.startswith("ic") else vowels[-2]))
    df = pl.DataFrame(sorted(rows), schema=["form", "stress_idx"], orient="row")
    return schema.conform(df.with_columns(
        stress_idx=pl.col("stress_idx").cast(pl.Int16), quality=pl.lit(None, pl.String),
        lemma=pl.col("form"), pos=pl.lit("noun"), tier=pl.lit("attested"), confidence=pl.lit(1.0),
        evidence=pl.lit("hyphenation"), sources=pl.lit(["kaikki_en"])), schema.READINGS)


@pytest.fixture
def fast_model(monkeypatch):
    monkeypatch.setattr(config, "MODEL_MAX_ITER", 40)
    monkeypatch.setattr(config, "MODEL_MIN_CONFIDENCE", 0.5)
    monkeypatch.setattr(config, "MODEL_MIN_CONFIDENCE_BY_POS", {"noun": 0.5})


def test_model_smoke_and_determinism(fast_model):
    readings = synthetic_readings(400)
    targets = pl.DataFrame({
        "form": ["bodalico", "tamerato", "pst", "città", "lunatica"],
        "pos": ["noun", "noun", None, "noun", "noun"],
        "lemma": ["bodalico", "tamerato", None, "città", "lunatico"],
    })
    out = model.predict(readings, targets)
    again = model.predict(readings, targets)
    for key in ("predictions", "low_confidence", "metrics"):
        assert_frame_equal(out[key], again[key])

    pred = out["predictions"]
    assert pred.schema == pl.Schema(schema.READINGS)
    got = {f: (i, t) for f, i, t in pred.select("form", "stress_idx", "tier").rows()}
    assert got["città"] == (4, "attested")
    assert got["bodalico"] == (3, "predicted")   # bòdalico
    assert got["tamerato"] == (5, "predicted")   # tameràto
    assert (pred.filter(pl.col("tier") == "predicted")["confidence"] >= 0.5).all()
    low = out["low_confidence"]
    assert low.columns == ["form", "stress_idx", "confidence"]
    assert low.filter(pl.col("form") == "pst").rows() == [("pst", None, 0.0)]   # no vowel
    assert "pst" not in got

    m = out["metrics"]
    assert m.columns[:4] == ["n_train", "cv_accuracy", "cv_accuracy_confident", "coverage_confident"]
    assert m["n_train"][0] + m["n_cv"][0] == 400   # lemma = form: every form is its own group
    assert 0 < m["n_cv"][0] < 200
    assert m["cv_accuracy"][0] > 0.9
    assert m["n_cv_noun"][0] == m["n_cv"][0]
    assert m["temperature"][0] > 0


def test_model_thresholds_by_pos(fast_model, monkeypatch):
    monkeypatch.setattr(config, "MODEL_MIN_CONFIDENCE_BY_POS", {"name": 1.01})
    targets = pl.DataFrame({"form": ["bodalico"] * 3, "pos": ["noun", "name", None], "lemma": ["bodalico"] * 3})
    out = model.predict(synthetic_readings(400), targets)
    assert out["predictions"].select("form", "pos").rows() == [("bodalico", "noun"), ("bodalico", None)]
    assert out["low_confidence"].is_empty()   # the name's stress ships under the other POS
    assert "n_cv_name" not in out["metrics"].columns   # no held-out name


def test_training_set_uses_attested_single_stress_forms():
    readings = pl.concat([
        synthetic_readings(3),
        schema.conform(pl.DataFrame({
            "form": ["ancora", "ancora", "città", "portarlo"], "stress_idx": [0, 3, 4, 5], "quality": [None] * 4,
            "lemma": ["ancora"] * 2 + ["città", "portare"], "pos": ["noun", "adv", "noun", "verb"],
            "tier": ["attested"] * 3 + ["propagated"],
            "confidence": [1.0] * 4, "evidence": ["hyphenation"] * 3 + ["none"], "sources": [["kaikki_en"]] * 4,
        }), schema.READINGS),
    ])
    train = model.training_set(readings)
    assert train.height == 3
    assert not train["form"].is_in(["ancora", "città", "portarlo"]).any()


def test_candidates_cover_every_vowel():
    vocab = model.fit_vocab(pl.Series("form", ["aiuola", "qui"]))
    cand = model.candidates(pl.DataFrame({"wid": [0, 1], "form": ["aiuola", "qui"], "pos": ["noun", None]})
                            .with_columns(pl.col("wid").cast(pl.UInt32)), vocab)
    assert cand.filter(pl.col("wid") == 0)["idx"].to_list() == [0, 1, 2, 3, 5]
    assert cand.filter(pl.col("wid") == 1)["vfe"].to_list() == [1, 0]
    assert cand.columns == ["wid", "idx", *model.FEATURES]
