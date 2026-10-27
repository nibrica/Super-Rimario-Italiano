"""Text normalization, tokenization and stress-mark <-> index conversion."""

import unicodedata
from collections.abc import Callable

from wordfreq import tokenize as _wordfreq_tokenize

from . import config

VOWELS = frozenset("aeiouàèéìíòóùú")

# Accented vowel -> (base vowel, quality of the stressed vowel).
ACCENTED = {
    "à": ("a", None), "á": ("a", None),
    "è": ("e", "open"), "é": ("e", "closed"),
    "ì": ("i", None), "í": ("i", None),
    "ò": ("o", "open"), "ó": ("o", "closed"),
    "ù": ("u", None), "ú": ("u", None),
}

# Base vowel + quality -> accented vowel, for marking a stress in display.
MARK = {
    ("a", None): "à", ("i", None): "ì", ("u", None): "ù",
    ("e", None): "è", ("e", "open"): "è", ("e", "closed"): "é",
    ("o", None): "ò", ("o", "open"): "ò", ("o", "closed"): "ó",
}


def norm(s: str) -> str:
    """NFC + lowercase, the canonical form of every spelling in the build."""
    return unicodedata.normalize("NFC", s).lower()


# Regex for a whole spelling made of config.ALLOWED_CHARS (is_allowed, vectorized).
ALLOWED_RE = "^[" + "".join(sorted(config.ALLOWED_CHARS)) + "]+$"


def is_allowed(form: str) -> bool:
    """True if ``form`` is a non-empty word made only of config.ALLOWED_CHARS."""
    return bool(form) and all(c in config.ALLOWED_CHARS for c in form)


def tokenize(text: str) -> list[str]:
    """Split text exactly like wordfreq does for Italian."""
    return _wordfreq_tokenize(text, "it")


def vowel_positions(form: str) -> list[int]:
    return [i for i, c in enumerate(form) if c in VOWELS]


def accent_positions(form: str) -> list[int]:
    return [i for i, c in enumerate(form) if c in ACCENTED]


def strip_accents(form: str) -> str:
    """Replace accented vowels by their base vowel; indexes are preserved."""
    return "".join(ACCENTED[c][0] if c in ACCENTED else c for c in form)


def marked_stress(form: str) -> tuple[int, str | None] | None:
    """The single accent mark anywhere in ``form`` (càpitano, città): (index, quality)."""
    marks = accent_positions(form)
    if len(marks) != 1:
        return None
    i = marks[0]
    return i, ACCENTED[form[i]][1]


def orthographic_stress(form: str) -> tuple[int, str | None] | None:
    """Stress written in a real spelling (città, perché, è): (index, quality).

    Italian spelling writes an accent only on a word-final stressed vowel. A
    non-final accent is a dictionary stress mark (àncora) or a foreign accent
    (élite, décor), not evidence of stress, so it gives None.
    """
    stress = marked_stress(form)
    return stress if stress and stress[0] == len(form) - 1 else None


def mark_stress(form: str, stress_idx: int, quality: str | None = None) -> str:
    """Return ``form`` with an accent on the stressed vowel (for display)."""
    c = form[stress_idx]
    if c in ACCENTED:
        base, written_quality = ACCENTED[c]
        if quality is None or quality == written_quality:
            return form
        c = base
    if c not in "aeiou":
        raise ValueError(f"{form!r}: index {stress_idx} is not a vowel")
    if c in "aiu":
        quality = None              # only e and o have an open/closed quality
    return form[:stress_idx] + MARK[(c, quality)] + form[stress_idx + 1:]


def resolve_spelling(
    marked: str, is_known: Callable[[str], bool] | None = None
) -> tuple[str, int, str | None] | None:
    """Turn a stress-marked dictionary spelling into (form, stress_idx, quality).

    ``marked`` carries exactly one accent on the stressed vowel (``càpitano``,
    ``perché``, ``dò``). The real spelling is chosen among the marked string
    itself and the string with the mark removed, never by blindly stripping
    every accent, so orthographic ones survive:

    1. a candidate that ``is_known`` accepts wins, the marked one first;
    2. without a known candidate, a polysyllable ending in its stressed vowel
       keeps the accent (Italian spelling writes it), anything else drops it
       (``hotèl`` -> ``hotel``);
       with ``is_known`` given, that guess must be known too, else None.

    Returns None if ``marked`` has no accent or more than one.
    """
    marked = norm(marked)
    stress = marked_stress(marked)
    if stress is None:
        return None
    idx, quality = stress
    stripped = strip_accents(marked)
    if is_known is not None:
        for candidate in (marked, stripped):
            if is_known(candidate):
                return candidate, idx, quality
        return None
    if idx == len(marked) - 1 and len(vowel_positions(marked)) > 1:
        return marked, idx, quality
    return stripped, idx, quality
