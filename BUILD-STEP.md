# Site build step

Notes for replacing the makeshift deployment (`lavisioblog/buildhtml.py`, which is gitignored and edited by hand) with a real build step. Neither the dictionary overhaul (`dictionary/OVERHAUL-PLAN.md`) nor the frontend notes (`web/FRONTEND-NOTES.md`) cover it.

## Inputs and outputs

- **Inputs:** the frontend sources in `web/`, and the dictionary at `dictionary/out/parole-accenti-frequenze.csv` (fixed name, committed) with `dictionary/out/ATTRIBUTION.md`.
- **Outputs** in a gitignored `dist/`:
  - **standalone site:** `index.html`, CSS, JS and the cache-busted dictionary;
  - **L'AvisioBlog version:** the single inline HTML fragment that `buildhtml.py` produces today, plus the dictionary file to upload to WordPress.

## Cache busting with content hashes

- Copy the dictionary as `parole-accenti-frequenze_<hash>.csv`, where `<hash>` is the first 8–10 hex characters of its sha256. The name changes only when the contents change, so visitors re-download it only when needed, and two builds can never share a name with different contents.
- Write that name into the JS when building, instead of the hard-coded `dictionary_link` in `rimario.js` and the string replacement in `buildhtml.py`. For example, replace a placeholder like `__DICTIONARY_FILE__`, or prepend a tiny generated config. *(Superseded: the URL now goes into `data-dictionary-url`, see "Frontend hooks". The JS needs no rewriting.)*
- Optional: hash the standalone CSS/JS filenames the same way.
- For the blog, the uploaded file's URL (`wp-content/uploads/<year>/<month>/…`) depends on the upload date. Take the base URL as a parameter and print the exact name to upload.

## Carry over from `buildhtml.py`

These are what the inline version does today:
- ~~CSS adjustments: scope `body` to `#main-body`, remove the top margin, use `[disabled]` instead of `:disabled`, set `pointer-events`/`text-align` for divs;~~ *not needed: all CSS is scoped under `#rimario` with no `body` rules, and the page margin lives in the standalone-only `<style>` block;*
- ~~`<button>` → `<div>` with matching JS (`toggleAttribute`, `removeAttribute`);~~ *not needed: the CSS resets theme styles on the widget's buttons;*
- ~~◀/▶ glyphs replaced with `<`/`>` entities or words;~~ *not needed: the new UI has no such glyphs;*
- ~~comment stripping;~~ *not needed (minifying is optional);*
- the hidden SEO heading; *probably unnecessary: the fragment has an `<h1>` (logo with alt text) and a visible tagline, see "Frontend hooks";*
- the licence header. *Still needed.*

The text replacements are fragile because they depend on exact whitespace. Prefer making the frontend source itself blog-friendly where possible, or use explicit markers in the sources, so the build has less to rewrite.

## Frontend hooks

What the frontend (`web/`) provides for the build:

- **Fragment markers:** the widget is everything between `<!-- rimario:begin -->` and `<!-- rimario:end -->` in `web/index.html` (the `<div id="rimario">`). The blog version takes that fragment plus the bundled CSS and JS.
- **Config by data attributes** on `#rimario` (one per line in `index.html`, easy to rewrite):
  - `data-dictionary-url`: write the content-hashed absolute URL of the dictionary here (the dev value is `../dictionary/out/parole-accenti-frequenze.csv`);
  - `data-attribution-url`: the published URL of `ATTRIBUTION.md` (dev value `../dictionary/out/ATTRIBUTION.md`); also rewrite the matching static `href` of the footer link, which is the no-JS fallback;
  - `data-dictionary-bytes` (optional): the decompressed CSV size, so the progress bar stays determinate when the server gzips the file;
  - `data-title-suffix` (optional): the text after "Rime con X | " in the page title; defaults to the page's initial `document.title`.
- **Preloads:** `index.html`'s `<head>` has a `<link rel="preload" … as="fetch" crossorigin>` for the dictionary, so the download starts before the JS modules load. Write the same URL into its `href` as into `data-dictionary-url`, or the file downloads twice. The blog version can keep it (a preload link is allowed in `<body>`) or drop it. The `modulepreload` links are for the unbundled standalone site only.
- **Standalone-only styles:** the inline `<style>` block in `index.html`'s `<head>` (body margin, background, font) is for the standalone page only; drop it in the blog version.
- **JS:** native ES modules, entry `web/js/app.js` (imports `text.js`, `dictionary.js`, `search.js`, `ui.js`). Bundle them into one script for the blog (for example with esbuild), or keep `<script type="module">` for the standalone site.
- **CSS:** `web/rimario.css`, entirely scoped under `#rimario`, with container queries instead of viewport media queries. A theme with a sticky header can set `--sri-sticky-top` on `#rimario`.
- **Logo:** `web/logo.svg`, referenced by an `<img>` in the fragment. Inline it or upload it and rewrite the `src`. `web/favicon.svg` is for the standalone site.
- **Headings:** the fragment starts with an `<h1>` (the logo). In the blog page, where the post title is already the `<h1>`, it may need downgrading to a `<p>` or `<div>` (keep the `sri-title` class, which the CSS styles).

## Clean-up

- Remove `web/parole-accenti-frequenze_2026-02-23.csv` once the build reads the dictionary from `dictionary/out/`.
- Decide whether `lavisioblog/` stays gitignored. The build script should be tracked; only its output belongs in `dist/`.
- Add the attribution from `ATTRIBUTION.md` to both outputs (see `web/FRONTEND-NOTES.md` §6).
