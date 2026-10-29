# Reproducing this repository

Built on 2026-10-29 from PDFs retrieved from agm.gov.bz on 2026-10-28, by the scripts in `tools/build/` (copied there as run). The sha256 of every PDF the build read is in [`data/source-sha256.tsv`](data/source-sha256.tsv) (and in `laws.csv`), so a copy of those files can be checked byte for byte before rebuilding. How the files were retrieved is not part of this record. The scripts were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`); no AI model runs during the build or the checks, and no AI wrote any legal text.

| Script | sha256 |
| --- | --- |
| source_files.py | `571c7d205d5187f5593973afa2377d3c6883bf10a143e46227fd6a436202a555` |
| parse_pdf.py | `f32cf5a37fdc2b5107ab3af0db692e8e189387278ababcac018759eb465b18e7` |
| subsid.py | `cdad6203e2f8f790b623f9244d6714c9b871b1b2f72d2fbf85ece1bea121fb6a` |
| ocrdates.py | `b626fa54e9f7b1595a52f0b4822a6a962ba9826b00fd86b098963b2919f71004` |
| titles.py | `cf6974c1adad98be9d0f7ee76c90d07241c92a51453fd3a20b3611f2791f67f1` |
| check_words.py | `8930ad1bfbe9785b76ecd7ebd1089d160c9d639b985f5ec344c575ab7a1c10a8` |
| build.py | `588c38911d75859dddef9074bfdadb87367980524c7950a84a80b0e55b755084` |
| docs.py | `fe46210398d4efdc4aec840da155251671679b600c6aa544179a7eb015c6ebf4` |

## Steps

With the retrieved listing and PDFs in place (each PDF matching its sha256 in `data/source-sha256.tsv`; `source_files.py` says where the build looks for them):

```sh
pip install pymupdf
# Build. --today dates the documentation commit and is the latest date allowed. The first run parses every PDF
# (about 30 minutes, one process) and caches the result by the PDF's and the parser's sha256 (and, for an
# instrument split off a subsidiary-laws file, where it starts and ends).
python build.py ../belize-law-build --today 2026-10-29
```

## What the build produced

- 413 Chapters of the Revised Edition 2020 (15,737 section and schedule files) and 228 Acts of 2021-2026 (3,792 files); 413 Chapters and 229 Act PDFs were listed.
- 1,039 subsidiary instruments (12,897 files) from 230 of the 253 listed subsidiary-laws files (222 split by their contents list, 8 kept whole).
- 795 statutory instruments (4,827 files) of the 1,077 listed; 235 scans, 20 web pages and 4 undated ones not built (`data/si-not-built.csv`).
- 2,476 commits: one per law and one documentation commit.
- 19,883 margin citations and 142 Chapter names from long titles in `data/amendments.csv`.
- 588 rows in `data/issues.csv`.

## Checks

```sh
git rev-list --merges --count main                  # 0
git log --format='%(trailers:key=In-force,valueonly)' main | grep . | sort -c -r   # dates never go back
git log --format=%B main | tr -cd '\r' | wc -c      # 0: no carriage returns in messages
python tools/in_force_on.py 2026-10-29 cap/101 12
python tools/build/check_words.py .                # letters and digits of every law against its PDF (needs the PDFs)
```

Rebuilding twice from the same PDFs gives the same `git rev-parse HEAD`.
