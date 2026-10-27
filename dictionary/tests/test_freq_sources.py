"""Frequency extractors: wordfreq_it, opensubtitles, leipzig."""

import io
import math
import tarfile
from pathlib import Path

import polars as pl
import pytest

from rimario_build import config, schema
from rimario_build.sources import leipzig, opensubtitles, wordfreq_it


def zipf(count: float, total: float) -> float:
    return math.log10(count / total * 1e9)


def as_dict(freq: pl.DataFrame, col: str) -> dict:
    return dict(freq.select("form", col).iter_rows())


# --- wordfreq ---------------------------------------------------------------

def test_wordfreq_merges_and_filters():
    out = wordfreq_it.from_frequencies({
        "città": 1e-6, "Citta\u0300": 1e-6,          # NFC + case variants merge
        "dell'uomo": 1e-5, "uomo": 1e-5, "po'": 1e-5, "2024": 1e-5, "москва": 1e-5, "e-mail": 1e-5,
        "ciao": 10 ** -7.99,
    })
    freq, meta = out["freq"], out["meta"]
    assert freq.schema == pl.Schema(schema.FREQ)
    assert freq["form"].to_list() == ["ciao", "città", "uomo"]       # dell'uomo counts for uomo
    assert as_dict(freq, "zipf") == {"ciao": 1.01, "città": round(zipf(2e-6, 1), 2), "uomo": round(zipf(2e-5, 1), 2)}
    assert freq["count"].null_count() == freq["cap_count"].null_count() == freq["lower_count"].null_count() == 3
    assert meta.row(0, named=True) == {
        "source": "wordfreq", "total_tokens": None, "floor_zipf": 1.01, "complete": True, "truncated": True,
    }


def test_wordfreq_real_list():
    out = wordfreq_it.extract(Path("unused"))
    freq = out["freq"]
    assert freq.height > 250_000
    assert out["meta"]["floor_zipf"][0] == pytest.approx(1.0, abs=0.02)
    assert freq["zipf"].min() >= out["meta"]["floor_zipf"][0]
    assert not freq["form"].str.contains("[^" + "".join(config.ALLOWED_CHARS) + "]").any()
    assert as_dict(freq, "zipf")["ancora"] > 5


# --- opensubtitles ----------------------------------------------------------

def write_subs(tmp_path: Path, body: str) -> Path:
    (tmp_path / config.OPENSUBTITLES_FILE).write_text(body, encoding="utf-8")
    return tmp_path


def test_opensubtitles(tmp_path):
    raw = write_subs(tmp_path, "e 10\nPerché 3\nperche\u0301 2\nl'uomo 4\n2024 5\nрусский 1\ntrauma-tizio 2\n")
    out = opensubtitles.extract(raw)
    freq, meta = out["freq"], out["meta"].row(0, named=True)
    total = 27
    assert out["freq"].schema == pl.Schema(schema.FREQ)
    assert as_dict(freq, "count") == {"e": 10, "perché": 5}
    assert as_dict(freq, "zipf")["perché"] == pytest.approx(zipf(5, total))
    assert freq["cap_count"].null_count() == freq["lower_count"].null_count() == 2
    assert meta == {
        "source": "opensubtitles", "total_tokens": total, "floor_zipf": pytest.approx(zipf(1, total)),
        "complete": True, "truncated": False,
    }


def test_opensubtitles_truncated(tmp_path):
    meta = opensubtitles.extract(write_subs(tmp_path, "e 10\nma 4\n"))["meta"].row(0, named=True)
    assert meta["truncated"] and meta["floor_zipf"] == pytest.approx(zipf(4, 14))


# --- leipzig: scanning ------------------------------------------------------

def test_elided_cues_are_candidates():
    assert set(config.ELIDED_CUES.values()) <= config.CUE_CANDIDATES


def test_scan_elisions():
    tokens = leipzig.scan("Dell’uomo, un’altra quest'anno c’è l’ancora nell'ex-Ilva")
    assert [(w, c) for w, c, _ in tokens] == [
        ("uomo", "della"), ("un", None), ("altra", "una"), ("anno", "questa"),
        ("c", "anno"), ("è", "ci"), ("l", "è"), ("ancora", "l"), ("ex", "nella"), ("ilva", None),
    ]


def test_scan_cues_need_adjacency():
    tokens = leipzig.scan("Il capitano, subito non subito")
    assert [(w, c) for w, c, _ in tokens] == [
        ("il", None), ("capitano", "il"), ("subito", None), ("non", "subito"), ("subito", "non"),
    ]


def test_scan_casing():
    sentence = 'Rosa vide Rosa. Rosa disse: Rosa "Rosa" ROSA rosa dell\'Italia l’Italia (Rosa) 2024'
    cases = [(w, case) for w, _, case in leipzig.scan(sentence)]
    assert cases == [
        ("rosa", None), ("vide", "lower"), ("rosa", "cap"), ("rosa", None), ("disse", "lower"),
        ("rosa", None), ("rosa", None), ("rosa", None), ("rosa", "lower"),
        ("italia", "cap"), ("l", "lower"), ("italia", "cap"), ("rosa", "cap"), ("2024", None),
    ]


def test_scan_capitalized_word_gets_no_cue():
    tokens = leipzig.scan("Noi Moderati e noi moderati, la Viola e l'Ambito")
    assert [(w, c) for w, c, _ in tokens] == [
        ("noi", None), ("moderati", None), ("e", "moderati"), ("noi", "e"), ("moderati", "noi"),
        ("la", None), ("viola", None), ("e", "viola"), ("l", "e"), ("ambito", None),
    ]


# --- leipzig: extract -------------------------------------------------------

def make_tarball(raw_dir: Path, year: int, sentences: list[str], symlink: bool = False) -> None:
    name = f"ita_news_{year}_1M"
    with tarfile.open(raw_dir / f"{name}.tar.gz", "w:gz") as tar:
        def add(member: str, data: bytes) -> None:
            info = tarfile.TarInfo(f"{name}/{member}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add(f"{name}-words.txt", b"1\tdecoy\t99\n")
        if symlink:
            info = tarfile.TarInfo(f"{name}/{name}-sentences.txt")
            info.type, info.linkname = tarfile.SYMTYPE, f"{name}-words.txt"
            tar.addfile(info)
        else:
            body = "".join(f"{i}\t{s}\n" for i, s in enumerate(sentences, 1))
            add(f"{name}-sentences.txt", body.encode())


SENTENCES = [
    "Il capitano non capitano mai.",
    "La Viola gioca: la viola suona, Rosa no.",
    "Dell'uomo resta l’ancora 2024!",
    "Rosa e rosa, PERCHÉ?",
]


def test_leipzig_extract(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEIPZIG_CHUNK_LINES", 2)          # several chunks
    make_tarball(tmp_path, 2022, ["vecchio vecchio vecchio"])
    make_tarball(tmp_path, 2024, SENTENCES)
    out = leipzig.extract(tmp_path)
    freq, meta, ctx = out["freq"], out["meta"].row(0, named=True), out["contexts"]
    total = 5 + 8 + 5 + 4                      # dell'uomo -> 1 token, "2024" counted
    assert freq.schema == pl.Schema(schema.FREQ) and ctx.schema == pl.Schema(schema.CONTEXTS)
    assert "vecchio" not in freq["form"] and "dell" not in freq["form"] and "2024" not in freq["form"]
    counts, caps, lower = as_dict(freq, "count"), as_dict(freq, "cap_count"), as_dict(freq, "lower_count")
    assert counts["capitano"] == 2 and counts["rosa"] == 3 and counts["viola"] == 2 and counts["perché"] == 1
    assert caps["viola"] == 1 and caps["rosa"] == 1 and caps["perché"] == 0 and caps["capitano"] == 0
    assert lower["viola"] == 1 and lower["rosa"] == 1 and lower["perché"] == 0 and lower["capitano"] == 2
    assert as_dict(freq, "zipf")["rosa"] == pytest.approx(zipf(3, total))
    assert meta == {
        "source": "leipzig_news", "total_tokens": total, "floor_zipf": pytest.approx(zipf(1, total)),
        "complete": True, "truncated": False,
    }
    assert ctx.rows() == [
        ("ancora", "l", 1), ("capitano", "il", 1), ("capitano", "non", 1),
        ("uomo", "della", 1), ("viola", "la", 1),
    ]


def test_leipzig_rejects_bad_tarballs(tmp_path):
    with pytest.raises(FileNotFoundError):
        leipzig.extract(tmp_path)
    make_tarball(tmp_path, 2024, [], symlink=True)
    with pytest.raises(ValueError):
        list(leipzig.read_sentences(leipzig.find_tarball(tmp_path)))
