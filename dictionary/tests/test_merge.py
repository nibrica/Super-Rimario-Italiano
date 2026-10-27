"""frequency/merge.py and frequency/homographs.py."""

import math

import polars as pl
import pytest
from scipy.stats import spearmanr

from rimario_build import config, schema
from rimario_build.frequency import homographs, merge

WF, OS, LZ = "wordfreq", "opensubtitles", "leipzig_news"
FLOORS = {WF: 1.0, OS: 0.6, LZ: 1.7}


# --- builders -----------------------------------------------------------------

def meta_df(complete: dict[str, bool] | None = None, floors: dict[str, float] = FLOORS) -> pl.DataFrame:
    complete = complete or {}
    return pl.DataFrame(
        [{"source": s, "total_tokens": None if s == WF else 10**9, "floor_zipf": f,
          "complete": complete.get(s, True), "truncated": s == WF} for s, f in floors.items()],
        schema=schema.FREQ_META,
    )


def freq_df(*rows: tuple) -> pl.DataFrame:
    """Rows of (form, source, zipf[, count[, cap_count, lower_count]]); counted sources default to count 1000."""
    data = []
    for form, source, zipf, *rest in rows:
        count = rest[0] if rest else (None if source == WF else 1000)
        cap, lower = rest[1:3] if len(rest) > 1 else (None, None)
        data.append({"form": form, "source": source, "zipf": zipf, "count": count,
                     "cap_count": cap, "lower_count": lower})
    return pl.DataFrame(data, schema=schema.FREQ)


def lex_df(**n_lexicons: int) -> pl.DataFrame:
    return pl.DataFrame({"form": list(n_lexicons), "n_lexicons": list(n_lexicons.values())},
                        schema={"form": pl.String, "n_lexicons": pl.Int8})


def run_merge(freq: pl.DataFrame, lex: pl.DataFrame, meta: pl.DataFrame | None = None) -> dict:
    return merge.merge(freq, meta if meta is not None else meta_df(), lex)


def zipf_of(out: dict, form: str) -> float:
    return out["form_zipf"].filter(pl.col("form") == form)["zipf"].item()


def entry(form: str, idx: int, lemmas: list[str], pos: list[str], tier: str = "attested",
          proper: bool = False, tags: list[str] = ()) -> dict:
    return {"form": form, "stress_idx": idx, "quality": None, "lemmas": sorted(lemmas), "pos": sorted(pos),
            "tier": tier, "confidence": 1.0, "tags": sorted(tags), "is_proper": proper, "provenance": "kaikki_en:ipa",
            "zipf": None, "share": None, "share_method": None, "is_default": None}


def form_zipf_df(lexicon_only: dict[str, float] | None = None, **zipf: float) -> pl.DataFrame:
    rows = [{"form": f, "zipf": z, "n_sources": 3, "n_lexicons": 1, "estimate": "corpus"} for f, z in zipf.items()]
    rows += [{"form": f, "zipf": z, "n_sources": 0, "n_lexicons": 1, "estimate": "lexicon_only"}
             for f, z in (lexicon_only or {}).items()]
    return pl.DataFrame(rows, schema=schema.FORM_ZIPF)


def contexts_df(*rows: tuple[str, str, int]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=schema.CONTEXTS, orient="row")


def run_split(entries: list[dict], form_zipf: pl.DataFrame, contexts: pl.DataFrame | None = None,
              freq: pl.DataFrame | None = None) -> dict:
    return homographs.split(
        pl.DataFrame(entries, schema=schema.ENTRIES), form_zipf,
        contexts if contexts is not None else schema.empty(schema.CONTEXTS),
        freq if freq is not None else schema.empty(schema.FREQ),
    )


def rows_of(out: dict, form: str) -> dict[int, dict]:
    """stress_idx -> entry row (forms in these tests differ by stress)."""
    return {r["stress_idx"]: r for r in out["entries"].filter(pl.col("form") == form).iter_rows(named=True)}


# --- merge: reliability, bounds, robustness ----------------------------------

def test_reliability():
    df = pl.DataFrame({"count": [1, 10, 20, 500, None, None, None, None],
                       "zipf": [0.0, 0.0, 0.0, 0.0, 1.0, 1.5, 2.0, 4.0]})
    r = df.select(merge._reliability(1.0))["count"].to_list()
    lo = config.WORDFREQ_MIN_RELIABILITY
    assert r == pytest.approx([1 / 20, 0.5, 1.0, 1.0, lo, lo + (1 - lo) / 2, 1.0, 1.0])


def test_weighted_mean_uses_reliability():
    # wordfreq 3 (r=1), opensubtitles 2.5 with 10 occurrences (r=0.5), leipzig 3.2 (r=1)
    out = run_merge(freq_df(("a", WF, 3.0), ("a", OS, 2.5, 10), ("a", LZ, 3.2)), lex_df(a=2))
    assert zipf_of(out, "a") == pytest.approx((3.0 + 0.5 * 2.5 + 3.2) / 2.5)
    row = out["form_zipf"].row(0, named=True)
    assert (row["n_sources"], row["n_lexicons"], row["estimate"]) == (3, 2, "corpus")


def test_missing_word_is_an_upper_bound():
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 1.9)), lex_df(a=1))
    bound = FLOORS[LZ] - config.MISSING_OFFSET
    assert zipf_of(out, "a") == pytest.approx((2.0 + 1.9 + config.MISSING_WEIGHT_FACTOR * bound)
                                              / (2 + config.MISSING_WEIGHT_FACTOR))
    assert out["form_zipf"]["n_sources"].item() == 2


def test_missing_bound_never_pulls_a_word_up():
    """Seen once in OpenSubtitles: Leipzig's bound (1.2) is above it and ignored, wordfreq's (0.5) applies."""
    out = run_merge(freq_df(("a", OS, 0.7, 1)), lex_df(a=1))
    m, r = config.MISSING_WEIGHT_FACTOR, 1 / config.RELIABLE_COUNT
    bound = FLOORS[WF] - config.MISSING_OFFSET
    assert zipf_of(out, "a") == pytest.approx((r * 0.7 + m * bound) / (r + m))


def test_bounds_are_not_agreeing_sources():
    """Leipzig-only word: the two bounds agree, but only real observations make an outlier."""
    out = run_merge(freq_df(("a", LZ, 3.0, 30)), lex_df(a=1))
    m = config.MISSING_WEIGHT_FACTOR
    bounds = [FLOORS[WF] - config.MISSING_OFFSET, FLOORS[OS] - config.MISSING_OFFSET]
    assert zipf_of(out, "a") == pytest.approx((3.0 + m * sum(bounds)) / (1 + 2 * m))
    assert out["disagreements"].is_empty()


def test_incomplete_source_gives_no_bound():
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 1.9)), lex_df(a=1), meta_df({LZ: False}))
    assert zipf_of(out, "a") == pytest.approx(1.95)


def test_outlier_is_down_weighted_and_logged():
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 2.3), ("a", LZ, 5.0)), lex_df(a=1))
    w = config.OUTLIER_WEIGHT_FACTOR
    assert zipf_of(out, "a") == pytest.approx((2.0 + 2.3 + w * 5.0) / (2 + w))
    d = out["disagreements"].row(0, named=True)
    assert (d["form"], d["source"]) == ("a", LZ)
    assert d["zipf_others"] == pytest.approx(2.15)
    assert d["weight_factor"] == pytest.approx(w)


def test_outlier_weight_ramps():
    """Halfway along the ramp the weight is halfway between 1 and OUTLIER_WEIGHT_FACTOR."""
    z = 2.15 + config.OUTLIER_DISTANCE + config.OUTLIER_RAMP / 2
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 2.3), ("a", LZ, z)), lex_df(a=1))
    assert out["disagreements"]["weight_factor"].item() == pytest.approx((1 + config.OUTLIER_WEIGHT_FACTOR) / 2)


def test_estimate_has_no_step_in_the_count():
    """wordfreq 1.5, OpenSubtitles 5 occurrences, Leipzig c occurrences: no big drop as c grows."""
    total = 10**9 / 10**1.7                       # Leipzig floor 1.7
    zs = []
    for c in range(1, 60):
        lz = math.log10(c / total * 1e9)
        zs.append(zipf_of(run_merge(freq_df(("a", WF, 1.5), ("a", OS, 1.3, 5), ("a", LZ, lz, c)), lex_df(a=1)), "a"))
    assert max(a - b for a, b in zip(zs, zs[1:])) < 0.05, zs


def test_no_outlier_when_the_others_disagree():
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 3.0), ("a", LZ, 5.0)), lex_df(a=1))
    assert zipf_of(out, "a") == pytest.approx(10 / 3)
    assert out["disagreements"].is_empty()


def test_outlier_cut_never_raises_a_weak_observation():
    # leipzig seen twice (r = 0.1 < 0.25): an outlier, but its weight stays 0.1 and nothing is logged
    out = run_merge(freq_df(("a", WF, 2.0), ("a", OS, 2.1), ("a", LZ, 5.0, 2)), lex_df(a=1))
    assert zipf_of(out, "a") == pytest.approx((2.0 + 2.1 + 0.1 * 5.0) / 2.1)
    assert out["disagreements"].is_empty()


def test_missing_bound_can_be_an_outlier():
    out = run_merge(freq_df(("a", WF, 3.5), ("a", LZ, 3.6)), lex_df(a=1))
    d = out["disagreements"].row(0, named=True)
    assert (d["source"], d["zipf_source"]) == (OS, pytest.approx(FLOORS[OS] - config.MISSING_OFFSET))
    assert d["weight_factor"] == pytest.approx(config.OUTLIER_WEIGHT_FACTOR)


# --- merge: lexicon-only forms -----------------------------------------------

@pytest.mark.parametrize("floors", [FLOORS, {WF: 1.0, OS: -2.0, LZ: 1.7}, {WF: 3.0, OS: 3.0, LZ: 3.0}])
def test_lexicon_only_values(floors):
    lex = lex_df(seen=1, one=1, two=2, three=3)
    out = run_merge(freq_df(("seen", OS, floors[OS], 1)), lex, meta_df(floors=floors))
    fz = out["form_zipf"].sort("n_lexicons")
    only = fz.filter(pl.col("estimate") == "lexicon_only")
    assert only["form"].to_list() == ["one", "two", "three"]
    assert only["n_sources"].to_list() == [0, 0, 0]
    for shift in (0.0, math.log10(0.5)):         # also after a 50/50 homograph split
        ints = [round((z + shift) * 100) for z in only["zipf"]]
        assert ints[0] >= 0 and ints == sorted(set(ints)), (shift, ints)
    # below every corpus estimate (here the rarest possible one)
    assert only["zipf"].max() < zipf_of(out, "seen")


def test_accent_twin_cap():
    """cosi: a typo of così where news has it 2 lower; papa/papà close in news: kept."""
    freq = freq_df(("così", WF, 6.0), ("così", OS, 6.0), ("così", LZ, 5.8),
                   ("cosi", WF, 4.8), ("cosi", OS, 6.0), ("cosi", LZ, 3.8),
                   ("papà", WF, 5.0), ("papà", OS, 5.0), ("papà", LZ, 4.5),
                   ("papa", WF, 5.0), ("papa", OS, 5.0), ("papa", LZ, 4.4))
    out = run_merge(freq, lex_df(così=3, cosi=3, papà=3, papa=3))
    assert zipf_of(out, "cosi") == pytest.approx(zipf_of(out, "così") - 2.0)
    assert zipf_of(out, "papa") == pytest.approx((5.0 + 5.0 + 4.4) / 3)


def test_form_zipf_has_one_row_per_lexicon_form():
    lex = pl.concat([lex_df(b=1, a=1), lex_df(a=3)])
    out = run_merge(freq_df(("a", WF, 3.0), ("corpus_only", WF, 3.0)), lex)
    fz = out["form_zipf"]
    assert fz["form"].to_list() == ["a", "b"]
    assert fz.schema == pl.Schema(schema.FORM_ZIPF)
    assert fz.filter(pl.col("form") == "a")["n_lexicons"].item() == 3


# --- merge: correlations -----------------------------------------------------

def test_spearman_matches_scipy():
    a = [1.0, 2.0, 2.0, 5.0, 3.0, 7.0, 0.5]
    b = [2.0, 1.0, 3.0, 4.0, 4.0, 9.0, 0.1]
    rho = pl.DataFrame({"a": a, "b": b}).select(merge.spearman(pl.col("a"), pl.col("b"))).item()
    assert rho == pytest.approx(spearmanr(a, b).statistic)


def test_correlations_leave_one_out():
    rows = [(f"w{i}", s, z) for i, (x, y, z_) in enumerate([(1, 1.2, 0.9), (2, 2.1, 2.5), (3, 2.9, 3.1), (4, 4.2, 3.0)])
            for s, z in ((WF, float(x)), (OS, y), (LZ, z_))]
    rows.append(("only_wf", WF, 5.0))
    corr = run_merge(freq_df(*rows), lex_df(w0=1))["correlations"]
    assert corr["source"].to_list() == sorted([WF, OS, LZ])
    assert set(corr["n"]) == {4}
    lz = corr.filter(pl.col("source") == LZ)["spearman"].item()
    assert lz == pytest.approx(spearmanr([0.9, 2.5, 3.1, 3.0], [1.1, 2.05, 2.95, 4.1]).statistic)


def test_merge_is_deterministic():
    freq = freq_df(*[(f"w{i}", s, 1 + (i * 7 % 13) / 3) for i in range(50) for s in (WF, OS, LZ)])
    lex = lex_df(**{f"w{i}": 1 for i in range(60)})
    a, b = run_merge(freq, lex), run_merge(freq.reverse(), lex.reverse())
    for k in a:
        assert a[k].equals(b[k]), k


# --- homographs ----------------------------------------------------------------

def test_single_reading():
    out = run_split([entry("amore", 2, ["amore"], ["noun"])], form_zipf_df(amore=5.3))
    r = rows_of(out, "amore")[2]
    assert (r["share"], r["share_method"], r["is_default"], r["zipf"]) == (1.0, "single", True, 5.3)
    assert out["entries"].schema == pl.Schema(schema.ENTRIES)


def test_context_noun_vs_adverb():
    """àncora (noun, also ancorare) vs ancòra (adverb): verbal cues such as "non" pick the adverb."""
    entries = [entry("ancora", 0, ["ancora", "ancorare"], ["noun", "verb"]), entry("ancora", 3, ["ancora"], ["adv"])]
    ctx = contexts_df(("ancora", "non", 300), ("ancora", "il", 40), ("ancora", "la", 500), ("ancora", "mi", 20))
    out = run_split(entries, form_zipf_df(ancora=6.1), ctx)
    rows = rows_of(out, "ancora")
    a = config.CONTEXT_PRIOR
    p_verbal = (320 + a) / (360 + 2 * a)
    assert rows[3]["share"] == pytest.approx(p_verbal)
    assert rows[3]["zipf"] == pytest.approx(6.1 + math.log10(p_verbal))
    assert rows[3]["is_default"] and not rows[0]["is_default"]
    assert {r["share_method"] for r in rows.values()} == {"context"}


def test_context_verb_vs_noun():
    entries = [entry("viola", 1, ["violare"], ["verb"]), entry("viola", 2, ["viola"], ["adj", "noun"])]
    ctx = contexts_df(("viola", "il", 80), ("viola", "si", 20), ("viola", "loro", 500))   # loro: ambiguous
    out = run_split(entries, form_zipf_df(viola=4.5), ctx)
    a = config.CONTEXT_PRIOR
    assert rows_of(out, "viola")[1]["share"] == pytest.approx((20 + a) / (100 + 2 * a))
    assert rows_of(out, "viola")[2]["is_default"]


def test_context_row_on_both_sides():
    """ìndica (indicare + indico) takes the nominal share and, by its verb lemma, most of the verbal one."""
    entries = [entry("indica", 0, ["indicare", "indico"], ["adj", "noun", "verb"]),
               entry("indica", 3, ["indire"], ["verb"])]
    ctx = contexts_df(("indica", "si", 60), ("indica", "un", 20))
    out = run_split(entries, form_zipf_df(indica=4.4, indicare=4.6, indico=2.0, indire=2.6), ctx)
    rows = rows_of(out, "indica")
    a = config.CONTEXT_PRIOR
    p_verbal = (60 + a) / (80 + 2 * a)
    assert rows[3]["share"] == pytest.approx(p_verbal * 10**2.6 / (10**4.6 + 10**2.6))
    assert rows[0]["is_default"] and rows[0]["share_method"] == "context"


def test_context_dual_row_counts_only_its_verb_lemma():
    """àncora (noun ancora + ancorare) vs ancòra (adv): the verbal share goes by ancorare vs ancora."""
    entries = [entry("ancora", 0, ["ancora", "ancorare"], ["noun", "verb"]), entry("ancora", 3, ["ancora"], ["adv"])]
    ctx = contexts_df(("ancora", "non", 300), ("ancora", "il", 40))
    out = run_split(entries, form_zipf_df(ancora=6.1, ancorare=2.1), ctx)
    rows = rows_of(out, "ancora")
    a = config.CONTEXT_PRIOR
    p_verbal = (300 + a) / (340 + 2 * a)
    assert rows[0]["share"] == pytest.approx(1 - p_verbal + p_verbal * 10**2.1 / (10**2.1 + 10**6.1))
    assert rows[3]["is_default"]


def test_function_word_reading():
    entries = [entry("glie", 2, ["glia"], ["noun"]), entry("glie", 3, ["glie"], ["pron"])]
    out = run_split(entries, form_zipf_df(glie=3.3, glia=2.0), contexts_df(("glie", "le", 90)))
    rows = rows_of(out, "glie")
    assert rows[3]["share"] == pytest.approx(config.FUNCTION_WORD_SHARE) and rows[3]["is_default"]
    assert rows[2]["share_method"] == "function_word"


def test_minor_reading():
    """fìero (poetic, of fire) vs fièro: the tagged reading gets the small fixed share."""
    entries = [entry("fiero", 1, ["essere", "fire"], ["verb"], tags=["poetic"]), entry("fiero", 2, ["fiero"], ["adj"])]
    out = run_split(entries, form_zipf_df(fiero=4.1, essere=7.0))
    rows = rows_of(out, "fiero")
    assert rows[1]["share"] == pytest.approx(config.MINOR_READING_SHARE) and rows[2]["is_default"]
    assert rows[1]["share_method"] == "minor"


def test_participle_prior():
    """trovàti (participle) vs tròvati (imperative + ti): the participle is the default."""
    entries = [entry("trovati", 2, ["trovare", "trovarsi"], ["verb"]),
               entry("trovati", 4, ["trovato"], ["adj", "verb"])]
    ctx = contexts_df(("trovati", "si", 500))
    out = run_split(entries, form_zipf_df(trovati=4.4, trovare=5.5, trovato=4.0), ctx)
    rows = rows_of(out, "trovati")
    assert rows[4]["share"] == pytest.approx(config.PARTICIPLE_SHARE) and rows[4]["is_default"]
    assert rows[2]["share_method"] == "participle"


def test_participle_prior_needs_a_verb_only_rival():
    """mèriti (noun merito, also meritare) vs merìti: not the participle pattern."""
    entries = [entry("meriti", 1, ["meritare", "merito"], ["noun", "verb"]), entry("meriti", 3, ["merire"], ["verb"])]
    out = run_split(entries, form_zipf_df(meriti=3.5, merito=4.0, meritare=4.0, merire=0.5))
    assert rows_of(out, "meriti")[1]["is_default"] and rows_of(out, "meriti")[1]["share_method"] == "lemma_ratio"


def test_context_with_few_cues_falls_back_to_lemma_ratio():
    """capìto (capire, adj capito) vs càpito (capitare): 2 cues in 1,397 occurrences decide nothing."""
    entries = [entry("capito", 1, ["capitare"], ["verb"]), entry("capito", 3, ["capire", "capito"], ["adj", "verb"])]
    ctx = contexts_df(("capito", "si", 1), ("capito", "un", 1))
    out = run_split(entries, form_zipf_df(capito=4.9, capitare=3.9, capire=4.5), ctx)
    rows = rows_of(out, "capito")
    assert rows[3]["is_default"] and rows[3]["share_method"] == "lemma_ratio"


def test_context_without_cues_is_even():
    entries = [entry("capitano", 1, ["capitare"], ["verb"]), entry("capitano", 5, ["capitano"], ["noun"])]
    out = run_split(entries, form_zipf_df(capitano=4.9))
    assert [r["share"] for r in rows_of(out, "capitano").values()] == [0.5, 0.5]


def test_lemma_ratio():
    entries = [entry("principi", 2, ["principe"], ["noun"]),
               entry("principi", 5, ["principiare", "principio"], ["noun", "verb"])]
    out = run_split(entries, form_zipf_df(principi=4.5, principe=4.0, principio=4.3, principiare=2.0))
    rows = rows_of(out, "principi")
    w = [10**4.0, 10**4.3 + 10**2.0]
    assert rows[2]["share"] == pytest.approx(w[0] / sum(w))
    assert rows[5]["is_default"] and rows[5]["share_method"] == "lemma_ratio"


def test_rare_reading_keeps_a_positive_zipf():
    entries = [entry("dettagli", 1, ["dettare"], ["verb"]), entry("dettagli", 3, ["dettaglio"], ["noun"])]
    out = run_split(entries, form_zipf_df(dettagli=4.9, dettare=2.0, dettaglio=7.0))
    assert rows_of(out, "dettagli")[1]["zipf"] == config.READING_MIN_ZIPF


def test_lemma_ratio_adverb_vs_participle():
    """sùbito (adv) vs subìto (subire): both on the verbal side, so the lemmas decide."""
    entries = [entry("subito", 1, ["subito"], ["adv"]), entry("subito", 3, ["subire"], ["verb"])]
    out = run_split(entries, form_zipf_df(subito=5.6, subire=4.1), contexts_df(("subito", "non", 30)))
    rows = rows_of(out, "subito")
    assert rows[1]["is_default"] and rows[1]["share"] == pytest.approx(1 / (1 + 10**-1.5))


def test_capitalization():
    entries = [entry("como", 1, ["como"], ["name"], proper=True), entry("como", 4, ["comare"], ["verb"])]
    freq = freq_df(("como", LZ, 3.0, 100, 90, 4), ("como", WF, 4.0))      # 6 sentence-initial or all caps
    out = run_split(entries, form_zipf_df(como=4.0, comare=1.0), freq=freq)
    rows = rows_of(out, "como")
    a = config.CONTEXT_PRIOR
    assert rows[1]["share"] == pytest.approx((90 + a) / (94 + 2 * a))
    assert rows[1]["share_method"] == "capitalization" and rows[1]["is_default"]


def test_capitalization_without_signal_falls_through():
    entries = [entry("lappano", 1, ["lappare"], ["verb"]), entry("lappano", 4, ["lappano"], ["name"], proper=True)]
    freq = freq_df(("lappano", LZ, 1.7, 1, 0, 1))
    out = run_split(entries, form_zipf_df(lappano=1.0, lappare=1.0), freq=freq)
    assert set(out["entries"]["share_method"]) == {"lemma_ratio"}


def test_default_of_a_corpus_form_stays_above_lexicon_only_forms():
    entries = [entry("x", 0, ["x"], ["noun"]), entry("x", 2, ["x"], ["noun"]), entry("x", 4, ["x"], ["noun"]),
               entry("y", 0, ["y"], ["noun"])]
    out = run_split(entries, form_zipf_df(x=0.6, lexicon_only={"y": 0.34}))
    x = rows_of(out, "x")
    assert x[0]["is_default"] and x[0]["zipf"] == pytest.approx(0.34 + config.LEXICON_ONLY_STEP)
    assert x[2]["zipf"] == pytest.approx(0.6 - math.log10(3))
    assert out["even_splits"]["reason"].to_list() == ["same lemmas"]


def test_nested_split_even_inside_a_group():
    entries = [entry("x", 0, ["x"], ["noun"]), entry("x", 2, ["y"], ["verb"]), entry("x", 4, ["z"], ["verb"])]
    out = run_split(entries, form_zipf_df(x=3.0), contexts_df(("x", "il", 98)))
    rows = rows_of(out, "x")
    a = config.CONTEXT_PRIOR
    p_verbal = a / (98 + 2 * a)
    assert rows[2]["share"] == pytest.approx(p_verbal / 2) == rows[4]["share"]
    assert sum(r["share"] for r in rows.values()) == pytest.approx(1.0)
    assert out["even_splits"]["reason"].item() == "no lemma frequency (verbal side)"


def test_default_tie_break_by_tier_then_stress():
    entries = [entry("a", 0, ["a"], ["noun"], tier="predicted"), entry("a", 2, ["a"], ["noun"]),
               entry("b", 0, ["b"], ["noun"]), entry("b", 2, ["b"], ["noun"])]
    out = run_split(entries, form_zipf_df(a=1.0, b=1.0))
    assert rows_of(out, "a")[2]["is_default"] and not rows_of(out, "a")[0]["is_default"]
    assert rows_of(out, "b")[0]["is_default"] and not rows_of(out, "b")[2]["is_default"]
    assert out["entries"].group_by("form").agg(pl.col("is_default").sum())["is_default"].to_list() == [1, 1]
    assert out["even_splits"]["reason"].to_list() == ["same lemmas", "same lemmas"]


def test_missing_form_zipf_falls_back():
    out = run_split([entry("nuovo", 1, ["nuovo"], ["adj"])], form_zipf_df())
    assert rows_of(out, "nuovo")[1]["zipf"] == config.LEXICON_ONLY_MIN_ZIPF
