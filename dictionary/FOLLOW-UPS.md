# Follow-ups

Possible later work on the dictionary build. None of it blocks a release.

## Worklist of Wiktionary fixes

Turn the build's findings into a list of fixes to contribute back to Wiktionary, so the source improves and later builds need fewer overrides.

- **Input:**
  - from the QA report: its "Stress conflicts between sources" list (forms where English and Italian Wiktionary disagree), and its list of frequent forms with no attested stress;
  - it.wiktionary pages whose `{{-verb form-}}` section implies a stress different from the page's `{{-sill-}}` (the *vìola*/*càpitano* case). The `kaikki_it` extractor already keeps the page's `{{-sill-}}` stress off the form-of entries of pages that also have a lemma entry, but it only logs how many rows it withheld; listing the pages (and which of them really differ) is part of this work;
  - entries fixed in `curation/overrides.tsv`, if any are added.
- **Output:** a page or file grouped by Wiktionary page, each with the suggested hyphenation/IPA and the evidence (the other source, or the conjugation table).
- **Scope:** generating the list only. The edits are made by hand on Wiktionary.
