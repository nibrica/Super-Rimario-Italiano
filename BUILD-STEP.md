# Site build step

Notes for replacing the makeshift deployment (`lavisioblog/buildhtml.py`, which is gitignored and edited by hand) with a real build step. Neither the dictionary overhaul (`dictionary/OVERHAUL-PLAN.md`) nor the frontend notes (`web/FRONTEND-NOTES.md`) cover it.

## Inputs and outputs

- **Inputs:** the frontend sources in `web/`, and the dictionary at `dictionary/out/parole-accenti-frequenze.csv` (fixed name, committed) with `dictionary/out/ATTRIBUTION.md`.
- **Outputs** in a gitignored `dist/`:
  - **standalone site:** `index.html`, CSS, JS and the cache-busted dictionary;
  - **L'AvisioBlog version:** the single inline HTML fragment that `buildhtml.py` produces today, plus the dictionary file to upload to WordPress.

## Cache busting with content hashes

- Copy the dictionary as `parole-accenti-frequenze_<hash>.csv`, where `<hash>` is the first 8–10 hex characters of its sha256. The name changes only when the contents change, so visitors re-download it only when needed, and two builds can never share a name with different contents.
- Write that name into the JS when building, instead of the hard-coded `dictionary_link` in `rimario.js` and the string replacement in `buildhtml.py`. For example, replace a placeholder like `__DICTIONARY_FILE__`, or prepend a tiny generated config.
- Optional: hash the standalone CSS/JS filenames the same way.
- For the blog, the uploaded file's URL (`wp-content/uploads/<year>/<month>/…`) depends on the upload date. Take the base URL as a parameter and print the exact name to upload.

## Carry over from `buildhtml.py`

These are what the inline version does today:
- CSS adjustments: scope `body` to `#main-body`, remove the top margin, use `[disabled]` instead of `:disabled`, set `pointer-events`/`text-align` for divs;
- `<button>` → `<div>` with matching JS (`toggleAttribute`, `removeAttribute`);
- ◀/▶ glyphs replaced with `<`/`>` entities or words;
- comment stripping;
- the hidden SEO heading;
- the licence header.

The text replacements are fragile because they depend on exact whitespace. Prefer making the frontend source itself blog-friendly where possible, or use explicit markers in the sources, so the build has less to rewrite.

## Clean-up

- Remove `web/parole-accenti-frequenze_2026-02-23.csv` once the build reads the dictionary from `dictionary/out/`.
- Decide whether `lavisioblog/` stays gitignored. The build script should be tracked; only its output belongs in `dist/`.
- Add the attribution from `ATTRIBUTION.md` to both outputs (see `web/FRONTEND-NOTES.md` §6).
