# Reproducing this repository

Built on 2026-10-29 from PDFs retrieved from agm.gov.bz on 2026-10-28, by the scripts in `tools/build/` (copied there as run). The scripts were written by Claude Code running Claude Opus 5.5 (`claude-opus-5-5`); no AI model runs during the fetch, the build or the checks, and no AI wrote any legal text.

| Script | sha256 |
| --- | --- |
| fetch.py | `3f1e5f7650efc75da14da90add891867e40097ec85ee53c1bb21c1f8634a3afb` |
| parse_pdf.py | `2319fb4b2acdba1771501b11eca3122e65fe35352d6f15d859a41265d21ebb9b` |
| subsid.py | `fc0e07e118dfb7d2a5f674dd055458ce94b53d6620937623c0bdec2d368e77e8` |
| check_words.py | `c6532d05c82614168cad59f2ac9cfb80a57e08537e49c99b73de23c6cc83b22f` |
| build.py | `3660671318bb9156d6be6bd81aaf55f52e32dc3d2338420f7f9ea7dc5e709c88` |
| docs.py | `752ee1f9f8312461c4bda638e6ef058a754e5c613b78927fefc793a92e5c5285` |

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
python build.py ../belize-law-build --today 2026-10-29
```

## robots.txt, terms and bulk data


## Fetch rate

The site sets no Crawl-delay. `fetch.py catalogue` makes its 44 listing requests one at a time, half a second apart. `fetch.py pdfs` downloads at most 4 PDFs at a time, starting the next only when one finishes, with a browser User-Agent naming the archive ("Lexifina law archive"); each PDF took a few seconds, and the whole fetch of about 2,000 files (1 GB) took a few hours over 2026-10-28. Every file is kept under `.cache/` (git-ignored) and never asked for again.

## What the build produced

- 413 Chapters of the Revised Edition 2020 (15,735 section and schedule files) and 228 Acts of 2021-2026 (3,790 files); 413 Chapters and 229 Act PDFs were listed.
- 1,041 subsidiary instruments (12,783 files) from 230 of the 253 listed subsidiary-laws files (222 split by their contents list, 8 kept whole).
- 772 statutory instruments (4,820 files) of the 1,077 listed; 235 scans, 20 web pages and 27 undated ones not built (`data/si-not-built.csv`).
- 2,455 commits: one per law and one documentation commit.
- 19,878 margin citations and 142 Chapter names from long titles in `data/amendments.csv`.
- 599 rows in `data/issues.csv`.

## Checks

```sh
git rev-list --merges --count main                  # 0
git log --format='%(trailers:key=In-force,valueonly)' main | grep . | sort -c -r   # dates never go back
git log --format=%B main | tr -cd '\r' | wc -c      # 0: no carriage returns in messages
python tools/in_force_on.py 2026-10-29 cap/101 12
python tools/build/check_words.py .                # letters and digits of every law against its PDF (needs the cache)
```

Rebuilding twice from the same PDFs gives the same `git rev-parse HEAD`.
