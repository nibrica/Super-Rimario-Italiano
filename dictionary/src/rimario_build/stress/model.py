"""Learned stress fallback (§5.3): a per-vowel classifier with confidence.

Every vowel of a form is a candidate (i/u in diphthongs too: the model learns
when they glide). A ``HistGradientBoostingClassifier`` scores each candidate
"stressed or not" from:

* the vowel itself and ``config.MODEL_CONTEXT_CHARS`` characters on each side
  (fixed ordinal codes, categorical; a padding code past the word's edges);
* the word's last characters, one categorical feature each, and its suffix
  n-grams (``config.MODEL_SUFFIX_NGRAMS``), each encoded as categorical over
  the ``config.MODEL_SUFFIX_VOCAB`` most frequent training suffixes;
* the candidate's distance from the end in vowels and in characters, the
  word's vowel and character counts (numeric);
* the POS if known (categorical; missing otherwise).

Per form the candidate with the highest score wins. Its confidence is the
softmax of the candidates' logits within the form, i.e. each candidate's odds
normalized over the form: the probability that it is the stressed vowel given
that exactly one vowel is, if the per-vowel predictions were independent.

Training: distinct (form, stress_idx) of the attested readings, minus forms
with more than one stress (homographs) and forms whose spelling carries an
accent (trivial); rule outputs (tier "propagated") are not labels. A seeded
``1 / config.MODEL_FOLDS`` of the lemma groups (the form when the lemma is
missing) is held out, so inflections of one lemma never straddle the split.
The shipped model is fitted on the rest (a seeded subsample of
``config.MODEL_MAX_TRAIN_FORMS`` forms, non-verbs first: verbs are most of the
attested forms but a minority of the targets). The held-out forms, scored by
that same model, give the temperature and the metrics.

A prediction ships when its confidence reaches its POS's threshold
(``config.MODEL_MIN_CONFIDENCE_BY_POS``, else ``config.MODEL_MIN_CONFIDENCE``);
the rest, and targets without a vowel, go to ``low_confidence``.
"""

import logging
import math
import time

import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingClassifier

from .. import config, schema, text

log = logging.getLogger(__name__)

_ALPHABET = sorted(config.ALLOWED_CHARS)
_CHAR_CODE = {c: i for i, c in enumerate(_ALPHABET)}
_OTHER_CHAR, _PAD = len(_ALPHABET), len(_ALPHABET) + 1
_POS_CODE = {p: i for i, p in enumerate(schema.POS_VALUES)}
_ACCENT_CLASS = f"[{''.join(sorted(text.ACCENTED))}]"
_VOWEL_CLASS = f"[{''.join(sorted(text.VOWELS))}]"

_C = config.MODEL_CONTEXT_CHARS
_NGRAMS = config.MODEL_SUFFIX_NGRAMS
_LAST = max(_NGRAMS)
CATEGORICAL = (
    ["vowel"] + [f"m{k}" for k in range(1, _C + 1)] + [f"p{k}" for k in range(1, _C + 1)]
    + [f"last{k}" for k in range(1, _LAST + 1)] + [f"suf{n}" for n in _NGRAMS] + ["pos"]
)
NUMERIC = ["vfe", "cfe", "n_vowels", "n_chars"]
FEATURES = CATEGORICAL + NUMERIC

Vocab = dict[int, dict[str, int]]


def _char_code(expr: pl.Expr) -> pl.Expr:
    return expr.replace_strict(_CHAR_CODE, default=_OTHER_CHAR, return_dtype=pl.Int16)


def fit_vocab(forms: pl.Series) -> Vocab:
    """The most frequent suffix of each n-gram size, as {n: {suffix: code}}."""
    vocab = {}
    for n in _NGRAMS:
        top = (
            forms.str.slice(-n).value_counts(name="c")
            .sort(["c", "form"], descending=[True, False]).head(config.MODEL_SUFFIX_VOCAB)
        )
        vocab[n] = {s: i for i, s in enumerate(top["form"].to_list())}
    return vocab


def candidates(words: pl.DataFrame, vocab: Vocab) -> pl.DataFrame:
    """One row per vowel of each word: wid, idx and the FEATURES columns.

    ``words`` has columns wid (unique id), form, pos. Rows come out sorted by
    (wid, idx).
    """
    w = words.filter(pl.col("form").str.contains(_VOWEL_CLASS)).with_columns(
        n_chars=pl.col("form").str.len_chars().cast(pl.Int32))
    word_feats = w.select(
        "wid", "n_chars",
        *[_char_code(pl.col("form").str.slice(-k, 1)).alias(f"last{k}") for k in range(1, _LAST + 1)],
        *[pl.col("form").str.slice(-n).replace_strict(vocab[n], default=len(vocab[n]), return_dtype=pl.Int16)
          .alias(f"suf{n}") for n in _NGRAMS],
        pos=pl.col("pos").replace_strict(_POS_CODE, default=None, return_dtype=pl.Int16),
    )
    for k in range(1, _LAST + 1):   # past the word's start: padding
        word_feats = word_feats.with_columns(
            pl.when(pl.col("n_chars") >= k).then(pl.col(f"last{k}")).otherwise(_PAD).alias(f"last{k}"))
    chars = (
        w.select("wid", "n_chars", ch=pl.col("form").str.split(""),
                 idx=pl.int_ranges(0, pl.col("n_chars"), dtype=pl.Int32))
        .explode("ch", "idx")
        .with_columns(code=_char_code(pl.col("ch")), is_vowel=pl.col("ch").is_in(list(text.VOWELS)))
    )
    ctx = []
    for k in range(1, _C + 1):
        ctx.append(pl.when(pl.col("idx") >= k).then(pl.col("code").shift(k)).otherwise(_PAD).alias(f"m{k}"))
        ctx.append(pl.when(pl.col("idx") + k < pl.col("n_chars")).then(pl.col("code").shift(-k))
                   .otherwise(_PAD).alias(f"p{k}"))
    cum = pl.col("is_vowel").cast(pl.Int32).cum_sum().over("wid")
    total = pl.col("is_vowel").cast(pl.Int32).sum().over("wid")
    return (
        chars.with_columns(*ctx, vfe=total - cum, n_vowels=total, cfe=pl.col("n_chars") - 1 - pl.col("idx"))
        .filter(pl.col("is_vowel"))
        .with_columns(vowel=pl.col("code"))
        .drop("n_chars")
        .join(word_feats, on="wid", how="left", maintain_order="left")
        .select("wid", "idx", *FEATURES)
    )


def _matrix(cand: pl.DataFrame) -> np.ndarray:
    return cand.select(FEATURES).to_numpy().astype(np.float32)   # null POS -> NaN (missing)


def _classifier() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=config.MODEL_MAX_ITER, learning_rate=config.MODEL_LEARNING_RATE,
        max_leaf_nodes=config.MODEL_MAX_LEAF_NODES, categorical_features=[f in CATEGORICAL for f in FEATURES],
        max_bins=255, early_stopping=False, random_state=config.MODEL_SEED,
        l2_regularization=config.MODEL_L2_REGULARIZATION,
    )


def pick(scored: pl.DataFrame, temperature: float = 1.0) -> pl.DataFrame:
    """Per-candidate logits [wid, idx, score] → per word [wid, stress_idx, confidence].

    The best-scoring candidate wins (ties: the first vowel); its confidence is
    the softmax of the word's logits divided by ``temperature``.
    """
    s = pl.col("score") / temperature
    e = (s - s.max().over("wid")).exp()
    return (
        scored.with_columns(confidence=e / e.sum().over("wid"))
        .sort(["wid", "score", "idx"], descending=[False, True, False])
        .group_by("wid", maintain_order=True).first()
        .select("wid", stress_idx=pl.col("idx").cast(pl.Int16), confidence="confidence")
    )


def fit_temperature(scored: pl.DataFrame) -> float:
    """Temperature minimizing the log loss of the true candidate (column ``true``).

    The raw boosted logits are overconfident; dividing them by one fitted
    constant calibrates the confidences without changing any winner.
    """
    def loss(log_t: float) -> float:
        s = pl.col("score") / math.exp(log_t)
        m = s.max().over("wid")
        nll = (m + (s - m).exp().sum().over("wid").log() - s).filter(pl.col("true"))
        return scored.select(nll.mean()).item()

    res = minimize_scalar(loss, bounds=(-3.0, 4.0), method="bounded", options={"xatol": 1e-3})
    return round(math.exp(res.x), 3)


class Model:
    """A fitted per-vowel classifier, its suffix vocabulary and its temperature."""

    def __init__(self, train: pl.DataFrame, temperature: float = 1.0):
        """Fit on ``train`` [form, stress_idx, pos] (one row per form)."""
        train = train.select("form", "stress_idx", "pos").with_row_index("wid")
        self.n_train, self.temperature = train.height, temperature
        self.vocab = fit_vocab(train["form"])
        cand = candidates(train, self.vocab)
        stress = train.select("wid", "stress_idx")
        y = cand.join(stress, on="wid", how="left", maintain_order="left").select(
            pl.col("idx") == pl.col("stress_idx")).to_series().to_numpy()
        self.clf = _classifier().fit(_matrix(cand), y)

    def scores(self, words: pl.DataFrame) -> pl.DataFrame:
        """``words`` [wid, form, pos] → per-candidate logits [wid, idx, score]."""
        cand = candidates(words, self.vocab)
        logits = self.clf.decision_function(_matrix(cand)) if cand.height else []
        return cand.select("wid", "idx").with_columns(score=pl.Series(logits, dtype=pl.Float64))

    def predict(self, words: pl.DataFrame) -> pl.DataFrame:
        """``words`` [wid, form, pos] → [wid, stress_idx, confidence] (vowel-less words dropped)."""
        return pick(self.scores(words), self.temperature)


def training_set(readings: pl.DataFrame) -> pl.DataFrame:
    """[form, stress_idx, pos, group] for attested forms with one stress and no written accent."""
    return (
        readings.filter(
            (pl.col("tier") == "attested") & pl.col("stress_idx").is_not_null()
            & ~pl.col("form").str.contains(_ACCENT_CLASS) & pl.col("form").str.contains(_VOWEL_CLASS)
        )
        .group_by("form").agg(
            n=pl.col("stress_idx").n_unique(),
            stress_idx=pl.col("stress_idx").first(),
            pos=pl.col("pos").drop_nulls().mode().sort().first(),
            group=pl.col("lemma").drop_nulls().min(),
        )
        .filter(   # one stress, on a vowel
            (pl.col("n") == 1) & pl.col("form").str.slice(pl.col("stress_idx"), 1).is_in(list(text.VOWELS)))
        .with_columns(pl.col("group").fill_null(pl.col("form")))
        .select("form", "stress_idx", "pos", "group")
        .sort("form")
    )


def threshold(pos: pl.Expr) -> pl.Expr:
    """The confidence a prediction for ``pos`` needs to ship."""
    return pos.replace_strict(
        config.MODEL_MIN_CONFIDENCE_BY_POS, default=config.MODEL_MIN_CONFIDENCE, return_dtype=pl.Float64,
    ).fill_null(config.MODEL_MIN_CONFIDENCE)


def validate(train: pl.DataFrame) -> tuple[Model, pl.DataFrame]:
    """The shipped model, fitted without a held-out lemma-grouped slice of
    ``train``, and that slice's [form, pos, stress_idx, predicted, confidence]
    (the temperature is fitted on it)."""
    groups = train["group"].unique().sort()
    perm = np.random.default_rng(config.MODEL_SEED).permutation(groups.len())
    held_groups = groups.filter(pl.Series(perm % config.MODEL_FOLDS == 0))
    is_held = pl.col("group").is_in(held_groups.implode())
    rest = train.filter(~is_held)
    rng = np.random.default_rng(config.MODEL_SEED)
    fit = (   # seeded subsample, non-verbs first
        rest.with_columns(order=pl.Series(rng.permutation(rest.height)))
        .sort(pl.col("pos") == "verb", "order", nulls_last=False)
        .head(config.MODEL_MAX_TRAIN_FORMS).drop("order").sort("form")
    )
    model = Model(fit)
    held = train.filter(is_held).with_row_index("wid")
    scored = (
        model.scores(held.select("wid", "form", "pos"))
        .join(held.select("wid", "stress_idx"), on="wid", maintain_order="left")
        .with_columns(true=pl.col("idx") == pl.col("stress_idx")).drop("stress_idx")
    )
    model.temperature = fit_temperature(scored)
    cv = held.join(pick(scored, model.temperature).rename({"stress_idx": "predicted"}), on="wid",
                   maintain_order="left")
    return model, cv.select("form", "pos", "stress_idx", "predicted", "confidence")


def suggest_threshold(cv: pl.DataFrame, target: float = config.MODEL_TARGET_ACCURACY) -> float | None:
    """Lowest confidence (2 decimals) whose held-out accuracy above it reaches ``target``."""
    ok = (cv["predicted"] == cv["stress_idx"]).to_numpy()
    conf = cv["confidence"].to_numpy()
    for t in np.arange(0.0, 1.0, 0.01):
        sel = conf >= t
        if sel.any() and ok[sel].mean() >= target:
            return round(float(t), 2)
    return None


def _metrics(cv: pl.DataFrame, n_train: int, temperature: float) -> pl.DataFrame:
    """Held-out accuracy overall and above the POS thresholds, overall and for
    each POS of ``config.MODEL_MIN_CONFIDENCE_BY_POS``."""
    cv = cv.with_columns(ok=pl.col("predicted") == pl.col("stress_idx"),
                         sure=pl.col("confidence") >= threshold(pl.col("pos")))

    def stats(df: pl.DataFrame, suffix: str = "") -> dict:
        sure = df.filter("sure")
        return {
            f"cv_accuracy{suffix}": [df["ok"].mean()],
            f"cv_accuracy_confident{suffix}": [sure["ok"].mean() if sure.height else math.nan],
            f"coverage_confident{suffix}": [df["sure"].mean()],
        }

    out = {"n_train": [n_train], **stats(cv), "n_cv": [cv.height], "temperature": [temperature]}
    for pos in config.MODEL_MIN_CONFIDENCE_BY_POS:
        part = cv.filter(pl.col("pos") == pos)
        if part.height:
            out |= {f"n_cv_{pos}": [part.height], **stats(part, f"_{pos}")}
    return pl.DataFrame(out)


def predict(readings: pl.DataFrame, targets: pl.DataFrame) -> dict[str, pl.DataFrame]:
    """READINGS (attested + propagated) and targets [form, pos, lemma] →
    {"predictions": READINGS (tier "predicted"), "low_confidence", "metrics"}.

    Targets whose spelling ends in an accent get that stress directly, as tier
    "attested" with evidence "ortho". Predictions under their POS's threshold
    and targets without a vowel (null stress, confidence 0) go to
    ``low_confidence`` instead.
    """
    train = training_set(readings)
    if train["group"].n_unique() < config.MODEL_FOLDS:
        raise ValueError(f"model: {train.height} training forms are too few to train on")
    start = time.perf_counter()
    model, cv = validate(train)
    log.info("model: fit on %d forms, %d held out, temperature %.3f, in %.1f s",
             model.n_train, cv.height, model.temperature, time.perf_counter() - start)
    for pos in cv["pos"].drop_nulls().unique().sort():
        part = cv.filter(pl.col("pos") == pos)
        log.info("model: %s: %d held out; threshold for %.0f%% accuracy: %s",
                 pos, part.height, config.MODEL_TARGET_ACCURACY * 100, suggest_threshold(part))
    metrics = _metrics(cv, model.n_train, model.temperature)

    words = targets.select("form", "pos", "lemma").unique().sort("form", "pos", "lemma", nulls_last=True)
    ortho = [text.orthographic_stress(f) for f in words["form"].to_list()]
    has_ortho = pl.Series([o is not None for o in ortho], dtype=pl.Boolean)
    found = [o for o in ortho if o is not None]
    written = words.filter(has_ortho).with_columns(
        stress_idx=pl.Series([o[0] for o in found], dtype=pl.Int16),
        quality=pl.Series([o[1] for o in found], dtype=pl.String),
        tier=pl.lit("attested"), confidence=pl.lit(1.0), evidence=pl.lit("ortho"),
        sources=pl.lit([], pl.List(pl.String)),
    )
    words = words.filter(~has_ortho).with_row_index("wid")
    guessed = words.join(model.predict(words.select("wid", "form", "pos")), on="wid", how="left").with_columns(
        pl.col("confidence").fill_null(0.0), quality=pl.lit(None, pl.String), tier=pl.lit("predicted"),
        evidence=pl.lit("none"), sources=pl.lit(["model"]),
    )
    sure = guessed["confidence"] >= guessed.select(threshold(pl.col("pos"))).to_series()
    predictions = pl.concat([
        schema.conform(guessed.filter(sure), schema.READINGS), schema.conform(written, schema.READINGS),
    ]).sort("form", "pos", "lemma", nulls_last=True)
    low = (   # minus the stresses that ship under another POS of the form
        guessed.filter(~sure).join(predictions, on=["form", "stress_idx"], how="anti")
        .group_by("form", "stress_idx").agg(pl.col("confidence").max())
        .sort("form", "stress_idx", nulls_last=True)
    )
    return {"predictions": predictions, "low_confidence": low, "metrics": metrics}
