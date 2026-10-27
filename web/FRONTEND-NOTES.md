# Frontend notes

Changes and ideas to apply during the frontend overhaul. The dictionary overhaul (`dictionary/OVERHAUL-PLAN.md`) produces the new data file. This file lists what the frontend needs to change to use it, plus improvements that came up along the way. The new dictionary and the new frontend are deployed together, so no legacy support is needed.

---

## 1. New data format (required)

The authoritative spec is §8 of `dictionary/OVERHAUL-PLAN.md`. In short:

- CSV, no header, sorted by **reversed word**, then stress index, then flags. The reversed-word binary search stays as it is.
- Each row has **3 or 4 fields**: `word,stress,zipf[,flags]`. The 4th field is present only when flags ≠ 0, so parse it as optional: `const [word, stress, zipf, flags = 0] = row.split(',')`.
- `zipf` is Zipf × 100 (3 digits) instead of a raw count. Sorting by it works the same way.
- `flags` is a bitfield that marks exceptions:

| value | meaning |
|---|---|
| 1 | non-default reading of a homograph |
| 2 | stressed vowel open (è/ò), only where it's the sole difference between two readings |
| 4 | stressed vowel closed (é/ó), same rule |
| 8 | stress predicted by a model (lower confidence) |
| 16 | vulgar / offensive / derogatory |
| 32 | archaic / poetic / literary |
| 64 | proper noun |

- The dictionary file has a fixed name in the repo (`dictionary/out/parole-accenti-frequenze.csv`). The site build step publishes it under a content-hashed name and injects that name into the JS, so `rimario.js` should stop hard-coding the filename. See `BUILD-STEP.md` at the repository root.

## 2. Homographs

- **Choosing the default:** pick the row **without** flag 1. Today `GetFirstAccent` picks whichever row comes first, which depends on sort order.
- **More than two readings:** collect every adjacent row with the same word. Today only the previous and next row are checked, so a third reading is lost.
- **Vowel-quality pairs** (flag 2 or 4, same word and stress): show *pèsca* / *pésca* with the right accent. `ExplicitAccent` always adds a grave accent (`̀`); it should use an acute (`́`) for closed vowels.

## 3. qu/cu equivalence

Endings with *qu* and *cu* before a vowel sound almost the same but are spelled differently, so the suffix search misses pairs like *obliquo* / *proficuo* or *iniquo* / *cospicuo*. Handle it like the existing è/é swap in `SearchPerfectRhymes`: when the rhyme suffix contains `qu`/`cqu`/`cu` + vowel, search the other spellings too.

Caveat: after *c*, the *u* is usually a separate syllable (*co-spì-cu-o*), while after *q* it glides (*i-nì-quo*). They sound the same at the end but differ by one syllable. You might decide to show these matches with the near-rhymes instead of the perfect rhymes.

## 4. Using the flags

All of these are UI choices that the data makes possible:
- Hide vulgar/offensive words (16) by default, behind a toggle. Probably useful when the page is embedded in a blog.
- Toggles for archaic/poetic (32) and proper nouns (64).
- A subtle marker on words with predicted stress (8), plus a way to report a wrong accent.

## 5. Memory and speed

The site already uses a lot of memory. Main causes in today's `rimario.js`:
- **One small array per row** (`[word, accent, freq]`): over 200k arrays, plus their strings. Alternatives:
  - parallel arrays: one array of words, `Uint8Array` for stress, `Uint16Array` for zipf, `Uint8Array` for flags;
  - keep the raw text and an `Int32Array` of line offsets, and decode rows only when they're read.
- **`[...segmenter.segment(...)]` on every binary-search step** allocates arrays during every search. The new dictionary contains only NFC lowercase letters plus precomposed accented vowels, all single UTF-16 code units, and the build sorts by code point. So the comparison can walk the two strings backwards by `charCodeAt`, with no segmenter, no `alphabetical_order` map and no allocations. The binary search itself stays the same.

## 6. Attribution (required)

The data comes from CC BY-SA and CC BY sources, which require credit. The build writes `ATTRIBUTION.md` next to the CSV. The page footer (and the L'AvisioBlog version) must show or link it, replacing the current Wiktionary/CoLFIS credits.
