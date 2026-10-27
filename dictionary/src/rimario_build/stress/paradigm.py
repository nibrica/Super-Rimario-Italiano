"""Paradigm propagation: stress for lexicon forms that no source marks.

Rules run in this order on the (form, lemma, pos) groups that have no attested
reading; a group filled by one rule is not touched by the later ones:

1. ``verb_rhizotonic``: present 1/2/3 sg and 3 pl (indicative, subjunctive)
   and the 2 sg imperative stress the stem vowel of an attested rhizotonic
   form of the same lemma (the one sharing the longest prefix, so -isc- forms
   follow -isc- forms), or else a stem-stressed -ere infinitive (prèndere):
   same vowel run counted from the start (càpito → càpitano, tèngo → tièni).
2. ``verb_ending``: every other finite or non-finite form is stressed on a
   fixed vowel run counted from the end, by its features (-àvo, -iàmo,
   -àrono/présero, -erèbbero, -àndo...); vowel quality from the ending.
3. ``nominal``: inflected nouns, adjectives... keep the lemma's stress index
   when the stem up to the stressed vowel is unchanged (uòmo → uòmini);
   superlatives are stressed on -ìssim-.
4. ``enclitic``: imperatives, gerunds and infinitives (attested or
   propagated) plus clitics (dìmmelo, portàndoglielo, portàrlo) keep the
   host's stress. Candidates are kept only if they are in ``spellings``.
5. ``suffix``: remaining non-verb forms with a productive suffix (-ménte,
   -zióne...). Each variant (-óso, -ósi...) is validated on the attested
   readings and used only if its precision reaches
   config.PARADIGM_SUFFIX_MIN_PRECISION (its family, the support). Like the
   model, this is a guess from the spelling, so it only fills forms that have
   no reading at all: it never adds a second stress to a known spelling
   (sàbato the noun, not sabàto the name; monòtone, not monotòne).
6. ``single_vowel``: forms with one vowel letter (del, sul, per): the only
   possible stress, so it is a rule, not a model guess.

Rules never invent forms: every output form is in ``forms`` or ``spellings``.
A rule's reading on the unaccented last vowel of a polysyllable is dropped:
Italian spelling would write that accent (Morph-it's ``devi`` of deviare would
otherwise become devì, ``riso`` of risapere risò). So is one off a written final
accent (abbacchiò); a non-final accent (élite) is no evidence (text.orthographic_stress).
"""

import logging
import os
import re

import polars as pl

from .. import config, schema, text

log = logging.getLogger(__name__)

_KEY = schema.READING_KEY
_PLAIN_VOWELS = frozenset("aeiou")
_ISC_RE = re.compile(r"isc(?:o|i|e|a|ono|ano|on|an)$")         # finìscon(o)
_ISC_LEMMA_RE = r"i(?:e)?re$|irsi$"                      # -isc- verbs: finire, compiere, pentirsi
_THEMATIC_I_RE = re.compile(r"[aeo]ire$")                # guaire, inveire, gioire


# --- Spelling helpers --------------------------------------------------------

_plain = text.strip_accents                           # accent-stripped spelling (same indexes)


def _runs(s: str) -> list[tuple[int, int]]:
    """(start, end) of each run of vowels in an accent-stripped spelling."""
    return [m.span() for m in re.finditer("[aeiou]+", s)]


def _nucleus(s: str, start: int, end: int) -> int:
    """Stressed vowel of a run: the last one, or the first of a falling pair (ài, uòi, finìi)."""
    if end - start >= 2 and (s[end - 2:end] == "ii" or (s[end - 1] in "iu" and s[end - 2] in "aeo")):
        return end - 2
    return end - 1


def _run_of(runs: list[tuple[int, int]], idx: int) -> int | None:
    return next((k for k, (a, b) in enumerate(runs) if a <= idx < b), None)


def _base_feats(feats: str | None) -> tuple[str | None, str]:
    """Split Morph-it feats into (paradigm key, clitics): "inf+pres+me+lo" -> ("inf+pres", "me+lo")."""
    if not feats:
        return None, ""
    parts = feats.split("+")
    n = 2 if parts[0] in ("inf", "ger") else 4       # part+past+s+m keys as "part+past"
    return "+".join(parts[:2 if parts[0] == "part" else n]), "+".join(parts[n:])


# --- Rules on single forms -----------------------------------------------------

def _isc(s: str) -> int | None:
    """Index of the stressed i of an -isc- present form (finìsco, finìscono), else None."""
    m = _ISC_RE.search(s)
    return m.start() if m else None


def rhizotonic(source: str, source_idx: int, target: str, isc: bool = True) -> int | None:
    """Stress of ``target`` on the vowel run of ``source``'s stress, counted from the start.

    Inside the run, the same offset if both runs are spelled alike (coòrdino),
    else the source's vowel (tèngo → tièni), else the run's nucleus (sòno → sèi).
    With ``isc`` (-ire, -iere, -irsi verbs), -isc- forms are stressed on -ìsc-, and a plain
    form mapped from an -isc- source (assorbìsco → assòrbe) takes the run before.
    """
    s, t = _plain(source), _plain(target)
    if isc and (i := _isc(t)) is not None:
        return i
    s_runs, t_runs = _runs(s), _runs(t)
    k = _run_of(s_runs, source_idx)
    from_isc = isc and _isc(s) == source_idx
    if k is not None and from_isc:
        k -= 1
    if k is None or k < 0 or k >= len(t_runs):
        return None
    (sa, sb), (a, b) = s_runs[k], t_runs[k]
    if from_isc:
        return _nucleus(t, a, b)
    if s[sa:sb] == t[a:b]:
        return a + source_idx - sa
    i = t.find(s[source_idx], a, b)
    return i if i >= 0 else _nucleus(t, a, b)


def ending(form: str, key: str, lemma: str) -> int | None:
    """Stress of an arizotonic (or strong-past) verb form from its features.

    Apocopated forms (Morph-it's trasformavan, incettar) count their lost final vowel.
    In -aire/-eire/-oire verbs the thematic i is stressed (guaìto, inveìvano, gioìre).
    """
    t = _plain(form)
    if t[-1:] not in _PLAIN_VOWELS:
        t += "e"
    back = config.PARADIGM_ENDING_RUN.get(key)
    if key == "part+past":
        back = config.PARADIGM_PARTICIPLE_RUN.get(lemma, back)
    if key == "inf+pres" and t.endswith("ere") and not t.endswith("rre"):
        return None                                  # prèndere or temére: unknown
    if key == "ind+past+1+s":                        # weak -ài/-éi/-ìi, else strong penult (prési)
        weak = {"are": "ai", "ere": "ei", "ire": "ii"}.get(_plain(lemma)[-3:])
        back = 1 if weak and t.endswith(weak) else 2
    runs = _runs(t)
    if back is None or back > len(runs):
        return None
    a, b = runs[-back]
    if b == len(lemma) - 2 and _THEMATIC_I_RE.search(lemma):     # the stem's run: gu[ai]re
        return b - 1
    return _nucleus(t, a, b)


def ending_quality(form: str, idx: int, key: str) -> str | None:
    """Quality of a stressed e from the ending (config.PARADIGM_ENDING_QUALITY)."""
    mood = "+".join(key.split("+")[:2])
    return config.PARADIGM_ENDING_QUALITY.get((mood, _plain(form)[idx:]))


def nominal(form: str, lemma: str, lemma_idx: int) -> int | None:
    """Lemma's stress index for an inflection of it: same stem, new final vowels.

    The stem is the lemma without its final vowel run; the form must be the
    stem plus at most two vowels, or an h and one vowel (amìco → amìci, amìche;
    stùdio → stùdi). Derived words (orlétto, caldìssimo) don't match. A lemma
    ending in a two-vowel hiatus stressed on its first vowel keeps that vowel
    and changes only the last one (energìa → energìe, zìo → zìi).
    """
    f, l = _plain(form), _plain(lemma)
    runs = _runs(l)
    if not runs or runs[-1][1] != len(l):
        return None                                  # consonant-final lemma
    a, b = runs[-1]
    if lemma_idx == a and b - a == 2:                # -ìa, -ìo: one final vowel changes
        return lemma_idx if len(f) == len(l) and f[:-1] == l[:-1] and f[-1] in _PLAIN_VOWELS else None
    if lemma_idx >= a:
        return None                                  # oxytone lemma
    stem, rest = l[:a], f[a:]
    if not f.startswith(stem) or len(rest) > 2 or not all(c in _PLAIN_VOWELS for c in rest.removeprefix("h")):
        return None
    return lemma_idx


def superlative(form: str) -> int | None:
    """caldìssimo: the i of -issim-."""
    i = _plain(form).rfind("issim")
    return i if i > 0 else None


def monosyllable(form: str) -> int | None:
    """Stress of a one-vowel-run spelling (da', fa', sta'), else None."""
    t = _plain(form)
    runs = _runs(t)
    return _nucleus(t, *runs[0]) if len(runs) == 1 else None


def host_stem(host: str, key: str) -> tuple[str, bool]:
    """Spelling a clitic attaches to, and whether it doubles the clitic's consonant (dammi).

    An infinitive drops its final e (portar+lo); an apocopated one (portar) is already a stem.
    """
    if key == "inf+pres" and host.endswith("e"):
        return (host[:-2] if host.endswith("rre") else host[:-1]), False
    stem = _plain(host.rstrip("'"))
    short = key == "impr+pres+2+s" and (host[-1] in "'àèéìòóù" or len(_runs(stem)) == 1)
    return (stem if short else host), short


# --- Frame helpers -----------------------------------------------------------

def _apply(df: pl.DataFrame, fn, cols: list[str], dtype=pl.Int16) -> pl.Series:
    return pl.Series([fn(*row) for row in df.select(cols).iter_rows()], dtype=dtype)


def _with_keys(lex: pl.DataFrame) -> pl.DataFrame:
    split = [_base_feats(f) for f in lex["feats"].to_list()]
    return lex.with_columns(
        key=pl.Series([s[0] for s in split], dtype=pl.String),
        clitics=pl.Series([s[1] for s in split], dtype=pl.String),
    )


def _against_spelling(form: pl.Expr, idx: pl.Expr) -> pl.Expr:
    """A stress the spelling rules out: off a written final accent (abbacchiò), or on the
    unaccented final vowel of a polysyllable (devì for devi). Other accents are no evidence."""
    v, last = "".join(sorted(text.VOWELS)), form.str.len_chars() - 1
    return pl.when(form.str.contains(f"[{''.join(sorted(text.ACCENTED))}]$")).then(idx != last).otherwise(
        (idx == last) & form.str.contains("[aeiou]$") & form.str.contains(f"[{v}][^{v}]+[{v}]"))


def _rule_out(df: pl.DataFrame, rule: str) -> pl.DataFrame:
    """Readings produced by one rule, in READINGS columns."""
    return (
        df.filter(pl.col("stress_idx").is_not_null() & ~_against_spelling(pl.col("form"), pl.col("stress_idx")))
        .select(*_KEY, "stress_idx", "quality")
        .unique()
        .with_columns(
            tier=pl.lit("propagated"), confidence=pl.lit(1.0), evidence=pl.lit("none"),
            sources=pl.lit([f"paradigm.{rule}"], dtype=pl.List(pl.String)),
        )
    )


def _same_vowel_quality(source: str, source_idx: int, target: str, idx: int | None,
                        quality: str | None) -> str | None:
    """``quality`` if the target is stressed on the same vowel letter as the source."""
    return quality if quality and idx is not None and _plain(source)[source_idx] == _plain(target)[idx] else None


# --- Rules on frames ---------------------------------------------------------

def _verb_rhizotonic(targets: pl.DataFrame, known: pl.DataFrame) -> pl.DataFrame:
    rhizo = list(config.PARADIGM_RHIZOTONIC)
    # A stem-stressed -ere infinitive (prèndere) is a source too, after the others.
    inf = known.filter((pl.col("key") == "inf+pres") & pl.col("form").str.ends_with("ere")
                       & ~pl.col("form").str.ends_with("rre"))
    inf = inf.filter(pl.Series([_run_of(r := _runs(_plain(f)), i) == len(r) - 3
                                for f, i in inf.select("form", "stress_idx").iter_rows()], dtype=pl.Boolean))
    src = (
        pl.concat([known.filter(pl.col("key").is_in(rhizo) & (pl.col("clitics") == "")), inf])
        .select("lemma", src_form="form", src_idx="stress_idx", src_quality="quality",
                src_rank=pl.col("key").replace_strict({k: i for i, k in enumerate([*rhizo, "inf+pres"])},
                                                      return_dtype=pl.Int32))
        .unique()
    )
    t = targets.filter(pl.col("key").is_in(rhizo) & (pl.col("clitics") == "")).select(_KEY).unique()
    pairs = t.join(src, on="lemma")
    lcp = [len(os.path.commonprefix([_plain(f), _plain(s)])) for f, s in pairs.select("form", "src_form").iter_rows()]
    best = (
        pairs.with_columns(lcp=pl.Series(lcp, dtype=pl.Int32))
        .sort(*_KEY, "lcp", "src_rank", "src_form", "src_idx",
              descending=[False, False, False, True, False, False, False])
        .group_by(_KEY, maintain_order=True).first()
    )
    best = best.with_columns(isc=pl.col("lemma").str.contains(_ISC_LEMMA_RE))
    best = best.with_columns(stress_idx=_apply(best, rhizotonic, ["src_form", "src_idx", "form", "isc"]))
    return best.with_columns(quality=_apply(
        best, _same_vowel_quality, ["src_form", "src_idx", "form", "stress_idx", "src_quality"], pl.String))


def _clitic_host(t: pl.DataFrame, lex: pl.DataFrame) -> pl.DataFrame:
    """``t`` with ``host``: the form without a trailing clitic when that is a form of the same
    lemma and key (tenuta for tenutasi, which kaikki lists as plain part+past), else the form.

    A regular participle is never split into a short one plus a clitic (frustàti, not frùsta+ti).
    """
    plain = lex.filter(pl.col("clitics") == "").select("lemma", "key", host="form").unique()
    vowel = pl.col("lemma").str.slice(-3, 1).replace({"e": "u"})       # -are: -at-, -ere: -ut-, -ire: -it-

    def regular(s: str) -> pl.Expr:
        return pl.col(s).str.slice(-3, 2) == vowel + "t"

    cand = pl.concat([
        t.filter(pl.col("form").str.ends_with(c)).select(*_KEY, "key", host=pl.col("form").str.head(-len(c)))
        for c in sorted({c.replace("+", "") for c in config.PARADIGM_CLITICS})
    ]).join(plain, on=["lemma", "key", "host"], how="semi").filter(~regular("form") | regular("host"))
    cand = (cand.sort(pl.col("host").str.len_chars(), "host")                         # shortest host
            .group_by(*_KEY, "key", maintain_order=True).first())
    return t.join(cand, on=[*_KEY, "key"], how="left").with_columns(host=pl.coalesce("host", "form"))


def _verb_ending(targets: pl.DataFrame, lex: pl.DataFrame) -> pl.DataFrame:
    # Pronominal lemmas (accettarsi) list clitic forms under plain features: skip them.
    t = (targets.filter((pl.col("clitics") == "") & pl.col("lemma").str.ends_with("re"))
         .select(*_KEY, "key").unique())
    t = _clitic_host(t, lex)
    t = t.with_columns(stress_idx=_apply(t, ending, ["host", "key", "lemma"]))
    t = t.filter(pl.col("stress_idx").is_not_null())
    t = t.with_columns(quality=_apply(t, ending_quality, ["host", "stress_idx", "key"], pl.String))
    t = t.group_by(*_KEY, "stress_idx").agg(
        quality=pl.when(pl.col("quality").n_unique() == 1).then(pl.col("quality").first()))
    return t.filter(pl.len().over(_KEY) == 1)    # a form with two keys (porta: ind and impr) must agree


def _nominal(targets: pl.DataFrame, readings: pl.DataFrame) -> pl.DataFrame:
    lemma_r = (                              # lemmas with one stress (quality may vary)
        readings.filter(pl.col("form") == pl.col("lemma"))
        .group_by("lemma", "pos").agg(
            n=pl.col("stress_idx").n_unique(), lemma_idx=pl.col("stress_idx").first(),
            lemma_quality=pl.when(pl.col("quality").n_unique() == 1).then(pl.col("quality").first()))
        .filter(pl.col("n") == 1).drop("n")
    )
    t = targets.filter(pl.col("pos") != "verb").select(*_KEY, "feats").unique()
    sup = t.filter(pl.col("feats").str.starts_with("sup+")).select(_KEY).unique()
    sup = sup.with_columns(stress_idx=_apply(sup, superlative, ["form"]), quality=pl.lit(None, pl.String))
    exc = pl.DataFrame(list(config.PARADIGM_NOMINAL_EXCEPTIONS.items()),
                       schema={"form": pl.String, "exc_idx": pl.Int16}, orient="row")
    rest = (
        t.filter(~pl.col("feats").fill_null("").str.starts_with("sup+") & (pl.col("form") != pl.col("lemma")))
        .select(_KEY).unique().join(lemma_r, on=["lemma", "pos"]).join(exc, on="form", how="left")
    )
    rest = rest.with_columns(
        stress_idx=pl.coalesce("exc_idx", _apply(rest, nominal, ["form", "lemma", "lemma_idx"])))
    rest = rest.with_columns(quality=_apply(
        rest, _same_vowel_quality, ["lemma", "lemma_idx", "form", "stress_idx", "lemma_quality"], pl.String))
    return pl.concat([sup, rest.select(*_KEY, "stress_idx", "quality")])


def _enclitic(lex: pl.DataFrame, verbs: pl.DataFrame, spellings: pl.DataFrame) -> pl.DataFrame:
    """Host verb readings × clitic combinations, kept if the spelling is in ``spellings``."""
    hosts = verbs.filter(pl.col("key").is_in(config.PARADIGM_CLITIC_HOSTS) & (pl.col("clitics") == ""))
    # Monosyllabic imperatives (da', fa', di', va', sta') need no reading: one vowel run.
    mono = lex.filter((pl.col("key") == "impr+pres+2+s") & (pl.col("clitics") == "") & (pl.col("pos") == "verb"))
    mono = mono.with_columns(stress_idx=_apply(mono, monosyllable, ["form"]), quality=pl.lit(None, pl.String))
    hosts = pl.concat([
        hosts.select(*_KEY, "key", "stress_idx", "quality"),
        mono.filter(pl.col("stress_idx").is_not_null()).select(*_KEY, "key", "stress_idx", "quality"),
    ]).unique(subset=[*_KEY, "key", "stress_idx"], keep="first")
    stems = [host_stem(f, k) for f, k in hosts.select("form", "key").iter_rows()]
    hosts = hosts.with_columns(
        stem=pl.Series([s for s, _ in stems], dtype=pl.String),
        double=pl.Series([d for _, d in stems], dtype=pl.Boolean),
    ).filter(pl.col("stress_idx") < pl.col("stem").str.len_chars())
    clitics = pl.DataFrame({"clitic": list(config.PARADIGM_CLITICS)})
    doubled = pl.col("clitic").str.replace_all("+", "", literal=True)
    cand = hosts.join(clitics, how="cross").with_columns(
        cand=pl.col("stem") + pl.when(pl.col("double") & ~doubled.str.starts_with("gli"))
        .then(doubled.str.slice(0, 1) + doubled).otherwise(doubled)
    )
    # Keep known spellings, except lexicon words listed only as something else
    # (federàti is a participle, not fèdera+ti): a lexicon form qualifies only if
    # every row is a verb with clitics, or an entry of its own (kaikki "dimmelo").
    other = lex.filter(
        (pl.col("pos") != "verb")
        | pl.when(pl.col("key").is_null()).then(pl.col("lemma") != pl.col("form")).otherwise(pl.col("clitics") == ""))
    cand = (cand.join(spellings.select(cand="form"), on="cand", how="semi")
            .join(other.select(cand="form").unique(), on="cand", how="anti"))
    return (
        cand.select(form="cand", lemma="lemma", pos="pos", stress_idx="stress_idx", quality="quality")
        .group_by(_KEY).agg(
            n=pl.col("stress_idx").n_unique(), stress_idx=pl.col("stress_idx").first(),
            quality=pl.when(pl.col("quality").n_unique() == 1).then(pl.col("quality").first()),
        )
        .filter(pl.col("n") == 1)               # hosts disagreeing on the stress: leave it to the model
        .drop("n")
    )


def suffix_variants(family: str) -> list[str]:
    """ "ìssimo|a|i|e" -> ["ìssimo", "ìssima", "ìssimi", "ìssime"]."""
    first, *rest = family.split("|")
    return [first, *(first[:-1] + r for r in rest)]


def _suffix_match(df: pl.DataFrame, marked: str) -> pl.DataFrame:
    """Rows of ``df`` whose form ends with the suffix variant ``marked`` (and is longer),
    with the expected stress index."""
    offset = text.accent_positions(marked)[0]
    end = marked if offset == len(marked) - 1 else _plain(marked)       # -ità is written with its accent
    n = pl.col("form").str.len_chars()
    return df.filter(pl.col("form").str.ends_with(end) & (n > len(marked))).with_columns(
        expected=(n - len(marked) + offset).cast(pl.Int16))


def suffix_precision(readings: pl.DataFrame) -> pl.DataFrame:
    """Precision of each variant of the config.PARADIGM_SUFFIXES families on attested
    non-verb readings (-ósi apart from -óso: diàgnosi).

    precision: share of matching forms whose readings all have the suffix's
    stress; quality_precision: share of those readings with a known quality
    that have the suffix's quality; family_n: forms matching the whole family.
    """
    r = readings.filter(pl.col("pos") != "verb").select("form", "stress_idx", "quality").unique()
    rows = []
    for family in config.PARADIGM_SUFFIXES:
        quality = text.ACCENTED[family[text.accent_positions(family)[0]]][1]
        for marked in suffix_variants(family):
            m = _suffix_match(r, marked)
            per_form = m.group_by("form").agg(ok=(pl.col("stress_idx") == pl.col("expected")).all())
            hit = m.filter((pl.col("stress_idx") == pl.col("expected")) & pl.col("quality").is_not_null())
            rows.append({
                "family": family, "suffix": marked, "n": per_form.height,
                "precision": per_form["ok"].mean() if per_form.height else None,
                "quality": quality,
                "quality_precision": (hit["quality"] == quality).mean() if quality and hit.height else None,
            })
    return pl.DataFrame(rows, schema={"family": pl.String, "suffix": pl.String, "n": pl.Int64,
                                      "precision": pl.Float64, "quality": pl.String,
                                      "quality_precision": pl.Float64},
                        ).with_columns(family_n=pl.col("n").sum().over("family"))


def _suffix(targets: pl.DataFrame, readings: pl.DataFrame) -> pl.DataFrame:
    prec = suffix_precision(readings)
    for row in prec.iter_rows(named=True):
        log.info("suffix -%s: n=%d precision=%s quality_precision=%s",
                 row["suffix"], row["n"], row["precision"], row["quality_precision"])
    # The family needs the support; each variant needs the precision on its own.
    ok = prec.filter((pl.col("family_n") >= config.PARADIGM_SUFFIX_MIN_SUPPORT)
                     & (pl.col("precision") >= config.PARADIGM_SUFFIX_MIN_PRECISION))
    t = targets.filter(pl.col("pos") != "verb").select(_KEY).unique()
    out = [t.with_columns(stress_idx=pl.lit(None, pl.Int16), quality=pl.lit(None, pl.String),
                          slen=pl.lit(0, pl.Int32)).clear()]
    for row in ok.iter_rows(named=True):
        q = row["quality"] if (row["quality_precision"] or 0) >= config.PARADIGM_SUFFIX_MIN_PRECISION else None
        out.append(_suffix_match(t, row["suffix"]).select(
            *_KEY, stress_idx="expected", quality=pl.lit(q, pl.String), slen=pl.lit(len(row["suffix"]), pl.Int32)))
    return (                                 # longest suffix wins (-ìssimo over -ìmo)
        pl.concat(out).sort(*_KEY, "slen", descending=[False, False, False, True])
        .group_by(_KEY, maintain_order=True).first().drop("slen")
    )


# --- Stage -------------------------------------------------------------------

def propagate(forms: pl.DataFrame, readings: pl.DataFrame, spellings: pl.DataFrame) -> pl.DataFrame:
    """FORMS + attested READINGS + known spellings (lexicons, corpora) → READINGS (tier "propagated")."""
    lex = _with_keys(forms.select(*_KEY, "feats").unique())
    base = readings.select(*_KEY, "stress_idx", "quality").unique()
    done = base.select(_KEY).unique()
    # Stresses attested for the same verb slot (form, feats key) under another lemma label:
    # a rule may not add a different one (compìscono of compire, not còmpiscono of compiere).
    # Only attested groups with one key count (abbùffati is the imperative, not the participle).
    # Nouns and adjectives have real homographs here (arbìtri of arbìtrio, àrbitri of àrbitro).
    one_key = lex.filter(pl.col("pos") == "verb").filter(pl.col("key").n_unique().over(_KEY) == 1)
    slots = one_key.join(base, on=_KEY).select("form", "pos", "key", att_lemma="lemma", att_idx="stress_idx")
    taken = (lex.join(slots, on=["form", "pos", "key"]).filter(pl.col("lemma") != pl.col("att_lemma"))
             .select(*_KEY, "att_idx").unique())
    out: list[pl.DataFrame] = []

    def todo() -> pl.DataFrame:
        return lex.join(done, on=_KEY, how="anti")

    def add(df: pl.DataFrame, rule: str) -> None:
        nonlocal done
        r = _rule_out(df.join(done, on=_KEY, how="anti"), rule)
        clash = (r.join(taken, on=_KEY).group_by(*_KEY, "stress_idx")
                 .agg(ok=(pl.col("att_idx") == pl.col("stress_idx")).any()).filter(~pl.col("ok")))
        r = r.join(clash, on=[*_KEY, "stress_idx"], how="anti")
        log.info("paradigm %s: %d readings", rule, r.height)
        out.append(r)
        done = pl.concat([done, r.select(_KEY)]).unique()

    def verbs_known() -> pl.DataFrame:
        known = pl.concat([base, *[o.select(base.columns) for o in out]])
        return known.join(lex.filter(pl.col("pos") == "verb"), on=_KEY)

    add(_verb_rhizotonic(todo().filter(pl.col("pos") == "verb"), verbs_known()), "verb_rhizotonic")
    add(_verb_ending(todo().filter(pl.col("pos") == "verb"), lex), "verb_ending")
    add(_nominal(todo(), base), "nominal")
    add(_enclitic(lex, verbs_known(), spellings), "enclitic")
    add(_suffix(todo().join(done.select("form").unique(), on="form", how="anti"), base), "suffix")
    single = todo().filter(pl.col("form").str.contains("^[a-z]+$") & (pl.col("form").str.count_matches("[aeiou]") == 1))
    add(single.with_columns(stress_idx=pl.col("form").str.find("[aeiou]").cast(pl.Int16),   # ASCII: byte = char
                            quality=pl.lit(None, pl.String)), "single_vowel")

    return schema.sort_readings(schema.conform(pl.concat(out), schema.READINGS))
