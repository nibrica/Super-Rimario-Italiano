"""Combine attested stress evidence into readings and detect conflicts (§5.1).

Rules, per group (form, lemma, pos):

* Every row with a stress value is evidence, unless the spelling rules its
  index out (``possible``): those rows are dropped and counted per source.
* Rows rank by a key: orthographic evidence first (the spelling carries the
  accent, so it is attested by definition), then source priority
  (``config.STRESS_SOURCE_PRIORITY``; other sources such as morphit come
  after), then evidence strength inside the source
  (``config.VOTE_EVIDENCE_PRIORITY``).
* The best-ranked rows decide: their stress indexes become the readings. More
  than one index there means the strongest source lists variants itself
  (``èdile``/``edìle``); only those with the most support (distinct (source,
  evidence) rows on the index, at any rank) are kept, so a stray table cell
  (``credére``) loses to the headword, hyphenation and IPA (``crédere``).
* ``sources`` lists every source with a row on the reading's index, whatever
  its evidence; ``evidence`` is the strongest of those rows.
* ``quality`` comes from the rows on the reading's index that carry one: the
  best-ranked (source, evidence) decides; if it gives both open and closed
  (a variant), the quality stays null.

Conflicts (a CONFLICTS row each; the readings stay the priority winner's):

* a source votes (with its own top-ranked rows) for an index the readings
  lack, and the form has a single (lemma, pos) among the rows of the priority
  sources;
* a reading supported by kaikki_it alone has a stress that kaikki_en doesn't
  give the same (form, lemma) under any POS (kaikki_it ``adj`` *novàntotto*,
  kaikki_en ``num`` *novantòtto*; ``_kaikki_en_stress``): the kaikki_it
  reading is dropped.

Other groups with different (lemma, pos) and different stress are homographs
and are all kept. Groups without stress evidence produce no reading.
"""

import logging

import polars as pl

from .. import config, schema, text

log = logging.getLogger(__name__)

_KEY = schema.READING_KEY
_VOWEL_CLASS = f"[{''.join(sorted(text.VOWELS))}]"
_ACCENT_CLASS = f"[{''.join(sorted(text.ACCENTED))}]"


def possible(form: pl.Expr, idx: pl.Expr) -> pl.Expr:
    """False where the spelling rules the stress index out.

    * A written final accent (città) is the stress: any other index is wrong.
    * Without one, a polysyllable isn't stressed on a final vowel in
      ``config.VOTE_UNSTRESSED_FINALS`` (congelatò, triviò).
    * The ``u`` of ``qu`` + vowel is a glide (tranqùilla).
    """
    idx = idx.cast(pl.Int64)
    last = form.str.len_chars() - 1
    accented = form.str.contains(_ACCENT_CLASS + "$") & (form.str.count_matches(_ACCENT_CLASS) == 1)
    final = (
        (idx == last) & form.str.slice(-1).is_in(list(config.VOTE_UNSTRESSED_FINALS))
        & (form.str.count_matches(_VOWEL_CLASS + "+") > 1)
    )
    qu = (idx > 0) & (form.str.slice(idx - 1, 2) == "qu") & form.str.slice(idx + 1, 1).is_in(list(text.VOWELS))
    return pl.when(accented).then(idx == last).otherwise(~final & ~qu)


def _ranked(forms: pl.DataFrame) -> pl.DataFrame:
    """Possible stressed evidence rows with their source rank, evidence rank and key."""
    sources = config.STRESS_SOURCE_PRIORITY
    evidence = config.VOTE_EVIDENCE_PRIORITY
    ev = (
        forms.filter(pl.col("stress_idx").is_not_null() & (pl.col("evidence") != "none"))
        .select(*_KEY, "stress_idx", "quality", "evidence", "source")
        .with_columns(ok=possible(pl.col("form"), pl.col("stress_idx")))
    )
    bad = ev.filter(~pl.col("ok")).unique(["form", "stress_idx", "source"]).sort("source", "form", "stress_idx")
    for (src,), rows in bad.group_by("source", maintain_order=True):
        shown = ", ".join(text.mark_stress(f, i) for f, i in rows.select("form", "stress_idx").head(10).iter_rows())
        log.info("vote: %s: dropped %d impossible stresses (%s)", src, rows.height, shown)
    return (
        ev.filter("ok").drop("ok")
        .with_columns(
            src_rank=pl.col("source").replace_strict(
                {s: i for i, s in enumerate(sources)}, default=len(sources), return_dtype=pl.Int32),
            ev_rank=pl.col("evidence").replace_strict(
                {e: i for i, e in enumerate(evidence)}, default=len(evidence), return_dtype=pl.Int32),
        )
        .with_columns(
            key=(pl.col("evidence") != "ortho").cast(pl.Int32) * 1_000_000
            + pl.col("src_rank") * 1_000 + pl.col("ev_rank"),
        )
    )


def _joined_labels(df: pl.DataFrame) -> pl.DataFrame:
    """Sorted rows [form, lemma, pos, source, stress_idx, quality] → [form, lemma, pos,
    readings] with readings "source:màrked ..." in row order."""
    labels = [
        f"{src}:{text.mark_stress(form, idx, q)}"
        for form, src, idx, q in df.select("form", "source", "stress_idx", "quality").iter_rows()
    ]
    return (
        df.with_columns(label=pl.Series(labels, dtype=pl.String))
        .group_by(_KEY, maintain_order=True).agg(readings=pl.col("label").str.join(" "))
    )


def _conflicts(forms: pl.DataFrame, ev: pl.DataFrame, readings: pl.DataFrame) -> pl.DataFrame:
    """Single-(lemma, pos) groups where some source's top vote is not among the readings."""
    single = (
        forms.filter(pl.col("source").is_in(config.STRESS_SOURCE_PRIORITY))
        .group_by("form").agg(n=pl.struct("lemma", "pos").n_unique())
        .filter(pl.col("n") == 1).select("form")
    )
    # Each source's own vote: its best-ranked rows in the group.
    votes = (
        ev.join(single, on="form")
        .filter(pl.col("key") == pl.col("key").min().over(*_KEY, "source"))
        .group_by(*_KEY, "source", "stress_idx")
        .agg(src_rank=pl.col("src_rank").first(), quality=pl.col("quality").drop_nulls().sort().first())
    )
    won = readings.select(*_KEY, "stress_idx").with_columns(won=pl.lit(True))
    bad = (
        votes.join(won, on=[*_KEY, "stress_idx"], how="left", nulls_equal=True)
        .filter(pl.col("won").is_null()).select(_KEY).unique()
    )
    return _joined_labels(votes.join(bad, on=_KEY, nulls_equal=True).sort(*_KEY, "src_rank", "source", "stress_idx"))


def _kaikki_en_stress(forms: pl.DataFrame, readings: pl.DataFrame) -> pl.DataFrame:
    """kaikki_en's stresses of each (form, lemma) it lists: its readings of the
    pair, plus the lemma's (not on its last letter) when the form differs from
    the lemma only in its last letter (brìvido → brìvidi, càlcolo → càlcoli).
    Rows [form, lemma, source, stress_idx, quality]."""
    en = readings.filter(pl.col("sources").list.contains("kaikki_en")).select(
        "form", "lemma", source=pl.lit("kaikki_en"), stress_idx="stress_idx", quality="quality")
    pairs = (
        forms.filter((pl.col("source") == "kaikki_en") & (pl.col("form") != pl.col("lemma"))
                     & (pl.col("form").str.head(-1) == pl.col("lemma").str.head(-1))
                     & (pl.col("form").str.len_chars() == pl.col("lemma").str.len_chars()))
        .select("form", "lemma").unique()
    )
    inherited = pairs.join(
        en.filter(pl.col("form") == pl.col("lemma")).drop("form"), on="lemma"
    ).filter(pl.col("stress_idx") < pl.col("form").str.len_chars() - 1)
    return pl.concat([en, inherited.select(en.columns)]).unique()


def _kaikki_it_clashes(forms: pl.DataFrame, readings: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """kaikki_it-only readings whose stress kaikki_en doesn't give the same
    (form, lemma) under any POS → (their [form, lemma, pos, stress_idx], CONFLICTS rows)."""
    en = _kaikki_en_stress(forms, readings)
    clash = (
        readings.filter(pl.col("sources").list.join(",") == "kaikki_it")
        .join(en.group_by("form", "lemma").agg(en_idx=pl.col("stress_idx")), on=["form", "lemma"])
        .filter(~pl.col("en_idx").list.contains(pl.col("stress_idx")))
        .select(*_KEY, source=pl.lit("kaikki_it"), stress_idx="stress_idx", quality="quality")
    )
    # kaikki_en's stresses of the same (form, lemma), shown under the kaikki_it group
    en_shown = en.join(clash.select(_KEY).unique(), on=["form", "lemma"]).select(clash.columns)
    shown = pl.concat([en_shown, clash]).unique().sort(*_KEY, "source", "stress_idx", "quality", nulls_last=True)
    return clash.select(*_KEY, "stress_idx"), _joined_labels(shown)


def vote(forms: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """FORMS → {"readings": READINGS (tier "attested"), "conflicts": CONFLICTS}."""
    ev = _ranked(forms)
    per_idx = ev.group_by(*_KEY, "stress_idx").agg(
        key=pl.col("key").min(), support=pl.struct("source", "evidence").n_unique())
    best = (
        per_idx.filter(pl.col("key") == pl.col("key").min().over(_KEY))
        .filter(pl.col("support") == pl.col("support").max().over(_KEY))
        .select(*_KEY, "stress_idx")
    )
    chosen = ev.join(best, on=[*_KEY, "stress_idx"], nulls_equal=True)
    quality = (
        chosen.filter(pl.col("quality").is_not_null())
        .filter(pl.col("key") == pl.col("key").min().over(*_KEY, "stress_idx"))
        .group_by(*_KEY, "stress_idx")
        .agg(quality=pl.when(pl.col("quality").n_unique() == 1).then(pl.col("quality").first()))
    )
    readings = schema.conform(
        chosen.group_by(*_KEY, "stress_idx")
        .agg(
            evidence=pl.col("evidence").sort_by("ev_rank", "evidence").first(),
            sources=pl.col("source").unique().sort(),
        )
        .join(quality, on=[*_KEY, "stress_idx"], how="left", nulls_equal=True)
        .with_columns(tier=pl.lit("attested"), confidence=pl.lit(1.0)),
        schema.READINGS,
    )
    dropped, clashes = _kaikki_it_clashes(forms, readings)
    log.info("vote: dropped %d kaikki_it-only readings that contradict kaikki_en", dropped.height)
    readings = schema.sort_readings(
        readings.join(dropped, on=[*_KEY, "stress_idx"], how="anti", nulls_equal=True))
    conflicts = pl.concat([   # a dropped kaikki_it reading also lacks its group's vote: show kaikki_en's side
        schema.conform(clashes, schema.CONFLICTS),
        schema.conform(_conflicts(forms, ev, readings), schema.CONFLICTS),
    ]).unique(_KEY, keep="first", maintain_order=True)
    return {"readings": readings, "conflicts": conflicts.sort(_KEY, nulls_last=True)}
