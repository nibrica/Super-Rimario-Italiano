# Dictionary overhaul plan

**Goal:** a dictionary that is bigger, more accurate on stress, aware of homographs and ranked by modern frequency. It should be built in minutes, with one command that first fetches the latest version of every source.

**In scope:** everything under `dictionary/`: sources, fetching, build code, curation files, tests, and the output data file with its format.
**Out of scope (separate session):** the frontend (`web/`), and copying the data into the site / L'AvisioBlog (`lavisioblog/`). This plan ends at a documented output file (§8). Frontend changes that the new format needs are collected in `web/FRONTEND-NOTES.md`, and the site build step (cache-busted filenames, L'AvisioBlog version) in `BUILD-STEP.md` at the repository root. No legacy support: the new dictionary and the new frontend are deployed together.

**Source rule:** every source must be **redistributable, and usable commercially, inside a GPL project**, and it must be **downloadable automatically**. No test-only, non-commercial, or manually downloaded data.

---

## 0. What's wrong today (measured)

| Problem | Evidence |
|---|---|
| **Slow** | `espeak` is spawned once per word (~5 ms × ~100k). `build_list()` finds each frequency by scanning the whole CoLFIS list, which is O(n×m). `mwxml` parses 650 MB of XML in pure Python. The cost comes from the algorithms, not from running on one core. |
| **Homographs mostly missing** | Only **253** homographs in 212,750 rows. it.wiktionary pages have one `{{-sill-}}` even when they also contain a `{{-verb form-}}` with different stress: `viola` → only *viòla*, `capitano` → only *capitàno*. The dump has 289k verb-form sections, and none gets its own stress. |
| **Homographs share one frequency** | `ancora,0,4009` / `ancora,3,4009`. The default reading depends on sort order. |
| **Frequencies sparse and old** | **64%** of rows have frequency 0. CoLFIS is 1990s print (~3M tokens), and its website is now unreachable. |
| **The espeak fallback is brittle** | It parses phoneme strings with regexes, fails silently on w/y/j/k/x, and gives no confidence. |
| **No vowel quality** | *pèsca*/*pésca* can't be told apart. |
| **Noisy gatekeeper lists** | napolux/witalian/pazqo decide which words go in. |

---

## 1. Sources

### Kept (all fetched automatically)

| id | Provides | License | Download URL | "Latest" | Size |
|---|---|---|---|---|---|
| `kaikki_en` | English-Wiktionary Italian entries: one per etymology/POS, IPA with ɛ/e ɔ/o, stress-marked hyphenation (`grà‧tis`), **stress-marked conjugation and inflection tables** (`càpito, càpitano, dièdi, diédi`) | CC BY-SA | `https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl.gz` | URL always serves latest (weekly; checked via ETag) | 77 MB |
| `kaikki_it` | Italian-Wiktionary entries already parsed: `hyphenations.parts` (`cà`,`sa`), IPA, POS, verb-form → lemma glosses | CC BY-SA | `https://kaikki.org/dictionary/downloads/it/it-extract.jsonl.gz` | URL always serves latest | 44 MB |
| `morphit` | ~505k inflected forms → lemma + morphological features | CC BY-SA 2.0 / LGPL | `https://docs.sslmit.unibo.it/lib/exe/fetch.php?media=resources:morph-it.tgz` | fixed URL (last changed 2018; Last-Modified checked) | 2.6 MB |
| `wordfreq` | Merged Italian Zipf frequencies (Wikipedia, subtitles, news, books, web, social; snapshot ≈2021, frozen upstream) | data CC BY-SA 4.0 | PyPI package `wordfreq` (3.1.1) | dependency version | — |
| `opensubtitles` | Spoken-register counts (OpenSubtitles 2018, full list) | CC BY-SA 4.0 | `https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/it/it_full.txt` | fixed URL (ETag) | 10 MB |
| `leipzig_news` | Recent news **sentences** (1M) → fresh counts after 2021, plus context for splitting homographs | CC BY (download corpora) | `https://downloads.wortschatz-leipzig.de/corpora/ita_news_{YEAR}_1M.tar.gz` | probe from the current year downwards; use **only the newest year** that exists (currently 2024) | ~260 MB |

### Dropped, and why

| Source | Reason |
|---|---|
| it.wiktionary XML dump + `mwxml` | Replaced by `kaikki_it`, the same data already parsed. |
| CoLFIS | Outdated (2005), its site is down, and it can't be fetched automatically. |
| napolux / pazqo lists | The same list twice (identical as sets), with **all accents stripped** (`citta`, `perche`, `scorgera`). It can't validate oxytone words, and it lets accent-less typos through (`piu`, `gia` are in today's CSV). **Already removed**, together with `licenses/`. |
| witalian list | Clean but redundant: no stress, no frequency, and its forms are covered by Morph-it + Kaikki. 8k entries are elided phrases (`dell'anfibio`). **Already removed.** |
| espeak / espeak-ng | Replaced by paradigm rules plus a trained model (§5). Removes the system dependency. |
| PhonItalia, STRESYL, PAISÀ, SUBTLEX-IT | Non-commercial or unclear licence. |
| spaCy / Stanza Italian taggers | Their models are trained on Italian UD treebanks licensed CC BY-NC-SA. Homographs are split with lexicon-based rules instead (§6.4). |
| Wikidata Lexemes, Hunspell it_IT, Google Books | Little gain over Kaikki/wordfreq for a large download or extra tooling. Reconsider only if the QA report shows gaps. |

**Attribution:** CC BY-SA and CC BY require credit. The build writes `ATTRIBUTION.md` next to the output, with each source, its licence, the cited papers (wiktextract LREC 2022, Leipzig LREC 2012) and the fetched versions. wordfreq's README notes that a bare CSV can't carry attribution, so the frontend session must show or link this file.

---

## 2. Fetching the latest sources

`rimario-build` runs **fetch → build** by default.

- Each source is declared in `sources.toml` (id, resolver, URL or pattern, licence, attribution text). Resolvers: `http` (fixed URL), `leipzig` (probe the years), `package` (Python dependency).
- **Conditional download:** send `If-None-Match` / `If-Modified-Since` using the values from `sources.lock.json`, so a source is only downloaded again when the server has a newer version. Download to a temp file → verify size → sha256 → atomic rename into `data/raw/<id>/`. Keep only the current version of each source.
- **`sources.lock.json` (committed):** resolved URL, ETag/Last-Modified, sha256, size and fetch time for every source in the last build. It shows exactly which data produced a given dictionary, and the QA report diffs it against the previous build.
- **Failures:** if a source can't be reached and a local copy exists, use the copy, warn, and record it in the report. If there's no local copy, abort with a clear message.
- **Flags:** `--offline` (skip fetch, use what's on disk) and `--only <id>` (fetch/rebuild one source).
- **Safety:** downloads are data only and are never executed. Tarballs are opened with `tarfile` `filter="data"`, and only the expected members are extracted (`*-sentences.txt` for Leipzig, the lexicon file for Morph-it).

Note: Kaikki serves only its latest file, so rebuilding a *past* dictionary exactly needs the raw files kept. The lockfile detects the mismatch (sha256) but can't recover old versions.

---

## 3. Final structure

```
dictionary/
├── README.md                  how to build; sources + licences; output format
├── pyproject.toml             deps + `rimario-build` entry point (managed with uv)
├── uv.lock
├── sources.toml               source declarations (§2)
├── sources.lock.json          versions + hashes of the last build (committed)
├── curation/
│   ├── overrides.tsv          manual fixes, always win (§5.5)
│   ├── gold.tsv               hand-checked stress + homographs (test)
│   └── freq_pairs.tsv         "A is more common than B" judgements (test)
├── src/rimario_build/
│   ├── __main__.py            CLI: fetch | build | report, --offline, --only
│   ├── config.py              paths, weights, thresholds: all knobs in one place
│   ├── schema.py              table schemas shared by every stage
│   ├── fetch.py               resolvers, conditional download, verify, lock
│   ├── cache.py               skips stages whose inputs are unchanged (hash)
│   ├── text.py                NFC/lowercase, tokenization, stress-mark ↔ index
│   ├── sources/               one module per source → one normalized table
│   │   ├── kaikki_en.py
│   │   ├── kaikki_it.py
│   │   ├── morphit.py
│   │   ├── wordfreq_it.py
│   │   ├── opensubtitles.py
│   │   └── leipzig.py         counts + homograph contexts
│   ├── stress/
│   │   ├── vote.py            combine attested evidence, detect conflicts
│   │   ├── paradigm.py        verb / noun / enclitic / suffix propagation
│   │   └── model.py           learned fallback with confidence
│   ├── frequency/
│   │   ├── merge.py           Zipf merge (§6)
│   │   └── homographs.py      frequency split between readings
│   ├── lexicon.py             which forms go in (§7)
│   ├── export.py              dictionary CSV + ATTRIBUTION.md
│   └── report.py              QA report + diff against the previous build
├── tests/
│   ├── test_text.py
│   ├── test_paradigm.py
│   ├── test_merge.py
│   └── test_curation.py       gold accuracy + freq-pair agreement thresholds
├── data/                      gitignored
│   ├── raw/<source>/
│   └── cache/                 parquet output of each stage
└── out/                       committed: the build's product
    ├── parole-accenti-frequenze.csv
    ├── ATTRIBUTION.md
    └── report.md
```

**Removed:** `dictionary/build-dictionary.py`, `dictionary/input/`, `dictionary/myenv/` (replaced by uv's `.venv`). In `.gitignore`, `/dictionary/input/*` and `/dictionary/myenv/` become `/dictionary/data/` and `/dictionary/.venv/`. `out/` is committed, so each dictionary update is a normal diff of one fixed-name file. The README's "Generazione del dizionario" and licence sections get updated to the new source list.

**Code conventions:**
- Each stage is a function from tables to a table (polars DataFrames) with no global state. Schemas live in `schema.py`.
- All tunable numbers (weights, thresholds) live in `config.py`.
- Each stage logs its duration and row counts.

**Dependencies:** Python ≥ 3.14, `polars`, `orjson`, `wordfreq`, `scikit-learn`, plus `pytest` for development. No system packages.

**Speed:**
- The extractors are independent and run in parallel (`ProcessPoolExecutor`); the Leipzig sentences are tokenized in parallel chunks.
- Joins are hash joins in polars, and unchanged stages are skipped via `cache.py`.
- Expected: a cold build in a few minutes, mostly download and decompression. A rebuild after changing the merge rules takes seconds.

---

## 4. Stages and data contracts

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
         export ─► out/   +   report
```

| Table | Columns |
|---|---|
| `forms` (from kaikki_en, kaikki_it, morphit) | `form, lemma, pos, stress_idx?, quality? (open/closed), evidence (ipa/hyphenation/table/sill/none), register_tags, source` |
| `freq` (from wordfreq_it, opensubtitles, leipzig) | `form, count or zipf, source`, plus per-source metadata: total tokens, detection floor, truncated? |
| `contexts` (leipzig) | `form, cue, count`: the token right before each form, kept only when it's one of the cue words configured for §6.4; `homographs.py` maps each cue to its class (nominal/verbal) |
| `entries` (merged) | `form, stress_idx, quality, lemma, pos, zipf, share, is_default, tier (attested/propagated/predicted), confidence, provenance` |

`stress_idx` keeps today's meaning: the character index of the stressed vowel in the NFC lowercase spelling.

Stress-marked forms (`càpitano`, `dò`) are matched to **real spellings** using the set of orthographic forms (entry titles + Morph-it), never by blindly stripping accents. This keeps orthographic accents such as *città*, *perché* and *dà*.

---

## 5. Stress

### 5.1 Voting on attested evidence
Priority: `kaikki_en` (IPA, hyphenation, tables) > `kaikki_it` (hyphenation, IPA). Each reading is a (form, stress_idx, quality, lemma/POS) tuple. If the two sources disagree on a form that has a single lemma and POS, the conflict goes to the report, where it's resolved by an override or confirmed as a real homograph. Distinct lemma/POS pairs with different stress are kept as homographs.

### 5.2 Paradigm propagation
For forms that Morph-it (or a Kaikki inflection list) knows but no source marks for stress.

**A generated form is kept only if it's attested:** it must appear in a lexicon (Kaikki, Morph-it) or in at least one frequency source (wordfreq, OpenSubtitles, Leipzig). The rules assign stress to real forms; they never invent new words. Without this, verb × clitic combinations alone could double the dictionary.
- **Verbs:** rhizotonic forms (1/2/3 sg and 3 pl present indicative/subjunctive, 2 sg imperative) take the stress of the lemma's attested 1sg (*càpito* → *càpita, càpitano, càpiti*). Arizotonic forms are stressed according to their ending (*-àvo, -erò, -iàmo, -àndo, -àto, -erèbbero, -àssimo…*).
- **Enclitics:** *dìmmelo, portàndoglielo, guardàtevi* keep the host verb's stress. Candidates are built from imperatives, gerunds and infinitives with the standard clitic combinations, then filtered by the attestation rule above. These forms are almost entirely missing today.
- **Nouns/adjectives:** inflected forms keep the stress, with a short exception list (*uòmo → uòmini*).
- **Productive suffixes:** *-ménte, -zióne, -ità, -ìsmo, -ìsta, -ìssimo, -ìno, -étto, -èllo*.

### 5.3 Learned fallback (replaces espeak)
- **Training data:** all attested readings (not propagated ones). For each vowel position, a classifier predicts "stressed or not" from the surrounding characters, the distance from the end in vowels, suffix n-grams and the POS if known (scikit-learn `HistGradientBoostingClassifier`). The highest-scoring vowel wins, and its probability is the confidence.
- **Evaluation:** held-out folds of attested data, plus `gold.tsv`.
- **Shipping rule:** ship predictions with tier `predicted` only above a confidence threshold, set per POS (names need more confidence than nouns). Low-confidence words are left out and listed in the report.

### 5.4 Vowel quality
Taken from Kaikki's IPA and accent marks (ɛ/è, e/é, ɔ/ò, o/ó) for the stressed vowel. It may stay in internal tables, but it **doesn't split rows and isn't exported**: *pèsca*/*pésca* and *bòtte*/*bótte* are one row per (word, stress), whose frequency is the sum of the two readings. The output has no vowel-quality flag (§8).

### 5.5 Curation
- `overrides.tsv`: `form, stress_idx, action (add/remove/fix), note`. It always wins, so reported bugs become one-line changes.
- `gold.tsv`: ~1,000 hand-checked forms, focused on homographs (*àncora/ancòra, prìncipi/princìpi, sùbito/subìto, càpitano/capitàno, vìola/viòla, rèsina/resìna*), enclitics and loanwords. `test_curation.py` fails if accuracy on it drops.

---

## 6. Frequency merge

### 6.1 Normalize
- Tokenize Leipzig sentences with `wordfreq.tokenize(text, "it")`, so they're split exactly like wordfreq. OpenSubtitles comes pre-counted: apply NFC + lowercase and drop tokens with apostrophes or digits.
- Convert every source to **Zipf**: `log10(count / total_tokens × 10⁹)`. wordfreq already gives Zipf.
- Store each source's **detection floor**, the Zipf of a single occurrence. wordfreq's list stops at a known cutoff, so a word missing from it is *below* that cutoff.

### 6.2 Treat a missing word as an upper bound
A word missing from a source that covers its whole vocabulary (or from one with a known cutoff) is evidence that it's rare there. It counts as one observation at `floor_s − 0.5`, with half that source's weight. The bound only applies as an upper bound: it's used where it lies below the word's real observations, and ignored where it would pull the word up. A word absent from all three sources gets no corpus estimate (§6.5).

### 6.3 Weighted mean with shrinkage
```
zipf(w) = Σ W_s · r_s(w) · zipf_s(w)  /  Σ W_s · r_s(w)
```
- **`W_s`, the source weight:** **1 for every source** (still a constant in `config.py`).
  - wordfreq already contains OpenSubtitles, so with equal weights spoken language counts somewhat more than written. This is a known effect of including the separate subtitle list, which is there for its real counts and as the third voter for the robustness check.
  - Leipzig adds post-2021 language that wordfreq doesn't have.
- **`r_s(w)`, how reliable this estimate is:** `min(1, count / 20)` for counted sources, so 3 occurrences barely count. For wordfreq it's 1 above Zipf 2 and drops toward its cutoff.
- **Robustness:** compare each source with the mean of the other two. If it's more than 1.5 Zipf away while those two agree within 0.5, cut its weight to a quarter for that word and log it. This catches news spikes (2024 events, names) and subtitle quirks (character names, swearing). The report lists the largest disagreements, and those are where to fix source-specific bias.

### 6.4 Splitting homographs
Frequency is merged per **spelling**, then split among its readings:
```
zipf(reading) = zipf(form) + log10(share(reading))
```
`share` is decided in this order:
1. **Verb vs. noun/adjective readings** (*vìola/viòla, càpitano/capitàno, sùbito/subìto, àncora/ancòra*): count the word before each occurrence of the form in the Leipzig sentences.
   - Only unambiguous cue words count. Nominal: *il, un, una, uno, i, del, della, questo, quella…* and other forms that Kaikki marks only as determiners or prepositions. Verbal: *mi, ti, si, ci, vi, ne, non*, subject pronouns.
   - Ambiguous words (*la, lo, le, li, gli*) are ignored.
   - Counts are smoothed with a small prior (α = 2), so a handful of contexts can't produce 100/0.
2. **Same-POS readings with different lemmas** (*prìncipi/princìpi*): the ratio of the lemmas' merged frequencies (*principe* vs *principio*).
3. **Proper noun vs. common word** (*Rosa*/*rosa* when stress differs, e.g. a place name): the share of capitalized occurrences that don't start a sentence in the Leipzig sentences.
4. **No usable signal:** 50/50, flagged in the report as candidates for overrides.

In the implementation, the capitalization check (3) runs before context (1), since proper nouns take no article. Context decides only when the form has at least `CONTEXT_MIN_CUES` nominal + verbal cue hits; readings that are function words (prepositions, articles, determiners, pronouns, conjunctions) take no cue side.

The reading with the largest share becomes `is_default`; the others get the *non-default* flag.

### 6.5 Forms found only in dictionaries
Forms that appear in a lexicon but in no corpus get `min_floor − 0.5`. Ties are broken by how many lexicons contain the form. The long tail gets a usable order instead of a pile of zeros. In practice `min_floor − 0.5` is close to 0, so these values sit in a small positive band starting at `LEXICON_ONLY_MIN_ZIPF`, below every corpus estimate, where even a 50/50 split of them stays above 0.

### 6.6 Validation
- `freq_pairs.tsv`: ~200 hand judgements ("*amore* > *amorevole*", "*ciao* > *salve*"). `test_curation.py` asserts a minimum agreement. It's a check on the merge, not used to tune the weights.
- Report: Spearman correlation of each source against the other two (leave-one-out).

---

## 7. Which forms go in
- **Include:** forms in at least one lexicon (`kaikki_en`, `kaikki_it`, `morphit`) or generated in §5.2, that also have a stress value at tier `attested`, `propagated`, or `predicted` above the threshold.
- **Proper nouns** (Kaikki `name` entries: places, personal names) are included **only if at least one frequency source has them**, lowercased like every other word and flagged. If a proper noun has the same spelling and stress as a common word (*rosa*), it adds no row. Whether to drop more is decided once the final size is known.
- **Exclude:** abbreviations, misspellings (Kaikki tags), and anything with characters outside the Italian alphabet plus accented vowels. Loanwords stay only if they appear in an Italian section with IPA. English words are gated by comparing wordfreq's English and Italian Zipf for the form, and Roman numerals (*ii*, *iv*, *vii*) are excluded.
- **Register and sensitivity tags** (Kaikki *archaic, poetic, literary, obsolete*; *vulgar, offensive, derogatory*) become flags, not filters. Whether to hide them is a frontend decision.

---

## 8. Output contract (hand-off to the frontend session)

`out/parole-accenti-frequenze.csv`: UTF-8, `\n` line endings, **no header**, sorted by the **reversed** word as today.

The filename is **fixed**: the file is committed, so git shows each update as an ordinary line diff of the same file. Cache busting happens later, in the site build step (`BUILD-STEP.md`), which publishes the file under a content-hashed name. The QA report states the CSV's sha256 so a build can be matched to a deployed file.

Each row has **3 fields, or 4 when it has flags**:

```
ancora,0,301,1
ancora,3,489
amore,2,512
pinca,1,32,6
```

| field | type | meaning |
|---|---|---|
| `word` | str | NFC lowercase spelling |
| `stress` | int | index of the stressed vowel |
| `zipf` | int | Zipf × 100, used for ranking (3 digits, against up to 6 for today's raw counts) |
| `flags` | int, **optional** | bitfield, written only when ≠ 0 |

**Flags mark exceptions only,** so the normal case is a 3-field row:

| bit | value | meaning |
|---|---|---|
| 0 | 1 | non-default reading of a homograph |
| 1 | 2 | stress predicted by the model (attested and rule-derived stress count as normal) |
| 2 | 4 | vulgar / offensive / derogatory |
| 3 | 8 | archaic / poetic / literary |
| 4 | 16 | proper noun |

The value of a row is the sum of its flags: `pinca,1,32,6` above is a predicted (2), vulgar (4) reading. Vowel quality is not exported (§5.4).

Also written: `out/ATTRIBUTION.md` (see §1).

**Deterministic output:** the same raw sources must produce a byte-identical CSV.
- Sort by reversed word, then by stress index, then by flags. Today's sort uses only the reversed word, so the relative order of two homograph rows depends on input order.
- The model gets a fixed random seed. Sets and dicts are never iterated unsorted on the way to the output. No build date or other variable data goes *inside* the file.
- Result: a rebuild with unchanged sources leaves the committed file untouched, and the content hash used by the site build step only changes when the dictionary really changes.

Size: today 3.2 MB raw / 0.95 MB gzipped. More forms will make it bigger. The pipeline doesn't trim anything. The report gives the size and the row count per Zipf band and per flag, and whether to trim is decided after the final dictionary is built.

---

## 9. QA report (`out/report.md`, every build)
- Source versions and what changed since the last build (from the lock).
- Row counts by tier and source; gold accuracy; held-out model accuracy; freq-pair agreement.
- **Diff against the previous build** (the committed `out/` CSV before it's overwritten): forms added or removed, stress changed, default reading changed.
- The CSV's size and sha256.
- Stress conflicts between sources, homographs split 50/50, the largest frequency disagreements, low-confidence predictions that were left out, and the 200 most frequent forms that lack attested stress (work through these first).

---

## 10. Roadmap

| Phase | Work | Done when |
|---|---|---|
| **1. Skeleton** | uv project, `sources.toml`, `fetch.py` + lockfile, `cache.py`, the `kaikki_en` / `kaikki_it` / `morphit` extractors, `stress/vote.py`, wordfreq-only frequency, `export.py` (§8 format, deterministic), report with diff. Delete the old script, `input/` and `myenv/`. | One command fetches and builds. The diff against the current CSV is reviewed (expect many more homographs and stress-marked verb forms; unattested words are missing until phase 3) |
| **2. Frequency** | `opensubtitles` + `leipzig` extractors, `frequency/merge.py`, `homographs.py`, `freq_pairs.tsv` | No zero frequencies; homographs have separate frequencies and a default |
| **3. Coverage** | `stress/paradigm.py` (verbs, enclitics, suffixes), `stress/model.py`, `gold.tsv` + `overrides.tsv` seeded from the report | Gold accuracy target met; coverage ≥ today's word count |
| **4. Cleanup** | README and licence section, `ATTRIBUTION.md` reviewed, thresholds tuned, tests in place | Ready to hand `out/` to the frontend session |

Don't publish a dictionary from this pipeline before phase 3: until then, words without attested stress are left out.

---

## Decisions
- **Trimming:** none in the pipeline; decided after the final dictionary is built (§8).
- **Frequency weights:** equal for all sources (§6.3).
- **Leipzig:** only the newest year (§1).
- **GitHub word lists:** dropped (§1).
- **Output:** one CSV, an optional 4th field for flags that mark exceptions, no legacy export; deployed together with the new frontend (§8).
- **Generated forms:** kept only if attested in a lexicon or corpus (§5.2).
- **Proper nouns:** only those with frequency data, flagged (§7).
- **Not in this plan:** phonetic rhyme keys, syllable and metre data, lemma column, poetic truncations (unnecessary or too much data); frontend ideas are in `web/FRONTEND-NOTES.md`; later work is in `dictionary/FOLLOW-UPS.md`.
- **Overrides:** none added; `curation/overrides.tsv` has no data rows (§5.5).
- **Gold threshold:** `GOLD_MIN_ACCURACY = 0.90` (§5.5).
- **Morph-it:** mirrored in the repository (`dictionary/mirror/morphit/`), because its server answers automated GETs with HTTP 402 (§1).
- **Vowel quality:** merged; it no longer splits rows and has no output flag (§5.4, §8).
- **Filename:** fixed and committed (`out/parole-accenti-frequenze.csv`); the content hash is added by the site build step (`BUILD-STEP.md`).
