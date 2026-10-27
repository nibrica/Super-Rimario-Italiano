"""sources/morphit.py on a tiny hand-made Morph-it archive."""

import io
import tarfile
from pathlib import Path

import polars as pl
import pytest

from rimario_build import config, schema
from rimario_build.sources import morphit

LINES = """\
ancora	ancora	ADV
ancora	ancora	NOUN-F:s
ancora	ancorare	VER:ind+pres+3+s
ancóra	ancóra	ADV
àncora	àncora	NOUN-F:s
àncore	àncora	NOUN-F:p
princìpi	princìpio	NOUN-M:p
principio	principio	NOUN-M:s
dèmone	dèmone	NOUN-M:s
démone	démone	NOUN-M:s
demone	demone	NOUN-M:s
zàzzera	zàzzera	NOUN-F:s
élite	élite	NOUN-F:s
èlite	èlite	NOUN-F:s
elite	elite	NOUN-F:s
è	essere	VER:ind+pres+3+s
é	essere	VER:ind+pres+3+s
più	più	ADV
piú	più	ADV
sé	sé	PRO-PERS-3-M-S
sè	sè	PRO-PERS-3-M-S
mò	mo'	ADV
mó	mo'	ADV
accellerato	accellerare	VER:part+past+s+m
striscie	striscia	NOUN-F:p
citta'	città	NOUN-F:s
attivita'	attivita'	NOUN-F:s
rifa'	rifare	VER:impr+pres+2+s
dotto'	dottore	NOUN-M:s
perchè	perché	CON
credè	credere	VER:ind+past+3+s
,	,	PON
"""


@pytest.fixture(scope="module")
def forms(tmp_path_factory) -> pl.DataFrame:
    raw = tmp_path_factory.mktemp("morphit")
    data = LINES.encode("iso-8859-1")
    with tarfile.open(raw / config.MORPHIT_ARCHIVE, "w:gz") as tar:
        info = tarfile.TarInfo(config.MORPHIT_MEMBER)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return morphit.extract(Path(raw))


def _rows(forms, form):
    return {(r["lemma"], r["pos"], r["feats"], r["stress_idx"], r["quality"], r["evidence"], tuple(r["tags"]))
            for r in forms.filter(pl.col("form") == form).iter_rows(named=True)}


def test_schema_and_order(forms):
    assert forms.schema == pl.Schema(schema.FORMS)
    assert forms.equals(forms.sort(["form", "lemma", "pos", "feats", "evidence", "stress_idx", "quality",
                                    pl.col("tags").list.join(","), "source"], nulls_last=True))
    assert forms.group_by("form", "lemma", "pos", "feats").len()["len"].max() == 1
    assert "," not in forms["form"].to_list()


def test_stress_marks_become_plain_spelling(forms):
    assert not set(forms["form"]) & {"ancóra", "àncora", "àncore", "princìpi", "dèmone", "démone"}
    assert _rows(forms, "ancora") == {
        ("ancora", "adv", None, 3, "closed", "table", ()),       # ancóra replaces the unstressed row
        ("ancora", "noun", "f+s", 0, None, "table", ()),         # àncora
        ("ancorare", "verb", "ind+pres+3+s", None, None, "none", ()),
    }
    assert _rows(forms, "ancore") == {("ancora", "noun", "f+p", 0, None, "table", ())}  # via its lemma
    assert _rows(forms, "principi") == {("principio", "noun", "m+p", 5, None, "table", ())}
    # dèmone/démone: one reading, the marks disagree on the quality
    assert _rows(forms, "demone") == {("demone", "noun", "m+s", 1, None, "table", ())}


def test_accent_without_plain_twin_is_kept_unstressed(forms):
    assert _rows(forms, "zàzzera") == {("zàzzera", "noun", "f+s", None, None, "none", ())}
    # French accent, not a stress mark, even though "elite" exists
    assert _rows(forms, "élite") == {("élite", "noun", "f+s", None, None, "none", ())}
    assert _rows(forms, "èlite") == {("èlite", "noun", "f+s", None, None, "none", ("misspelling",))}


@pytest.mark.parametrize("bad, good", [("é", "è"), ("piú", "più"), ("sè", "sé"), ("mó", "mò")])
def test_accent_glyph_twins(forms, bad, good):
    assert all("misspelling" in t for t in forms.filter(pl.col("form") == bad)["tags"])
    assert not any("misspelling" in t for t in forms.filter(pl.col("form") == good)["tags"])


def test_listed_misspellings(forms):
    for form in ("accellerato", "striscie"):               # accellerare: listed as a lemma
        assert forms.filter(pl.col("form") == form)["tags"].to_list() == [["misspelling"]]


def test_spelling_quirks(forms):
    assert _rows(forms, "città") == {("città", "noun", "f+s", 4, None, "ortho", ())}
    assert _rows(forms, "attività") == {("attività", "noun", "f+s", 7, None, "ortho", ())}
    assert _rows(forms, "rifà") == {("rifare", "verb", "impr+pres+2+s", 3, None, "ortho", ())}
    assert _rows(forms, "dotto'") == {("dottore", "noun", "m+s", None, None, "none", ())}  # apocope, not dottò
    assert _rows(forms, "perché") == {("perché", "conj", None, 5, "closed", "ortho", ())}
    assert _rows(forms, "credé") == {("credere", "verb", "ind+past+3+s", 4, "closed", "ortho", ())}
