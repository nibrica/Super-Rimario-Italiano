"""Tests for rimario_build.text: normalization, tokenization, stress marks."""

import unicodedata

import pytest
import wordfreq

from rimario_build import text

NFD = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731


# --- norm / is_allowed ------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [
    ("casa", "casa"),
    ("CITTÀ", "città"),
    ("Perché", "perché"),
    ("É", "é"),
    (NFD("città"), "città"),
    (NFD("PERCHÉ"), "perché"),
    ("", ""),
])
def test_norm(raw, expected):
    assert text.norm(raw) == expected
    assert unicodedata.is_normalized("NFC", text.norm(raw))


def test_norm_makes_accented_vowels_one_code_point():
    assert len(text.norm(NFD("città"))) == 5


@pytest.mark.parametrize("form", [
    "casa", "città", "perché", "più", "è", "kiwi", "weekend", "àèéìíòóùú",
])
def test_is_allowed(form):
    assert text.is_allowed(form)


@pytest.mark.parametrize("form", [
    "",                # empty
    "Casa",            # not lowercase
    "dell'anfibio",    # apostrophe
    "po'",
    "ab-ovo",          # hyphen
    "due parole",      # space
    "casa2",           # digit
    "naïve",           # diaeresis
    "über",
    "señor",
    "á",               # not used in Italian spelling, not in ALLOWED_CHARS
    NFD("città"),      # decomposed accent
])
def test_is_not_allowed(form):
    assert not text.is_allowed(form)


# --- tokenize ---------------------------------------------------------------------


@pytest.mark.parametrize("sentence", [
    "C'è un po' di caffè. Perché?",
    "L'amico dell'anfibio e quell'uomo all'improvviso.",
    "Nel 2024 la città è cresciuta del 3,5%!",
    "«Dimmelo», disse: \"portandoglielo\" — sùbito.",
    NFD("Città PERCHÉ più"),
])
def test_tokenize_matches_wordfreq(sentence):
    assert text.tokenize(sentence) == wordfreq.tokenize(sentence, "it")


def test_tokenize_lowercases_and_drops_punctuation():
    assert text.tokenize("Città, PERCHÉ? Più!") == ["città", "perché", "più"]


def test_tokenize_nfc():
    assert text.tokenize(NFD("città")) == ["città"]


@pytest.mark.parametrize(("sentence", "expected"), [
    ("l'amico", ["l", "amico"]),
    ("L'anima", ["l", "anima"]),
    ("c'è", ["c", "è"]),
    ("un po' di", ["un", "po", "di"]),
    # wordfreq 3.1.1 splits single-letter elisions only: longer elided
    # articles and prepositions stay attached to the next word.
    ("dell'anfibio", ["dell'anfibio"]),
    ("quell'uomo", ["quell'uomo"]),
    ("all'improvviso", ["all'improvviso"]),
])
def test_tokenize_elisions(sentence, expected):
    assert text.tokenize(sentence) == expected


# --- vowel / accent positions, strip_accents -------------------------------------


@pytest.mark.parametrize(("form", "expected"), [
    ("casa", [1, 3]),
    ("aiuola", [0, 1, 2, 3, 5]),
    ("città", [1, 4]),
    ("perché", [1, 5]),
    ("strz", []),
    ("", []),
])
def test_vowel_positions(form, expected):
    assert text.vowel_positions(form) == expected


@pytest.mark.parametrize(("form", "expected"), [
    ("casa", []),
    ("città", [4]),
    ("perché", [5]),
    ("càpitàno", [1, 5]),
    ("è", [0]),
])
def test_accent_positions(form, expected):
    assert text.accent_positions(form) == expected


@pytest.mark.parametrize(("form", "expected"), [
    ("città", "citta"),
    ("perché", "perche"),
    ("pèsca", "pesca"),
    ("àèéìíòóùú", "aeeiioouu"),
    ("casa", "casa"),
])
def test_strip_accents(form, expected):
    stripped = text.strip_accents(form)
    assert stripped == expected
    assert len(stripped) == len(form)   # indexes are preserved


# --- orthographic_stress ------------------------------------------------------------


@pytest.mark.parametrize(("form", "expected"), [
    ("città", (4, None)),
    ("perché", (5, "closed")),
    ("caffè", (4, "open")),
    ("più", (2, None)),
    ("è", (0, "open")),
    # A non-final accent is a stress mark or a foreign accent, not spelling.
    ("pésca", None),
    ("ancòra", None),
    ("élite", None),
    ("casa", None),
    ("càpitàno", None),      # more than one accent: no single stress
    ("", None),
])
def test_orthographic_stress(form, expected):
    assert text.orthographic_stress(form) == expected


@pytest.mark.parametrize(("form", "expected"), [
    ("città", (4, None)),
    ("pésca", (1, "closed")),
    ("ancòra", (3, "open")),
    ("casa", None),
    ("càpitàno", None),
])
def test_marked_stress(form, expected):
    assert text.marked_stress(form) == expected


# --- mark_stress -------------------------------------------------------------------


@pytest.mark.parametrize(("form", "idx", "quality", "expected"), [
    ("casa", 1, None, "càsa"),
    ("capitano", 1, None, "càpitano"),
    ("capitano", 5, None, "capitàno"),
    ("ancora", 0, None, "àncora"),
    ("ancora", 3, None, "ancòra"),
    ("subito", 3, None, "subìto"),
    ("virtu", 4, None, "virtù"),
    # e/o: a grave accent when the quality is unknown, else the quality's accent.
    ("pesca", 1, None, "pèsca"),
    ("pesca", 1, "open", "pèsca"),
    ("pesca", 1, "closed", "pésca"),
    ("amore", 2, "closed", "amóre"),
    ("botte", 1, "open", "bòtte"),
    # An accent already in the spelling is kept unless the quality contradicts it.
    ("città", 4, None, "città"),
    ("perché", 5, None, "perché"),
    ("perché", 5, "closed", "perché"),
    ("caffè", 4, "open", "caffè"),
    ("perché", 5, "open", "perchè"),
    ("perchè", 5, "closed", "perché"),
    ("pésca", 1, "open", "pèsca"),
    ("è", 0, None, "è"),
])
def test_mark_stress(form, idx, quality, expected):
    assert text.mark_stress(form, idx, quality) == expected


@pytest.mark.parametrize(("form", "idx"), [
    ("casa", 0),      # consonant
    ("casa", 2),
    ("strz", 1),
])
def test_mark_stress_rejects_consonants(form, idx):
    with pytest.raises(ValueError, match="not a vowel"):
        text.mark_stress(form, idx)


@pytest.mark.parametrize(("form", "idx", "quality"), [
    ("casa", 1, "open"),
    ("città", 4, "closed"),
    ("virtù", 4, "open"),
])
def test_mark_stress_quality_on_a_i_u(form, idx, quality):
    # Either ignoring the meaningless quality or a ValueError would be fine;
    # check the tolerant behaviour.
    assert text.mark_stress(form, idx, quality) == text.mark_stress(form, idx)


def test_mark_stress_round_trips_with_resolve_spelling():
    for form, idx, quality in [("capitano", 1, None), ("capitano", 5, None),
                               ("pesca", 1, "closed"), ("città", 4, None),
                               ("perché", 5, "closed"), ("amore", 2, "closed")]:
        marked = text.mark_stress(form, idx, quality)
        assert text.resolve_spelling(marked) == (form, idx, quality)


# --- resolve_spelling ---------------------------------------------------------------


@pytest.mark.parametrize(("marked", "expected"), [
    # Oxytone polysyllables keep their written accent.
    ("città", ("città", 4, None)),
    ("perché", ("perché", 5, "closed")),
    ("caffè", ("caffè", 4, "open")),
    ("virtù", ("virtù", 4, None)),
    ("più", ("più", 2, None)),
    ("già", ("già", 2, None)),
    ("ciò", ("ciò", 2, "open")),
    ("venderò", ("venderò", 6, "open")),
    # Any other stress mark is a dictionary mark and is dropped.
    ("càpitano", ("capitano", 1, None)),
    ("capitàno", ("capitano", 5, None)),
    ("àncora", ("ancora", 0, None)),
    ("ancòra", ("ancora", 3, "open")),
    ("pèsca", ("pesca", 1, "open")),
    ("pésca", ("pesca", 1, "closed")),
    ("dìmmelo", ("dimmelo", 1, None)),
    ("portàndoglielo", ("portandoglielo", 4, None)),
    ("puòi", ("puoi", 2, "open")),
    # Without is_known a monosyllable can't be told apart (dà vs da): no accent.
    ("dà", ("da", 1, None)),
    ("dò", ("do", 1, "open")),
    ("è", ("e", 0, "open")),
    # Input is normalized first.
    ("Città", ("città", 4, None)),
    (NFD("càpitano"), ("capitano", 1, None)),
])
def test_resolve_spelling_without_is_known(marked, expected):
    assert text.resolve_spelling(marked) == expected


@pytest.mark.parametrize("marked", ["casa", "", "càpitàno", "àncòra"])
def test_resolve_spelling_needs_exactly_one_accent(marked):
    assert text.resolve_spelling(marked) is None
    assert text.resolve_spelling(marked, lambda _: True) is None


KNOWN = frozenset({
    "città", "perché", "più", "dà", "da", "do", "è", "e",
    "capitano", "pesca", "ancora", "dimmelo",
})


@pytest.mark.parametrize(("marked", "expected"), [
    ("città", ("città", 4, None)),
    ("perché", ("perché", 5, "closed")),
    ("più", ("più", 2, None)),
    # Both dà and da are real: the marked candidate is tried first.
    ("dà", ("dà", 1, None)),
    ("è", ("è", 0, "open")),
    # dò is not a real spelling (the verb is written do).
    ("dò", ("do", 1, "open")),
    ("càpitano", ("capitano", 1, None)),
    ("capitàno", ("capitano", 5, None)),
    ("pèsca", ("pesca", 1, "open")),
    ("pésca", ("pesca", 1, "closed")),
    ("àncora", ("ancora", 0, None)),
    ("dìmmelo", ("dimmelo", 1, None)),
])
def test_resolve_spelling_with_is_known(marked, expected):
    assert text.resolve_spelling(marked, KNOWN.__contains__) == expected


@pytest.mark.parametrize("marked", ["càsa", "lunedì", "perchè", "xyzà"])
def test_resolve_spelling_unknown_is_none(marked):
    # Neither the marked spelling nor the stripped one is known.
    assert text.resolve_spelling(marked, KNOWN.__contains__) is None


def test_resolve_spelling_is_known_overrides_the_oxytone_guess():
    # A known stripped spelling wins over the "keep the final accent" guess...
    assert text.resolve_spelling("venderò", {"vendero"}.__contains__) == ("vendero", 6, "open")
    # ...and a known marked spelling wins over dropping a non-final accent.
    assert text.resolve_spelling("àncora", {"àncora", "ancora"}.__contains__) == ("àncora", 0, None)


def test_resolve_spelling_calls_is_known_with_normalized_candidates():
    seen = []
    text.resolve_spelling(NFD("CÀPITANO"), lambda c: seen.append(c) or False)
    assert seen == ["càpitano", "capitano"]


@pytest.mark.parametrize(("marked", "expected"), [
    ("hotèl", ("hotel", 3, "open")),
    ("nobèl", ("nobel", 3, "open")),
    ("bazàr", ("bazar", 3, None)),
])
def test_resolve_spelling_final_consonant_drops_accent(marked, expected):
    assert text.resolve_spelling(marked) == expected
