# Reproducing this repository

Built on {{TODAY}} from PDFs retrieved from agm.gov.bz on {{RETRIEVED}}, by the scripts in `tools/build/` (copied there as run). The sha256 of every PDF the build read is in [`data/source-sha256.tsv`](data/source-sha256.tsv) (and in `laws.csv`), so a copy of those files can be checked byte for byte before rebuilding. How the files were retrieved is not part of this record. The scripts were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`); no AI model runs during the build or the checks, and no AI wrote any legal text.

| Script | sha256 |
| --- | --- |
| source_files.py | `{{SHA_SOURCE_FILES_PY}}` |
| parse_pdf.py | `{{SHA_PARSE_PDF_PY}}` |
| subsid.py | `{{SHA_SUBSID_PY}}` |
| ocrdates.py | `{{SHA_OCRDATES_PY}}` |
| titles.py | `{{SHA_TITLES_PY}}` |
| check_words.py | `{{SHA_CHECK_WORDS_PY}}` |
| build.py | `{{SHA_BUILD_PY}}` |
| docs.py | `{{SHA_DOCS_PY}}` |

## Steps

With the retrieved listing and PDFs in place (each PDF matching its sha256 in `data/source-sha256.tsv`; `source_files.py` says where the build looks for them):

```sh
pip install pymupdf
# Build. --today dates the documentation commit and is the latest date allowed. The first run parses every PDF
# (about 30 minutes, one process) and caches the result by the PDF's and the parser's sha256 (and, for an
# instrument split off a subsidiary-laws file, where it starts and ends).
python build.py ../belize-law-build --today {{TODAY}}
```

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
python tools/build/check_words.py .                # letters and digits of every law against its PDF (needs the PDFs)
```

Rebuilding twice from the same PDFs gives the same `git rev-parse HEAD`.
