"""Leipzig news sentences: counts, capitalization and cue contexts (source "leipzig_news").

The newest ``ita_news_<year>_1M.tar.gz`` on disk is streamed; only its
``*-sentences.txt`` member (``id\\tsentence``) is read, nothing is extracted.
Sentences are tokenized in parallel chunks exactly like wordfreq (``text.tokenize``).
"""

import re
import tarfile
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from itertools import batched
from pathlib import Path

import polars as pl
from wordfreq.tokens import TOKEN_RE, uncurl_quotes

from .. import config, schema, text
from .freq import from_counts

SOURCE = "leipzig_news"

# (form, cue, case) for one word token; case is "cap" (capitalized, not
# sentence-initial, not all caps), "lower" (all lowercase) or None (unknown).
Token = tuple[str, str | None, str | None]


def find_tarball(raw_dir: Path) -> Path:
    """The newest-year Leipzig tarball in ``raw_dir``."""
    years = {
        int(m[1]): p for p in raw_dir.iterdir() if (m := re.fullmatch(config.LEIPZIG_TARBALL_RE, p.name))
    }
    if not years:
        raise FileNotFoundError(f"no Leipzig news tarball in {raw_dir}")
    return years[max(years)]


def read_sentences(path: Path) -> Iterator[str]:
    """Stream the lines of the single ``*-sentences.txt`` member of ``path``."""
    with tarfile.open(path, "r|gz") as tar:
        for member in tar:
            if member.name.endswith(config.LEIPZIG_SENTENCES_SUFFIX):
                member = tarfile.data_filter(member, str(path.parent))   # rejects unsafe members
                if not member.isfile():
                    break
                for line in tar.extractfile(member):
                    yield line.decode("utf-8")
                return
    raise ValueError(f"{path.name}: no regular *{config.LEIPZIG_SENTENCES_SUFFIX} member")


def _case(word: str, initial: bool) -> str | None:
    """"lower" if all lowercase; "cap" for a capital initial that is not
    sentence-initial nor all caps (headlines, acronyms); else None."""
    if word.islower():
        return "lower"
    if word[:1].isupper() and not initial and not (len(word) > 1 and word.isupper()):
        return "cap"
    return None


def _cue(elided: str) -> str:
    return config.ELIDED_CUES.get(elided, elided)


def scan(sentence: str) -> list[Token]:
    """Word tokens of one raw sentence.

    Tokens are ``text.tokenize``'s, on the sentence with curly apostrophes
    straightened as in wordfreq's own data (``l’ultimo`` -> ``l``, ``ultimo``).
    A token still holding an apostrophe (``dell'uomo``, ``quest'anno``) yields
    its right-hand word, cued by the elided word (config.ELIDED_CUES).
    Otherwise the cue is the previous token if only whitespace separates them
    (an elided ``l'``/``c'``/``un'`` is mapped too). A capitalized word gets no
    cue (*Noi Moderati*, *la Viola*: names, whose cues say nothing about the
    common readings). Casing comes from the same regex split of the
    uncasefolded sentence; if it doesn't match the tokenizer, the sentence
    yields no cues and no casing.
    """
    sentence = unicodedata.normalize("NFC", uncurl_quotes(sentence))
    tokens = text.tokenize(sentence)
    matches = list(TOKEN_RE.finditer(sentence))
    if len(matches) != len(tokens) or any(
        m.group().strip("'").casefold() != t for m, t in zip(matches, tokens)
    ):
        return [(t.rpartition("'")[2], None, None) for t in tokens]
    out: list[Token] = []
    prev, prev_end = None, 0
    for i, (m, token) in enumerate(zip(matches, tokens)):
        gap = sentence[prev_end:m.start()]
        cased = m.group().strip("'")
        if "'" in token:
            left, _, word = token.rpartition("'")
            cased, cue, initial = cased.rpartition("'")[2], _cue(left.rpartition("'")[2]), False
        else:
            word, cue = token, None if gap.strip() else prev
            initial = i == 0 or not config.SENTENCE_BREAK_CHARS.isdisjoint(gap)
        out.append((word, None if cased[:1].isupper() else cue, _case(cased, initial)))
        prev = _cue(token) if "'" not in token and m.group().endswith("'") else word
        prev_end = m.end()
    return out


def count_lines(lines: Iterable[str]) -> tuple[int, pl.DataFrame, pl.DataFrame]:
    """(all tokens, FREQ-like (form, count, cap_count, lower_count), CONTEXTS) for ``id\\tsentence`` lines."""
    counts: Counter[str] = Counter()
    cases: Counter[tuple[str, str]] = Counter()
    contexts: Counter[tuple[str, str]] = Counter()
    for line in lines:
        for word, cue, case in scan(line.partition("\t")[2]):
            counts[word] += 1
            if case:
                cases[word, case] += 1
            if cue in config.CUE_CANDIDATES:
                contexts[word, cue] += 1
    forms = [w for w in counts if text.is_allowed(w)]
    freq = pl.DataFrame(
        {"form": forms, "count": [counts[w] for w in forms],
         "cap_count": [cases[w, "cap"] for w in forms], "lower_count": [cases[w, "lower"] for w in forms]},
        schema={"form": pl.String, "count": pl.Int64, "cap_count": pl.Int64, "lower_count": pl.Int64},
    )
    rows = [(w, c, n) for (w, c), n in contexts.items() if text.is_allowed(w)]
    ctx = pl.DataFrame(rows, schema=schema.CONTEXTS, orient="row")
    return counts.total(), freq, ctx


def extract(raw_dir: Path) -> dict[str, pl.DataFrame]:
    """FREQ, FREQ_META and CONTEXTS from the newest Leipzig news tarball."""
    lines = batched(read_sentences(find_tarball(raw_dir)), config.LEIPZIG_CHUNK_LINES)
    with ProcessPoolExecutor(config.MAX_WORKERS) as pool:
        parts = list(pool.map(count_lines, lines))
    total = sum(n for n, _, _ in parts)
    freq = pl.concat([f for _, f, _ in parts])
    contexts = (
        pl.concat([c for _, _, c in parts]).group_by("form", "cue").agg(pl.col("count").sum()).sort("form", "cue")
    )
    return from_counts(freq, total, SOURCE, min_count=1) | {"contexts": schema.conform(contexts, schema.CONTEXTS)}
