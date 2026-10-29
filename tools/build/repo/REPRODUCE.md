# Reproducing this repository

Built on {{TODAY}} from PDFs retrieved from agm.gov.bz on {{RETRIEVED}}, by the scripts in `tools/build/` (copied there as run). The scripts were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`); no AI model runs during the fetch, the build or the checks, and no AI wrote any legal text.

| Script | sha256 |
| --- | --- |
| fetch.py | `{{SHA_FETCH_PY}}` |
| parse_pdf.py | `{{SHA_PARSE_PDF_PY}}` |
| subsid.py | `{{SHA_SUBSID_PY}}` |
| check_words.py | `{{SHA_CHECK_WORDS_PY}}` |
| build.py | `{{SHA_BUILD_PY}}` |
| docs.py | `{{SHA_DOCS_PY}}` |

## Steps

```sh
pip install pymupdf
# 1. The list of laws: one POST /api-laws/ per volume or list (44 requests, half a second apart).
python fetch.py catalogue
# 2. Every PDF on the list (about 2,000 files, 1 GB; at most 4 at a time; resumable).
#    An answer that is not a PDF (the site's HTML error page) is cached as <file>.err and not asked again.
python fetch.py pdfs
# 2b. Any listed PDF still missing (a network failure on the first pass), one request at a time, 3 seconds apart.
python fetch.py missing
# 3. Build. --today dates the documentation commit and is the latest date allowed. The first run parses every PDF
#    (about 30 minutes, one process) and caches the result by the PDF's and the parser's sha256 (and, for an
#    instrument split off a subsidiary-laws file, where it starts and ends).
python build.py ../belize-law-build --today {{TODAY}}
```

## robots.txt, terms and bulk data


## Fetch rate

The site sets no Crawl-delay. `fetch.py catalogue` makes its 44 listing requests one at a time, half a second apart. `fetch.py pdfs` downloads at most 4 PDFs at a time, starting the next only when one finishes, with a browser User-Agent naming the archive ("Lexifina law archive"); each PDF took a few seconds, and the whole fetch of about 2,000 files (1 GB) took a few hours over 2026-10-28. Every file is kept under `.cache/` (git-ignored) and never asked for again.

## What the build produced

- {{CHAPTERS}} Chapters of the Revised Edition 2020 ({{CHAPTER_UNITS}} section and schedule files) and {{ACTS}} Acts of 2021-2026 ({{ACT_UNITS}} files); {{LISTED_CHAPTERS}} Chapters and {{LISTED_ACTS}} Act PDFs were listed.
- {{SUBSIDIARY}} subsidiary instruments ({{SUBSIDIARY_UNITS}} files) from {{SUBSIDIARY_FILES}} of the {{LISTED_SUBSIDIARY}} listed subsidiary-laws files ({{SUBSIDIARY_SPLIT_FILES}} split by their contents list, {{SUBSIDIARY_WHOLE}} kept whole).
- {{SIS}} statutory instruments ({{SI_UNITS}} files) of the {{LISTED_SI}} listed; {{SI_SCANS}} scans, {{SI_PAGES}} web pages and {{SI_UNDATED}} undated ones not built (`data/si-not-built.csv`).
- {{COMMITS}} commits: one per law and one documentation commit.
- {{MARGIN_CITES}} margin citations and {{NAMES_ROWS}} Chapter names from long titles in `data/amendments.csv`.
- {{ISSUES}} rows in `data/issues.csv`.

## Checks

```sh
git rev-list --merges --count main                  # 0
git log --format='%(trailers:key=In-force,valueonly)' main | grep . | sort -c -r   # dates never go back
git log --format=%B main | tr -cd '\r' | wc -c      # 0: no carriage returns in messages
python tools/in_force_on.py {{TODAY}} cap/101 12
python tools/build/check_words.py .                # letters and digits of every law against its PDF (needs the cache)
```

Rebuilding twice from the same PDFs gives the same `git rev-parse HEAD`.
