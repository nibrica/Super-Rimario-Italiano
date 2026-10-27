# Dictionary build

This folder builds `web/parole-accenti-frequenze.csv`, the dictionary behind Super Rimario Italiano: every Italian word form that a corpus or at least two lexicons know, with the position of its stressed vowel, a modern frequency, and separate rows for homographs (*àncora*/*ancòra*, *prìncipi*/*princìpi*).

One command fetches the latest version of every source and rebuilds the file. This README is the reference for the build and for the output format (see [Output](#output)), which the frontend in `web/` relies on; later work is in [`FOLLOW-UPS.md`](FOLLOW-UPS.md).

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python (≥ 3.14) and the dependencies (`polars`, `orjson`, `wordfreq`, `scikit-learn`, `numpy`, `scipy`; `pytest` for development) into `.venv/`.
- No system packages (no espeak).
- About 400 MB of disk for the raw sources, and a network connection for the first build.

## Building

Run everything from this folder:

```sh
cd dictionary
uv run rimario-build                  # fetch the latest sources, then build the dictionary
uv run rimario-build --offline        # build from the files already in data/raw/ (no network)
uv run rimario-build fetch            # only update data/raw/ and sources.lock.json
uv run rimario-build build            # only build the dictionary from the files on disk (same as --offline)
uv run rimario-build report           # only rewrite report.md from the cache, diffing against git HEAD
uv run rimario-build --only morphit   # fetch only this source, then rebuild its extractor and every later stage
uv run rimario-build -v ...           # debug logging
```

Usage: `rimario-build [fetch|build|report] [--offline] [--only ID] [-v]`. `--only` takes a source id from `sources.toml`; with `fetch` it fetches just that source, with `--offline` nothing is fetched but the source's extractor and every later stage rerun even if cached. `fetch --offline` is an error, and so is `--only` with `report` (it reruns no stage). `report` fails if a stage has no cached output for the current inputs; run a build first.

**Baseline.** `build` and `report` diff the new CSV and lock against `web/parole-accenti-frequenze.csv` and `sources.lock.json` as committed at git HEAD, so the report shows what a commit would change. Without a committed CSV (a fresh repository, or a checkout outside git), the baseline is the CSV on disk before it's overwritten, or nothing; without a committed lock, it is the lock as it was before this run's fetch.

**Fetching.** Sources are declared in `sources.toml`. A download is conditional (ETag / Last-Modified from `sources.lock.json`), so a source is downloaded again only when the server has a newer version; it's verified (size, sha256) and moved atomically into `data/raw/<id>/`. If a source can't be reached, the local copy is used and the report says so; without a local copy the build stops. `sources.lock.json` is committed: it records exactly which data produced the committed dictionary.

**Cache.** Each stage's output is stored as parquet under `data/cache/`, keyed by a hash of its inputs and its code, so a rebuild reruns only the stages whose inputs or code changed.

A cold build takes a few minutes, mostly downloading and decompressing; a rebuild after changing the frequency rules takes seconds. The same raw sources always produce a byte-identical CSV.

## Stages

```
fetch ─► sources/* ─► forms, freq, contexts
                         │
         stress/vote ◄───┘
              │
         stress/paradigm ─► stress/model
              │
         lexicon (inclusion)
              │
         frequency/merge ─► frequency/homographs
              │
         export ─► web/   +   report
```

| Stage | What it does |
|---|---|
| `sources/*` | One extractor per source, each producing one normalized table (`schema.py`): word forms with lemma, POS and any stress evidence; word counts; the cue word (article, preposition, clitic…) before each form in the news sentences, and how often each form is capitalized mid-sentence or all lowercase there. |
| `stress/vote.py` | Combines the attested stress (IPA, stress-marked hyphenation, conjugation tables) of the two Wiktionaries; distinct lemma/POS with different stress become homographs, disagreements go to the report. |
| `stress/paradigm.py` | Gives stress to forms no source marks: verb forms from the lemma's attested forms, enclitics (*dìmmelo*, *portàndoglielo*), inflections, productive suffixes. A generated form is kept only if a lexicon or a corpus contains it. |
| `stress/model.py` | A classifier trained on the attested readings predicts the rest; predictions are shipped only above a confidence threshold set per POS, and flagged. |
| `lexicon.py` | Decides which forms go in: it drops the unstressed articles, clitic pronouns, prepositions and conjunctions (`ATONIC_FORMS`: *il, la, un, mi, si, ne, glie, di, a, della, nel, e, ma, che*…) with all their readings, since they can't rhyme (the note *la* and *glìe*, plural of *glia*, go too: left alone, they would get the clitic's frequency; so *su*, *dai* and *dei*, also stressed words, stay); it drops abbreviations, misspellings and Roman numerals (only their `num` readings); among forms whose stress is only predicted or from the single-vowel rule, it drops loanwords (spelled with j/k/w/x/y and no Italian suffix, or clearly more frequent in English than in Italian according to wordfreq); proper nouns need a Kaikki entry and frequency data; a form found in no corpus needs at least `UNSEEN_MIN_LEXICONS` (2) of the three lexicons (Morph-it! and the two Wiktionaries), unless `paradigm` derived it as a verb + clitics (*portàndoglielo*), which drops the long tail that only one lexicon lists, and with it that lexicon's typos (*muoiaa* in a Wiktionary conjugation table). Then it applies `curation/overrides.tsv`. |
| `frequency/merge.py` | Merges the three frequency sources into one Zipf value per spelling: a weighted mean with reliability and robustness checks, where a missing word counts as "rarer than this source's floor" (only when that bound is below the word's real observations). The unaccented twin of a final-accent word (*cosi* for *così*), mostly the same word typed without its accent, is capped below the accented spelling where edited news text confirms it is the rarer one. Forms found only in lexicons get a small value below every corpus estimate. |
| `frequency/homographs.py` | Splits a spelling's frequency among its readings and picks the default reading. The first rule that applies splits the readings into two groups, each split again the same way: capitalization in the news sentences (proper noun vs. common word), function word vs. content word, archaic/literary/rare readings vs. the others, participle vs. imperative + clitic (*trovàti*/*tròvati*), context words before noun vs. verb readings (only with at least `CONTEXT_MIN_CUES` cues), lemma frequencies, else 50/50. Readings that differ only in vowel quality (*pèsca*/*pésca*) are one row, with the summed frequency. |
| `export.py` | Writes the CSV and `ATTRIBUTION.md`. |
| `report.py` | Writes `report.md`: source versions, counts, gold accuracy, model accuracy, frequency agreement, the diff against the build committed at git HEAD, and worklists (conflicts, 50/50 splits, low-confidence predictions, frequent forms without attested stress). |

Every tunable number (weights, thresholds, cue words) lives in `src/rimario_build/config.py`.

## Sources

| id | Provides | Licence |
|---|---|---|
| `kaikki_en` | Italian entries of the English Wiktionary, via [Kaikki.org](https://kaikki.org/dictionary/Italian/) (wiktextract): IPA, stress-marked hyphenation and inflection tables | CC BY-SA 4.0 |
| `kaikki_it` | The Italian Wiktionary, via [Kaikki.org](https://kaikki.org/itwiktionary/rawdata.html) (wiktextract): hyphenation, IPA, POS, verb-form glosses | CC BY-SA 4.0 |
| `morphit` | [Morph-it!](https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it): ~505k inflected forms with lemma and features | CC BY-SA 2.0 / LGPL |
| `wordfreq` | [wordfreq](https://github.com/rspeer/wordfreq) Italian Zipf frequencies (Wikipedia, subtitles, news, books, web) | data CC BY-SA 4.0 |
| `opensubtitles` | [FrequencyWords](https://github.com/hermitdave/FrequencyWords): OpenSubtitles 2018 word counts | CC BY-SA 4.0 |
| `leipzig_news` | [Leipzig Corpora Collection](https://wortschatz.uni-leipzig.de/en/download/Italian): 1M Italian news sentences, newest year available | CC BY 4.0 |

Every source is redistributable, usable commercially inside a GPL project, and downloaded automatically. The build writes `web/ATTRIBUTION.md` with each source, its licence, the papers to cite and the fetched versions; wherever the dictionary is shown, that file must be shown or linked too.

**Morph-it! mirror.** Since 2026 the Morph-it! server answers automated downloads with HTTP 402 (a bot check), so the original archive is committed unchanged at `mirror/morphit/morph-it.tgz` (with its `lgpl.txt` and readme), redistributed under its licence (CC BY-SA 2.0 / LGPL); `ATTRIBUTION.md` says so. `fetch` still tries the upstream URL first; when it can't download the file and there is no local copy in `data/raw/morphit/`, it copies the mirror there, checks its sha256 against `mirror_sha256` in `sources.toml`, and records `"via": "mirror"` in `sources.lock.json`. When the mirror is restored and upstream answers a HEAD request with a different Last-Modified or size than `mirror_last_modified`, the build warns that the mirror needs refreshing. Once `data/raw/morphit/` holds a copy, an upstream change that can't be downloaded only shows the usual "using the local copy" warning.

To refresh the mirror (only needed if Morph-it! publishes a new version; the last one is from 2018):

1. Download `morph-it.tgz` by hand in a browser from the [Morph-it! page](https://docs.sslmit.unibo.it/doku.php?id=resources:morph-it).
2. Replace `mirror/morphit/morph-it.tgz` with it, unchanged.
3. In `sources.toml`, set `mirror_sha256` to its `sha256sum` and `mirror_last_modified` to the server's `Last-Modified` header for it (browser developer tools, network tab). If the lexicon member inside was renamed, update `MORPHIT_MEMBER` in `config.py`.
4. Run `uv run rimario-build --only morphit`: the lock still records the old mirror's sha256, so fetch copies the new mirror into `data/raw/morphit/` and the build reruns from Morph-it! on. Commit the mirror, `sources.toml`, `sources.lock.json`, `report.md` and the two files in `web/`.

## Output

The build writes three files, all committed, so each dictionary update is an ordinary diff:

- `web/parole-accenti-frequenze.csv`: the dictionary (format below), in the site folder so the frontend reads it as is;
- `web/ATTRIBUTION.md`: sources and licences, linked from the site's footer;
- `dictionary/report.md`: the QA report of the last build, including the CSV's sha256 (not part of the site).

`parole-accenti-frequenze.csv` is UTF-8 with `\n` line endings and **no header**, sorted by the **reversed** word (code-point order), then stress index, then flags. Each row has **3 fields, or 4 when it has flags**:

```
ancora,0,301,1
ancora,3,489
amore,2,512
pinca,1,32,6
```

| field | type | meaning |
|---|---|---|
| `word` | str | NFC lowercase spelling, with orthographic accents (*città*, *perché*) |
| `stress` | int | character index of the stressed vowel in `word` |
| `zipf` | int | Zipf × 100 (1 to about 750), used for ranking: higher is more frequent |
| `flags` | int, **optional** | bitfield, written only when ≠ 0 |

`word` contains only the letters `a`–`z` and the precomposed vowels `à è é ì í ò ó ù ú` (`ALLOWED_CHARS` in `config.py`), each a single code point (and a single UTF-16 code unit), so the reversed-word order can be compared character by character from the end. There is at most one row per (`word`, `stress`): readings that differ only in vowel quality (*pèsca*/*pésca*, *bòtte*/*bótte*) rhyme the same and are merged, with the summed frequency. A word with several rows is a homograph; exactly one of its rows has no flag 1, and that is its default reading.

Flags mark exceptions only, so the normal case is a 3-field row. A row's value is the sum of its flags (`pinca,1,32,6`: predicted and vulgar); vowel quality is not exported:

| bit | value | meaning |
|---|---|---|
| 0 | 1 | non-default reading of a homograph |
| 1 | 2 | stress predicted by the model (attested and rule-derived stress count as normal) |
| 2 | 4 | vulgar / offensive / derogatory |
| 3 | 8 | archaic / poetic / literary |
| 4 | 16 | proper noun |

**Deterministic.** The same raw sources produce a byte-identical CSV: the sort key above is total, the model has a fixed seed (`MODEL_SEED`), sets and dicts are never iterated unsorted on the way to the output, and nothing variable (no build date) goes inside the file. A rebuild with unchanged sources therefore leaves the committed file untouched.

**Fixed filename.** The file keeps the same name, so git shows each dictionary update as an ordinary line diff. Cache busting happens later, in the site build step ([`build.py`](../README.md#compilazione-per-la-pubblicazione)), which publishes it under a name with its content hash; since the output is deterministic, that hash changes only when the dictionary really changes. `report.md` states the CSV's sha256, so a deployed file can be matched to a build.

**Size.** The only trim is the lexicon rule above: forms found in no corpus and listed by a single lexicon (reason `few_lexicons` in the report's excluded forms). It takes the file from 15.8 MB (4.3 MB gzipped) to 10.0 MB (2.9 MB gzipped) and drops ~318k forms, mostly generated inflections no corpus has seen; the enclitics (verb + clitics) are exempt, being regular and good rhymes. `UNSEEN_MIN_LEXICONS = 1` in `config.py` keeps every form; an `add` line in `overrides.tsv` brings back a single reading. `report.md` gives the file size and the row counts per Zipf band and per flag.

## Curation

Three hand-edited, tab-separated files in `curation/`. Lines starting with `#` are comments; each file documents its columns at the top.

| File | Columns | Use |
|---|---|---|
| `overrides.tsv` | `form, stress_idx, action, note` | Manual fixes; they always win over every source. None are in use yet (the file has only its header). |
| `gold.tsv` | `form, stress_idx, default, note` | Hand-checked stress and homographs; the tests require a minimum accuracy on it. |
| `freq_pairs.tsv` | `more, less, note` | "*A* is more common than *B*" judgements; the tests require a minimum agreement. |

**Adding an override.** `action` is `add` (an extra reading), `remove` (drop the `form, stress_idx` reading, or the whole form when `stress_idx` is empty) or `fix` (this reading replaces all the others). `stress_idx` is the index in the real spelling; let the code compute it rather than counting:

```sh
uv run python -c 'from rimario_build import text; print(text.resolve_spelling("rùbrica"))'
# ('rubrica', 1, None)
```

Then add the row (`rubrica`, `1`, `fix`, a note saying why) and rebuild with `uv run rimario-build --offline`. Forms in the report's lists of conflicts, 50/50 homograph splits and frequent words without attested stress are the best candidates.

## Tests

```sh
uv run pytest
```

`tests/test_curation.py` checks that the curation files are well-formed and that the committed dictionary meets the thresholds in `config.py` (`GOLD_MIN_ACCURACY`, `FREQ_PAIRS_MIN_AGREEMENT`); the tests that need `web/parole-accenti-frequenze.csv` are skipped until it has been built.

## Beyond this folder

- How the frontend (`web/`) is told the URLs of the dictionary and of `ATTRIBUTION.md`: the "Integrazione" section of the [repository README](../README.md#integrazione).
- Publishing the dictionary under a cache-busted name, and the L'AvisioBlog version: `build.py`, described in the [repository README](../README.md#compilazione-per-la-pubblicazione).
