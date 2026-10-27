"""lexicon.py, export.py and report.py: inclusion rules, CSV format, curation scoring."""

import polars as pl
import pytest

from rimario_build import config, export, lexicon, report, schema


# --- builders -----------------------------------------------------------------

def forms_df(*rows: dict) -> pl.DataFrame:
    base = {"lemma": None, "pos": "noun", "feats": None, "stress_idx": None, "quality": None,
            "evidence": "none", "tags": [], "source": "kaikki_en"}
    data = [{**base, "lemma": r["form"], **r} for r in rows]
    return pl.DataFrame(data, schema=schema.FORMS)


def readings_df(*rows: dict) -> pl.DataFrame:
    base = {"quality": None, "pos": "noun", "tier": "attested", "confidence": 1.0,
            "evidence": "ipa", "sources": ["kaikki_en"]}
    data = [{**base, "lemma": r["form"], **r} for r in rows]
    return pl.DataFrame(data, schema=schema.READINGS)


def freq_df(*words: str) -> pl.DataFrame:
    return pl.DataFrame({"form": list(words)}, schema={"form": pl.String})


def low_df(*forms: str) -> pl.DataFrame:
    return pl.DataFrame({"form": list(forms), "stress_idx": [0] * len(forms), "confidence": [0.5] * len(forms)},
                        schema={"form": pl.String, "stress_idx": pl.Int16, "confidence": pl.Float64})


def entry(form: str, stress: int, zipf: float = 3.0, **kw) -> dict:
    return {"form": form, "stress_idx": stress, "quality": None, "lemmas": [form], "pos": ["noun"],
            "tier": "attested", "confidence": 1.0, "tags": [], "is_proper": False, "provenance": "",
            "zipf": zipf, "share": 1.0, "share_method": "single", "is_default": True, **kw}


def entries_df(*rows: dict) -> pl.DataFrame:
    return pl.DataFrame(list(rows), schema=schema.ENTRIES)


def rows_df(*rows: tuple) -> pl.DataFrame:
    return pl.DataFrame([r if len(r) == 4 else (*r, 0) for r in rows], schema=export.ROWS, orient="row")


NO_OVERRIDES = schema.empty(lexicon.OVERRIDES)


def run_select(forms, readings, freq=None, overrides=NO_OVERRIDES, low=None):
    out = lexicon.select(forms, readings, freq if freq is not None else freq_df(), overrides,
                         low if low is not None else low_df())
    return out["entries"], out["excluded"]


def keys(entries: pl.DataFrame) -> list[tuple]:
    return entries.select("form", "stress_idx").rows()


def tags_of(entries: pl.DataFrame) -> dict:
    return {(f, s): t for f, s, t in entries.select("form", "stress_idx", "tags").rows()}


# --- export -------------------------------------------------------------------

def test_flags_and_field_count(tmp_path):
    e = entries_df(
        entry("amore", 2, 5.12),
        entry("ancora", 0, 3.01, is_default=False),
        entry("ancora", 3, 4.89),
        entry("pesca", 1, 4.02, quality="open"),           # quality is never exported
        entry("cazzo", 1, 3.0, tags=["vulgar"]),
        entry("desio", 2, 2.0, tags=["literary", "regional"], tier="predicted", confidence=0.95),
        entry("roma", 1, 5.0, is_proper=True),
        entry("raro", 1, -0.3),
    )
    rows = export.to_rows(e)
    flags = {(w, s, f) for w, s, _, f in rows.iter_rows()}
    assert ("ancora", 0, 1) in flags and ("ancora", 3, 0) in flags and ("pesca", 1, 0) in flags
    assert ("cazzo", 1, 4) in flags and ("desio", 2, 10) in flags and ("roma", 1, 16) in flags
    path = tmp_path / "out.csv"
    export.write_csv(rows, path)
    lines = path.read_bytes().decode().split("\n")
    assert lines[-1] == "" and "\r" not in path.read_text()
    assert "amore,2,512" in lines and "ancora,0,301,1" in lines and "ancora,3,489" in lines
    assert "raro,1,0" in lines                     # clamped to >= 0
    assert all(len(l.split(",")) == (4 if l.count(",") == 3 else 3) for l in lines[:-1])
    assert not any(l.endswith(",0") and l.count(",") == 3 for l in lines)


def test_sort_reversed_code_points_then_stress_then_flags(tmp_path):
    rows = rows_df(
        ("città", 4, 400), ("citta", 1, 10), ("ancora", 3, 489), ("ancora", 0, 301, 1),
        ("pesca", 1, 402, 3), ("pesca", 1, 355, 2), ("bà", 1, 5), ("ba", 1, 5), ("za", 1, 5),
    )
    path = tmp_path / "out.csv"
    export.write_csv(rows, path)
    words = [tuple(l.split(",")) for l in path.read_text().splitlines()]
    assert [w[0] for w in words] == ["ba", "pesca", "pesca", "ancora", "ancora", "citta", "za", "bà", "città"]
    assert words[1] == ("pesca", "1", "355", "2") and words[2] == ("pesca", "1", "402", "3")
    assert words[3][1] == "0" and words[4][1] == "3"


def test_csv_is_byte_identical_for_identical_input(tmp_path):
    e = entries_df(*(entry(w, 1, z) for w, z in [("casa", 5.0), ("cosa", 6.0), ("chiesa", 4.5),
                                                  ("perché", 6.1), ("viola", 4.0)]),
                   entry("viola", 0, 3.0, is_default=False))
    shas, blobs = [], []
    for seed in (1, 2):
        shuffled = e.sample(fraction=1.0, shuffle=True, seed=seed)
        path = tmp_path / f"{seed}.csv"
        shas.append(export.write_csv(export.to_rows(shuffled), path))
        blobs.append(path.read_bytes())
    assert blobs[0] == blobs[1] and shas[0] == shas[1]


def test_read_csv_round_trip(tmp_path):
    rows = rows_df(("ancora", 0, 301, 1), ("ancora", 3, 489), ("pesca", 1, 355, 2))
    path = tmp_path / "new.csv"
    export.write_csv(rows, path)
    assert export.read_csv(path).equals(export.sort_rows(rows))
    assert export.read_csv(path.read_bytes()).equals(export.sort_rows(rows))
    got = export.read_csv(b"a,0,507\nfiaba,2,30,1\n")
    assert got.columns == ["word", "stress", "zipf", "flags"]
    assert got.rows() == [("a", 0, 507, 0), ("fiaba", 2, 30, 1)]
    assert export.read_csv(tmp_path / "missing.csv").is_empty() and export.read_csv(b"").is_empty()
    with pytest.raises(ValueError):
        export.read_csv(b"a,0,1\nb,1\n")


def test_attribution_lists_sources_and_versions(tmp_path):
    common = {"license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/"}
    sources = [{"id": "kaikki_en", "name": "Kaikki", "provides": "IPA", "homepage": "https://kaikki.org",
                "attribution": "From Wiktionary.", "cite": [{"text": "Ylonen 2022", "url": "https://x"}], **common},
               {"id": "wordfreq", "name": "wordfreq", "provides": "Zipf", "homepage": "https://w",
                "attribution": "By Speer.", "cite": [{"text": "Speer 2022"}], **common},
               {"id": "offline", "name": "Offline", "provides": "x", "homepage": "https://o",
                "attribution": "o", "cite": [{"text": "o"}], **common}]
    lock = {"kaikki_en": {"url": "https://k", "sha256": "ab" * 32, "etag": '"e1"',
                          "fetched_at": "2026-10-01T00:00:00Z"},
            "wordfreq": {"version": "3.1.1"}}
    path = tmp_path / "ATTRIBUTION.md"
    export.write_attribution(sources, lock, path)
    md = path.read_text()
    for s in ("## Kaikki", "CC BY-SA 4.0", "Ylonen 2022 <https://x>", "  - Speer 2022\n", "`3.1.1`",
              '`"e1"`', "2026-10-01", "GPL-3.0-or-later", "From Wiktionary.", "not recorded"):
        assert s in md, s


# --- lexicon ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def keep_unseen_forms(monkeypatch):
    """The other tests' forms are in one lexicon and mostly in no corpus."""
    monkeypatch.setattr(config, "UNSEEN_MIN_LEXICONS", 1)


def test_forms_in_no_corpus_need_enough_lexicons(monkeypatch):
    monkeypatch.setattr(config, "UNSEEN_MIN_LEXICONS", 2)
    forms = forms_df({"form": "raro"}, {"form": "rarissimo"}, {"form": "rarissimo", "lemma": "raro"},
                     {"form": "comune"}, {"form": "comune", "source": "morphit"}, {"form": "visto"},
                     {"form": "dimmelo", "lemma": "dire", "pos": "verb", "source": "morphit"})
    readings = readings_df({"form": "raro", "stress_idx": 1}, {"form": "rarissimo", "stress_idx": 4},
                           {"form": "comune", "stress_idx": 3}, {"form": "visto", "stress_idx": 1},
                           {"form": "dimmelo", "stress_idx": 1, "lemma": "dire", "pos": "verb", "tier": "propagated",
                            "evidence": "none", "sources": ["paradigm.enclitic"]})
    entries, excluded = run_select(forms, readings, freq_df("visto"))
    assert keys(entries) == [("comune", 3), ("dimmelo", 1), ("visto", 1)]     # enclitics are exempt
    assert excluded.rows() == [("rarissimo", "few_lexicons"), ("raro", "few_lexicons")]

    overrides = pl.DataFrame([("raro", 1, "add", None)], schema=lexicon.OVERRIDES, orient="row")
    entries, excluded = run_select(forms, readings, freq_df("visto"), overrides=overrides)
    assert ("raro", 1) in keys(entries) and excluded["form"].to_list() == ["rarissimo"]

    monkeypatch.setattr(config, "UNSEEN_MIN_LEXICONS", 3)
    entries, _ = run_select(forms, readings, freq_df("visto"))
    assert keys(entries) == [("dimmelo", 1), ("visto", 1)]


def test_proper_nouns_need_kaikki_and_frequency_and_never_duplicate_a_common_reading():
    forms = forms_df({"form": "rosa"}, {"form": "rosa", "pos": "name", "tags": ["proper"]},
                     {"form": "mario", "pos": "name"}, {"form": "pippo", "pos": "name"},
                     {"form": "como", "pos": "name"}, {"form": "como", "pos": "noun"},
                     {"form": "reggio", "pos": "name", "source": "morphit"})
    readings = readings_df({"form": "rosa", "stress_idx": 1},
                           {"form": "rosa", "stress_idx": 1, "pos": "name"},
                           {"form": "mario", "stress_idx": 3, "pos": "name"},
                           {"form": "pippo", "stress_idx": 1, "pos": "name"},
                           {"form": "como", "stress_idx": 1, "pos": "name"},
                           {"form": "como", "stress_idx": 3, "pos": "noun"},
                           {"form": "reggio", "stress_idx": 1, "pos": "name", "tier": "predicted",
                            "confidence": 0.95, "sources": ["model"], "evidence": "none"})
    entries, excluded = run_select(forms, readings, freq_df("rosa", "mario", "como", "reggio"))
    got = {(f, s): p for f, s, p in entries.select("form", "stress_idx", "is_proper").rows()}
    assert got == {("rosa", 1): False, ("mario", 3): True, ("como", 1): True, ("como", 3): False}
    assert excluded.rows() == [("pippo", "proper_no_freq"), ("reggio", "proper_no_kaikki")]


def test_vowel_quality_never_splits_rows():
    forms = forms_df({"form": "pesca"}, {"form": "botte"}, {"form": "botte", "lemma": "botta"})
    readings = readings_df(
        {"form": "pesca", "stress_idx": 1, "quality": "open"},
        {"form": "pesca", "stress_idx": 1, "quality": "closed", "sources": ["kaikki_it"],
         "evidence": "hyphenation"},
        {"form": "pesca", "stress_idx": 1, "tier": "propagated", "sources": ["morphit"], "evidence": "none"},
        {"form": "botte", "stress_idx": 1, "quality": "closed"},
        {"form": "botte", "stress_idx": 1, "quality": "open", "lemma": "botta", "tier": "predicted",
         "confidence": 0.95},
    )
    entries, _ = run_select(forms, readings)
    assert keys(entries) == [("botte", 1), ("pesca", 1)]
    assert entries["quality"].null_count() == 2
    botte, pesca = entries.rows(named=True)
    assert botte["lemmas"] == ["botta", "botte"] and botte["tier"] == "attested"
    assert pesca["provenance"] == "kaikki_en:ipa,kaikki_it:hyphenation,morphit:none"


def test_loanwords():
    forms = forms_df(*({"form": f} for f in (
        "weekend", "jazz", "yogurt", "juventini", "jihadisti", "performance", "micro", "the", "me")))
    pred = {"tier": "predicted", "confidence": 0.95, "evidence": "none", "sources": ["model"]}
    single = {"tier": "propagated", "evidence": "none", "sources": ["paradigm.single_vowel"]}
    readings = readings_df(
        {"form": "weekend", "stress_idx": 1},                                   # attested
        {"form": "yogurt", "stress_idx": 1, "evidence": "hyphenation", "sources": ["kaikki_it"]},
        {"form": "juventini", "stress_idx": 6, "lemma": "juventino", "tier": "propagated",
         "evidence": "none", "sources": ["paradigm.nominal"]},
        {"form": "jazz", "stress_idx": 1, **pred},                              # j/k/w/x/y, no suffix
        {"form": "jihadisti", "stress_idx": 5, **pred},                         # Italian suffix -isti
        {"form": "performance", "stress_idx": 7, **pred},                       # English 5.2 vs 4.3
        {"form": "micro", "stress_idx": 1, **pred},                             # English 4.08 vs 4.00
        {"form": "the", "stress_idx": 2, **single},                             # English 7.7 vs 5.5
        {"form": "me", "stress_idx": 1, "pos": "pron", **single},               # English 6.5 vs 6.1
    )
    entries, excluded = run_select(forms, readings)
    assert sorted(entries["form"]) == ["jihadisti", "juventini", "me", "micro", "weekend", "yogurt"]
    assert excluded.rows() == [("jazz", "loanword"), ("performance", "loanword"), ("the", "loanword")]


def test_exclusions_and_tiers():
    forms = forms_df(
        {"form": "sig", "tags": ["abbreviation"]}, {"form": "perchè", "tags": ["misspelling"]},
        {"form": "striscie", "lemma": "strisce", "tags": ["misspelling"]},
        {"form": "striscie", "lemma": "striscia", "source": "morphit"},
        {"form": "c'è"}, {"form": "'ndrangheta"}, {"form": "dubbio"}, {"form": "nulla"},
        {"form": "ii", "pos": "num", "source": "morphit"}, {"form": "di", "pos": "num", "source": "morphit"},
        {"form": "di", "pos": "prep", "source": "morphit"}, {"form": "me", "pos": "pron"},
    )
    readings = readings_df(
        {"form": "sig", "stress_idx": 1}, {"form": "perchè", "stress_idx": 5}, {"form": "c'è", "stress_idx": 2},
        {"form": "striscie", "stress_idx": 3, "lemma": "striscia", "tier": "propagated", "evidence": "none",
         "sources": ["paradigm.nominal"]},
        {"form": "ii", "stress_idx": 0, "pos": "num"}, {"form": "di", "stress_idx": 1, "pos": "prep"},
        {"form": "di", "stress_idx": 1, "pos": "num"}, {"form": "me", "stress_idx": 1, "pos": "pron"},
        {"form": "generato", "stress_idx": 4, "tier": "propagated"},
        {"form": "inventato", "stress_idx": 4},
        {"form": "previsto", "stress_idx": 3, "tier": "predicted", "confidence": 0.97},
    )
    entries, excluded = run_select(forms.vstack(forms_df({"form": "previsto"})), readings,
                                   low=low_df("dubbio", "'ndrangheta"))
    assert dict(excluded.rows()) == {"sig": "abbreviation", "perchè": "misspelling", "striscie": "misspelling",
                                     "c'è": "chars", "'ndrangheta": "chars", "dubbio": "low_confidence",
                                     "nulla": "no_stress", "ii": "roman_numeral", "inventato": "not_in_lexicon"}
    got = {f: t for f, t in entries.select("form", "tier").rows()}
    assert got == {"di": "attested", "generato": "propagated", "me": "attested", "previsto": "predicted"}


def test_atonic_function_words_go_with_all_their_readings():
    """la/si: the note goes with the article or clitic; so does glìe (plural of glia), stressed elsewhere."""
    forms = forms_df(
        {"form": "la", "pos": "article"}, {"form": "la", "pos": "pron"}, {"form": "la", "pos": "noun"},
        {"form": "si", "pos": "pron"}, {"form": "si", "pos": "noun"}, {"form": "si", "pos": "num"},
        {"form": "glie", "pos": "pron"}, {"form": "glie", "lemma": "glia"}, {"form": "me", "pos": "pron"},
        {"form": "luna"},
    )
    readings = readings_df(
        {"form": "la", "stress_idx": 1, "pos": "article"}, {"form": "la", "stress_idx": 1, "pos": "pron"},
        {"form": "la", "stress_idx": 1}, {"form": "si", "stress_idx": 1, "pos": "pron"},
        {"form": "si", "stress_idx": 1}, {"form": "si", "stress_idx": 1, "pos": "num"},
        {"form": "glie", "stress_idx": 3, "pos": "pron"}, {"form": "glie", "stress_idx": 2, "lemma": "glia"},
        {"form": "me", "stress_idx": 1, "pos": "pron"}, {"form": "luna", "stress_idx": 1},
    )
    entries, excluded = run_select(forms, readings)
    assert keys(entries) == [("luna", 1), ("me", 1)]
    assert excluded.rows() == [("glie", "atonic"), ("la", "atonic"), ("si", "atonic")]


def test_tags_need_every_row_of_a_source_except_vulgar_form_of():
    """siete: one archaic table cell among plain rows; auto/pizzo: one sense among others."""
    forms = forms_df(
        {"form": "siete", "lemma": "essere", "pos": "verb", "evidence": "table", "stress_idx": 2},
        {"form": "siete", "lemma": "essere", "pos": "verb", "evidence": "table", "stress_idx": 2,
         "tags": ["archaic"]},
        {"form": "auto", "tags": ["abbreviation"]}, {"form": "auto", "evidence": "ipa", "stress_idx": 0},
        {"form": "auto", "source": "kaikki_it"},
        {"form": "pizzo", "tags": ["derogatory"]}, {"form": "pizzo", "evidence": "ipa", "stress_idx": 0},
        {"form": "coglioni", "lemma": "coglione", "tags": ["vulgar"]},
        {"form": "coglioni", "lemma": "coglione", "evidence": "ipa", "stress_idx": 4},
    )
    readings = readings_df({"form": "siete", "lemma": "essere", "pos": "verb", "stress_idx": 2},
                           {"form": "auto", "stress_idx": 0}, {"form": "pizzo", "stress_idx": 1},
                           {"form": "coglioni", "lemma": "coglione", "stress_idx": 4})
    entries, excluded = run_select(forms, readings)
    assert excluded.is_empty()
    assert dict(entries.select("form", "tags").rows()) == {
        "siete": [], "auto": [], "pizzo": [], "coglioni": ["vulgar"]}


def test_archaic_needs_both_kaikki_sources_and_every_reading():
    forms = forms_df(
        {"form": "stazione", "tags": ["archaic"]}, {"form": "stazione", "source": "kaikki_it"},
        {"form": "stazione", "source": "morphit"},
        {"form": "giammai", "pos": "adv", "tags": ["literary"]},
        {"form": "giammai", "pos": "adv", "tags": ["literary"], "source": "kaikki_it"},
        {"form": "speme", "tags": ["literary"]},                         # kaikki_en only
        {"form": "gente", "tags": ["archaic"]}, {"form": "gente", "source": "kaikki_it"},
        {"form": "gente", "lemma": "gire", "pos": "verb", "tags": ["archaic"]},
    )
    readings = readings_df({"form": "stazione", "stress_idx": 5}, {"form": "giammai", "pos": "adv", "stress_idx": 5},
                           {"form": "speme", "stress_idx": 1}, {"form": "gente", "stress_idx": 1},
                           {"form": "gente", "lemma": "gire", "pos": "verb", "stress_idx": 1})
    entries, _ = run_select(forms, readings)
    assert tags_of(entries) == {("gente", 1): [], ("giammai", 5): ["literary"], ("speme", 1): ["literary"],
                                ("stazione", 5): []}


def test_vulgar_spreads_over_readings_except_from_verb_inflections():
    forms = forms_df(
        {"form": "cazzo", "tags": ["vulgar"]}, {"form": "cazzo", "lemma": "cazzare", "pos": "verb"},
        {"form": "puttana"}, {"form": "puttana", "lemma": "puttano", "tags": ["vulgar"]},
        {"form": "chiavi", "lemma": "chiave"}, {"form": "chiavi", "lemma": "chiavare", "pos": "verb",
                                                 "tags": ["vulgar"]},
        {"form": "fottuta", "lemma": "fottere", "pos": "verb", "tags": ["vulgar"]},
    )
    readings = readings_df(
        {"form": "cazzo", "stress_idx": 1}, {"form": "cazzo", "lemma": "cazzare", "pos": "verb", "stress_idx": 1},
        {"form": "puttana", "stress_idx": 4}, {"form": "puttana", "lemma": "puttano", "stress_idx": 4},
        {"form": "chiavi", "lemma": "chiave", "stress_idx": 3},
        {"form": "chiavi", "lemma": "chiavare", "pos": "verb", "stress_idx": 3},
        {"form": "fottuta", "lemma": "fottere", "pos": "verb", "stress_idx": 4},
    )
    entries, _ = run_select(forms, readings)
    assert tags_of(entries) == {("cazzo", 1): ["vulgar"], ("chiavi", 3): [], ("fottuta", 4): ["vulgar"],
                                ("puttana", 4): ["vulgar"]}


def test_overrides_add_remove_fix(tmp_path):
    path = tmp_path / "overrides.tsv"
    path.write_text(
        "form\tstress_idx\taction\tnote\n# comment\n\n"
        "pesca\t1\tfix\tfrutto\n"
        "ancora\t0\tadd\tnave\n"
        "viola\t1\tremove\t\n"
        "sbaglio\t\tremove\ttutta la forma\n"
        "jazz\t1\tadd\tprestito\n"
    )
    overrides = lexicon.load_overrides(path)
    assert overrides.height == 5 and overrides.columns == ["form", "stress_idx", "action", "note"]
    forms = forms_df({"form": "pesca"}, {"form": "ancora"}, {"form": "viola"}, {"form": "sbaglio"},
                     {"form": "jazz", "source": "morphit"})
    readings = readings_df({"form": "pesca", "stress_idx": 1}, {"form": "pesca", "stress_idx": 3},
                           {"form": "ancora", "stress_idx": 3},
                           {"form": "ancora", "stress_idx": 0, "tier": "predicted", "confidence": 0.95},
                           {"form": "viola", "stress_idx": 1}, {"form": "viola", "stress_idx": 2},
                           {"form": "sbaglio", "stress_idx": 1}, {"form": "jazz", "stress_idx": 1})
    entries, excluded = run_select(forms, readings, overrides=overrides)
    assert keys(entries) == [("ancora", 0), ("ancora", 3), ("jazz", 1), ("pesca", 1), ("viola", 2)]
    tiers = {(f, s): t for f, s, t in entries.select("form", "stress_idx", "tier").rows()}
    assert tiers[("ancora", 0)] == "override" and tiers[("ancora", 3)] == "attested"
    assert tiers[("pesca", 1)] == "override"
    assert excluded.rows() == [("sbaglio", "override_remove")]


@pytest.mark.parametrize("line, msg", [
    ("casa\t2\tadd\t", "not a vowel"),
    ("casa\t1\tmove\t", "action"),
    ("casa\t\tadd\t", "needs a stress_idx"),
    ("casa\tx\tadd\t", "non-negative integer"),
    ("perché\t1\tadd\t", "accent written"),
    ("c'è\t2\tadd\t", "characters"),
    ("casa\t1\topen\tadd\t", "at most 4"),
])
def test_bad_override_lines_fail_with_line_number(tmp_path, line, msg):
    path = tmp_path / "overrides.tsv"
    path.write_text(f"# header comment\n{line}\n")
    with pytest.raises(ValueError, match=rf"overrides.tsv:2: .*{msg}"):
        lexicon.load_overrides(path)


# --- report -------------------------------------------------------------------

def test_gold_accuracy(tmp_path):
    path = tmp_path / "gold.tsv"
    path.write_text(
        "form\tstress_idx\tdefault\tnote\n"
        "ancora\t3\t1\t\nancora\t0\t0\t\n"          # ok, ok
        "pesca\t1\t\t\n"                             # ok
        "viola\t2\t1\t\n"                            # should be default: miss
        "capitano\t1\t\t\n"                          # missing reading: miss
        "zuzu\t1\t\t\n"                              # missing form: miss
    )
    gold = report.load_gold(path)
    rows = rows_df(("ancora", 3, 489), ("ancora", 0, 301, 1), ("pesca", 1, 355),
                   ("viola", 0, 400), ("viola", 2, 300, 1), ("capitano", 4, 400))
    acc, misses = report.gold_accuracy(rows, gold)
    assert acc == pytest.approx(3 / 6)
    assert dict(zip(misses["form"], misses["reason"])) == {
        "viola": "should be default", "capitano": "missing reading", "zuzu": "missing form"}


@pytest.mark.parametrize("line, msg", [("casa\t2\t\t", "not a vowel"), ("casa\t1\t2\t", "default"),
                                       ("città\t1\t\t", "accent written")])
def test_bad_gold_lines_fail_with_line_number(tmp_path, line, msg):
    path = tmp_path / "gold.tsv"
    path.write_text(f"form\tstress_idx\tdefault\tnote\n{line}\n")
    with pytest.raises(ValueError, match=rf"gold.tsv:2: .*{msg}"):
        report.load_gold(path)


def test_freq_pair_agreement(tmp_path):
    path = tmp_path / "pairs.tsv"
    path.write_text("more\tless\tnote\namore\tamorevole\t\nciao\tsalve\t\nancora\tàncora\t\n"
                    "ancora\tamore\t\nzzz\tamore\t\n")
    pairs = report.load_freq_pairs(path)
    rows = rows_df(("amore", 2, 512), ("amorevole", 4, 300), ("ciao", 1, 500), ("salve", 1, 500),
                   ("ancora", 0, 700, 1), ("ancora", 3, 489))
    acc, misses = report.freq_pair_agreement(rows, pairs)
    assert acc == pytest.approx(1 / 5)
    assert misses.select("more", "less", "reason").rows() == [
        ("ciao", "salve", "tie"), ("ancora", "àncora", "missing"),
        ("ancora", "amore", "reversed"), ("zzz", "amore", "missing")]


def full_ctx(entries: pl.DataFrame, tmp_path) -> dict:
    return {
        "entries": entries, "rows": export.to_rows(entries),
        "form_zipf": pl.DataFrame({"form": ["ancora", "dimmelo"], "zipf": [4.9, 3.2]}),
        "excluded": pl.DataFrame({"form": ["sig", "xyz"], "reason": ["abbreviation", "low_confidence"]}),
        "conflicts": pl.DataFrame({"form": ["viola"], "lemma": ["viola"], "pos": ["noun"],
                                   "readings": ["kaikki_en:vìola kaikki_it:viòla"]}),
        "even_splits": pl.DataFrame({"form": ["pesca"], "stress_idxs": [[1, 4]], "reason": ["same lemmas"]}),
        "disagreements": pl.DataFrame({"form": ["meloni"], "source": ["leipzig_news"], "zipf_source": [5.0],
                                       "zipf_others": [3.0], "weight_factor": [0.25]}),
        "low_confidence": pl.DataFrame({"form": ["xyz", "xyz"], "stress_idx": [0, 1], "confidence": [0.4, 0.3]}),
        "metrics": pl.DataFrame({"n_train": [10], "cv_accuracy": [0.9]}),
        "correlations": pl.DataFrame({"source": ["wordfreq"], "spearman": [0.8], "n": [100]}),
        "lock_old": {"kaikki_en": {"sha256": "1" * 64}, "gone": {"sha256": "2" * 64}},
        "lock_new": {"kaikki_en": {"sha256": "3" * 64}, "wordfreq": {"version": "3.1.1"}},
        "fetch_warnings": ["leipzig_news unreachable, used local copy"],
        "gold": report.load_gold(tmp_path / "none.tsv"),
    }


def test_report_diffs_previous_build_and_is_deterministic(tmp_path):
    e = entries_df(entry("ancora", 3, 4.89), entry("ancora", 0, 3.01, is_default=False),
                   entry("nuovo", 1, 3.0), entry("pesca", 1, 3.55, is_default=False))
    ctx = full_ctx(e, tmp_path)
    previous = rows_df(("ancora", 0, 489), ("ancora", 3, 301, 1), ("vecchio", 1, 12), ("pesca", 1, 355, 1))
    md = report.render_report(ctx, previous, "X")
    assert md.count("Built:") == 1
    assert "**Forms added:** 1" in md and "**Forms removed:** 1" in md and "**Stress changed:** 0" in md
    assert "**Default reading changed:** 1 forms" in md and "| ancora | àncora | ancòra |" in md
    assert md == report.render_report(ctx, previous, "X")
    previous = rows_df(("ancora", 0, 489), ("ancora", 3, 301, 1), ("pesca", 0, 1))
    md = report.render_report(ctx, previous, "X")
    assert "**Stress changed:** 1" in md and "| pèsca (1) |" in md


def test_report_full_ctx(tmp_path):
    e = entries_df(entry("ancora", 3, 4.89), entry("ancora", 0, 3.01, is_default=False),
                   entry("dimmelo", 1, 3.2, tier="propagated", provenance="paradigm:none"),
                   entry("gnocco", 2, 2.1, tier="predicted", confidence=0.95))
    ctx = full_ctx(e, tmp_path)
    path = tmp_path / "report.md"
    report.write_report(ctx, export.read_csv(tmp_path / "none.csv"), path)
    md = path.read_text()
    for s in ("| kaikki_en | changed", "| gone | removed", "| wordfreq | new", "unreachable",
              "dìmmelo", "gnòcco", "| meloni | leipzig_news", "| wordfreq | 0.800 | 100 |",
              f"`{export.write_csv(ctx['rows'], tmp_path / 'x.csv')}`", "No previous CSV.",
              "| abbreviation | 1 |", "| 2–3 | 1 |", "| 3–4 | 2 |", "| 4–5 | 1 |", "| pèsca, pescà | same lemmas |",
              "2 predictions (1 forms) were below the confidence threshold of their POS (", "1 of those forms have no other reading",
              "at most 2,000", "| 2 predicted | 1 |", "| 16 proper | 0 |"):
        assert s in md, s
    assert "open" not in md and "closed" not in md
