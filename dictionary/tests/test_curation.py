"""Curation files: well-formed, and the build meets the gold / freq-pair thresholds.

The loaders (``lexicon.load_overrides``, ``report.load_gold``,
``report.load_freq_pairs``) validate fields, stress indexes and actions; the
format tests add only what they don't check. The accuracy checks need
``web/parole-accenti-frequenze.csv`` and skip without it.
"""

from collections import Counter
from pathlib import Path

import polars as pl

from rimario_build import config, lexicon, report, text


def _header(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                return line.rstrip("\n").split("\t")
    return []


def _raw(path: Path, columns: dict) -> list[dict[str, str]]:
    """Data rows as written (not normalized), padded to ``columns``."""
    return [dict(zip(columns, fields)) for _, _, fields in lexicon.read_tsv(path, columns)]


def _form_problem(form: str) -> str | None:
    if form != text.norm(form):
        return "not NFC lowercase"
    if not text.is_allowed(form):
        return "characters outside config.ALLOWED_CHARS"
    return None


def _report(problems: list[str]) -> str:
    return f"{len(problems)} problem(s):\n" + "\n".join(problems)


def _misses(misses: pl.DataFrame) -> str:
    return "\n".join(str(row) for row in misses.iter_rows(named=True))


# --- Format ------------------------------------------------------------------


def test_gold_format():
    assert _header(config.GOLD_TSV) == list(report.GOLD)
    gold = report.load_gold(config.GOLD_TSV)
    assert gold.height, "gold.tsv has no rows"
    problems = []
    for n, row in enumerate(_raw(config.GOLD_TSV, report.GOLD), 1):
        where = f"row {n} {row['form']!r}"
        problem = _form_problem(row["form"])
        if problem is None and row["note"]:
            # The note starts with the stress-marked form: check they agree.
            marked = row["note"].split(" ", 1)[0]
            idx = int(row["stress_idx"])
            if (text.strip_accents(marked) != text.strip_accents(row["form"])
                    or text.accent_positions(marked) != [idx]):
                problem = f"note starts with {marked!r}, which disagrees with stress_idx {idx}"
        if problem:
            problems.append(f"{where}: {problem}")
    keys = Counter(gold.select("form", "stress_idx").rows())
    problems += [f"duplicate row {key}" for key, n in sorted(keys.items()) if n > 1]
    defaults = Counter(gold.filter(pl.col("default"))["form"])
    problems += [f"{form!r}: more than one default=1 row" for form, n in sorted(defaults.items()) if n > 1]
    assert not problems, _report(problems)


def test_freq_pairs_format():
    assert _header(config.FREQ_PAIRS_TSV) == list(report.FREQ_PAIRS)
    pairs = report.load_freq_pairs(config.FREQ_PAIRS_TSV)
    assert pairs.height, "freq_pairs.tsv has no rows"
    problems = []
    for n, row in enumerate(_raw(config.FREQ_PAIRS_TSV, report.FREQ_PAIRS), 1):
        for column in ("more", "less"):
            if problem := _form_problem(row[column]):
                problems.append(f"row {n} {column} {row[column]!r}: {problem}")
        if row["more"] == row["less"]:
            problems.append(f"row {n}: {row['more']!r} compared with itself")
    keys = Counter(pairs.select("more", "less").rows())
    problems += [f"duplicate pair {pair}" for pair, n in sorted(keys.items()) if n > 1]
    problems += [f"contradictory pairs {pair} and its reverse"
                 for pair in sorted(keys) if pair[::-1] in keys and pair < pair[::-1]]
    assert not problems, _report(problems)


def test_overrides_format():
    assert _header(config.OVERRIDES_TSV) == list(lexicon.OVERRIDES)
    overrides = lexicon.load_overrides(config.OVERRIDES_TSV)
    problems = [f"row {n} {row['form']!r}: not NFC lowercase"
                for n, row in enumerate(_raw(config.OVERRIDES_TSV, lexicon.OVERRIDES), 1)
                if row["form"] != text.norm(row["form"])]
    keys = Counter(overrides.select("form", "stress_idx", "action").rows())
    problems += [f"duplicate override {key}" for key, n in sorted(keys.items()) if n > 1]
    assert not problems, _report(problems)


# --- Accuracy against the build -------------------------------------------------


def test_gold_accuracy(built_rows):
    gold = report.load_gold(config.GOLD_TSV)
    accuracy, misses = report.gold_accuracy(built_rows, gold)
    assert accuracy >= config.GOLD_MIN_ACCURACY, (
        f"gold accuracy {accuracy:.3f} < {config.GOLD_MIN_ACCURACY}; "
        f"{misses.height} miss(es):\n{_misses(misses)}"
    )


def test_freq_pair_agreement(built_rows):
    pairs = report.load_freq_pairs(config.FREQ_PAIRS_TSV)
    agreement, misses = report.freq_pair_agreement(built_rows, pairs)
    assert agreement >= config.FREQ_PAIRS_MIN_AGREEMENT, (
        f"freq-pair agreement {agreement:.3f} < {config.FREQ_PAIRS_MIN_AGREEMENT}; "
        f"{misses.height} miss(es):\n{_misses(misses)}"
    )
