# The laws of Belize, as a git repository

The legislation of Belize as a git repository: the {{CHAPTERS}} Chapters of the Substantive Laws of Belize, Revised Edition 2020 (including the Belize Constitution, Chapter 4), with the {{SUBSIDIARY}} instruments of the Subsidiary Laws made under them, the {{ACTS}} Acts passed from 2021 to 2026, as enacted, and the {{SIS}} statutory instruments of 2020 to 2026 that have a text layer, as made. The source is the [Laws of Belize](https://agm.gov.bz/laws) page of the Attorney General's Ministry. There is one file per section or schedule ({{UNITS}} files), with one paragraph per line, so `git blame` and `git diff` work line by line.

**What this repository is not: a history before 2021.** The Ministry publishes one consolidation, the Revised Edition 2020, "showing the substantive laws as at 31st December, 2020", and no earlier one. So each Chapter is a single commit holding its text as at that date (the shape called *current-only*). Nothing before that text can be rebuilt from this source, so there is no line-by-line history before 31 December 2020. The amending laws that the edition prints in its margins are kept: in the files, and listed in [`data/amendments.csv`](data/amendments.csv).

**The Acts after 2020 are kept as enacted, beside the Chapters, not applied to them.** No consolidation after 2020 is published to check an amended text against, so no amendment is replayed into a Chapter. An Act of 2021 to 2026 sits in its own folder, `acts/<year>/<number>/`, as it was passed, and its commit names the Chapters its long title mentions (`Names-chapter:`). To read a Chapter as it stands today, read the 2020 text and then the later Acts that name it.

**Subsidiary laws of the Revised Edition 2020 are in `sub/<chapter>/<item>/`**, one folder per instrument, dated 2020-12-31 like the Chapters. The Ministry publishes them one file per Chapter, each holding every instrument made under it, with a numbered list of them and their pages on its cover. The build follows that list and splits the file where each instrument's Chapter line and title are printed; `<item>` is its number in that list (`sub/4/1` is the first instrument under Chapter 4, the Belize Advisory Council (Procedure) Rules). {{SUBSIDIARY_SPLIT_FILES}} files are split this way. {{SUBSIDIARY_WHOLE}} whose list cannot be followed (no list on the cover, page numbers out of order, or an instrument whose opening is not where the list says) are kept whole in `sub/<chapter>/all/`, labelled as the whole file; the reason for each is in `data/issues.csv`.

**Statutory instruments of 2020 to 2026 are in `si/<year>/<number>/`, as made**, not applied to the instruments they amend. Each is dated by the day it says it was gazetted: under the Interpretation Act (Chapter 1, s. 21(h)), an instrument has the force of law on its publication in the Gazette, or from a date it names. {{SI_GAZETTE_DATED}} are dated that way (`In-force-basis: gazetted`), {{SI_MADE_DATED}} with no readable Gazette date by the day they say they were made (`In-force-basis: made`); both dates are in trailers (`Gazetted:`, `Made:`), and the Chapter an instrument is made under is in `Made-under:`. Of the {{LISTED_SI}} listed, {{SI_SCANS}} are scans with no text layer, {{SI_PAGES}} answer with a web page instead of a PDF, and {{SI_UNDATED}} have no readable date; they are not built and are listed in [`data/si-not-built.csv`](data/si-not-built.csv). {{SI_OCR}} more are scans under a text layer the publisher made by optical character recognition (and {{SI_PART_OCR}} have some such pages). They are built from that text as it is, errors and all, and marked `Text-layer: OCR`; read the PDF for them. The publisher offers no text version of the scans: its listing (`POST /api-laws/`) has one column, the linked name, its search returns names only, and the Internet Archive holds no earlier typeset copy. {{SI_OCR_DATES}} instruments have a Gazette or made date that could be read only from OCR text with slips in its digits or month name corrected (a "l" or "I" read as 1, "Octoher" as October); each such date is used only when it agrees with the instrument's other date, and the text as printed is kept in a `Gazetted-as-printed:` or `Made-as-printed:` trailer. `Law:` is the short title printed in the instrument's citation clause; `Law-title-from:` says where it came from: {{SI_TITLES_REPAIRED}} titles had OCR or font slips repaired only from words printed in the listed name or in the Revised Edition's titles (each repair is named there), and {{SI_TITLES_LISTED}} use the listed name, because no clean citation clause could be read.

The record holds {{CHAPTERS}} Chapters and {{SUBSIDIARY}} subsidiary instruments (dated 2020-12-31), {{ACTS}} Acts (dated {{FIRST_ACT}} to {{LAST_ACT}}) and {{SIS}} statutory instruments (dated {{FIRST_SI}} to {{LAST_SI}}), in {{COMMITS}} commits.

## A lawyer's questions as git commands

| Question | Command |
| --- | --- |
| What does section 12 of the Criminal Code (Chapter 101) say? | `python tools/in_force_on.py {{TODAY}} cap/101 12` |
| The whole of a Chapter, in order | `python tools/in_force_on.py {{TODAY}} cap/101` |
| Which laws the margin cites beside a section | `tail -1 cap/101/12.md` |
| Every section whose margin cites an Act | `grep '7 of 2018' data/amendments.csv` |
| Which Acts since 2020 name a Chapter | `git log --format='%s' --grep='^Names-chapter: 101$' main` |
| An Act as enacted | `python tools/in_force_on.py {{TODAY}} acts/2026/5` |
| The instruments made under a Chapter | `ls sub/4/` and `git log --format='%s' main -- sub/4` |
| A statutory instrument as made | `python tools/in_force_on.py {{TODAY}} si/2026/1` |
| The statutory instruments made under a Chapter | `git log --format='%s' --grep='^Made-under: Chapter 150$' main` |
| The Acts in force by a date | `git log --format='%(trailers:key=In-force,valueonly) %s' main -- acts` |
| The list of laws, with their dates | [`laws.csv`](laws.csv) |

Each section file starts with any Part headings above it (`## PART I`, `## Preliminary`), then its number and the heading printed in the margin (`# 12. Interpretation.`). Then come its paragraphs, one per line: `(1) ...`, `(a) ...`. Last, if the margin cites any laws beside the section, they are copied in one line, in print order: `- Margin notes: 40 of 1963; S.I. 34 of 2010.` The margin does not say what each law did (inserted, amended or substituted), only that it is the source of the section or of some change to it. Each Chapter's `title.md` holds its title, the derivation block under it (the laws it came from, and the date of commencement in brackets) and its index of files is `index.txt`.

## The dates, and which one we use

- **Chapters: 2020-12-31**, the as-at date of the Revised Edition, at noon Belize time (UTC-6). It is the date the consolidated text speaks from. It is not the day any section took effect: those days are not printed, and the margin gives only the amending law's number and year.
- **Subsidiary laws of the Revised Edition: 2020-12-31**, the same as-at date as the Chapters.
- **Statutory instruments: the day gazetted**, or the day made where no Gazette date can be read (see above). An instrument that names a later commencement is still dated by its Gazette date here.
- **Acts: the day of assent.** Under the Interpretation Act (Chapter 1, s. 41), an Act comes into force on the day the Governor-General assents to it, unless it sets another day or its commencement is postponed. The assent day is printed under "I assent" on each Act. {{ASSENT_DATED}} Acts are dated that way (`In-force-basis: assent`); {{GAZETTE_DATED}} with no readable assent date are dated by the day they say they were gazetted (`In-force-basis: gazetted`). Both dates are in trailers (`Assented:`, `Gazetted:`). An Act that sets a later commencement, or leaves it to an order, is still dated by assent here: the commencement clause is in its text but is not read.

`tools/in_force_on.py` answers for any date on or after 2020-12-31 (and for the statutory instruments of 2020 from their own dates). For an earlier date it says there is no version, because the source has none.

## What "author" means

Every Chapter commit has the same author: `Laws of Belize (Attorney General's Ministry) <laws-of-belize@agm-gov-bz.invalid>`, with `Kind: consolidated`. The address cannot exist. The author is the publisher of the consolidation, not a lawmaker, and no line of a Chapter is credited to an amending law, because without the earlier text nobody can tell which words an amendment wrote. The subsidiary instruments of the Revised Edition are authored the same way. Each Act commit is authored by the Act itself (`act-2026-5@agm-gov-bz.invalid`), `Kind: enacted`: it adds that Act's own text, which it did write. Each statutory instrument commit is authored by the instrument (`si-2026-1@agm-gov-bz.invalid`), `Kind: enacted`, for the same reason.

The margins cite {{MARGIN_CITES}} laws ({{MARGIN_CITES_CHAPTERS}} beside the Chapters), and the Acts' long titles name Chapters {{NAMES_ROWS}} times.

## What it does not show

- Any text before the Revised Edition 2020. The Ministry publishes none.
- The Chapters and subsidiary laws as amended after 2020. The Acts and statutory instruments that amend them are here as made, not applied.
- Statutory instruments that are scans with no text layer, or that the site does not serve as a PDF (listed in `data/si-not-built.csv`), and statutory instruments before 2020 (not published apart from the Revised Edition).
- The Practice Directions of the Senior Courts (2025) listed with the subsidiary laws: they are not part of the Revised Edition and are not built.
- Commencement clauses, and days on which parts of an Act were brought into force by order.
- Pictures, the arrangement of sections at the head of each PDF (the same headings are in the files), running heads, page numbers and footers.
- Text the PDFs do not carry as readable text. Some schedules, mostly the tables of appropriation and customs Acts, are printed in a font with no usable text mapping, so their text layer is garbage; those lines are left out, not guessed. A few pages are scanned images with no text layer at all, and are left out too. They, a second upload of one Act and the laws with no numbered sections (whose whole text is in `title.md`) are the {{ISSUES}} rows in [`data/issues.csv`](data/issues.csv).

This is a research aid. It is not an official or authoritative text; for anything that matters, read the Ministry's PDF.

## How it is checked

`tools/build/` holds the build as it was run. [`data/source-sha256.tsv`](data/source-sha256.tsv) has the sha256 of every PDF the build read. The build is deterministic: from the same PDFs it gives the same commit hashes. See [`REPRODUCE.md`](REPRODUCE.md). Before it was handed on, the build was checked for these things:
- the letters and digits of every law, read straight from its PDF by a separate extractor, match the files;
- every commit's trailers parse, and every commit is at noon local time;
- there are no merges, no dates that go backwards and no dates after the build date;
- two builds from the same PDFs give the same HEAD.

## How it is built

The build reads the Ministry's own list of laws and one PDF per law, as retrieved. `parse_pdf.py` reads each PDF's text layer with PyMuPDF: it drops the cover, running heads and footers, takes the 8-point margin column as headings and citations, and splits the body at each bold section number. `build.py` writes one commit per law with `git fast-import`. No AI model takes part in building or checking it.

## Licence

Source: Laws of Belize, Attorney General's Ministry, Government of Belize (https://agm.gov.bz/laws). The site states no licence and has no terms page; its footer says "All Rights Reserved". The Copyright Act (Chapter 252) has no exclusion for legislation or other official texts, and it gives the State copyright in works made by or under the direction or control of the Government (s. 25(4)). So there is no stated legal basis for republishing the texts. **This repository is private, and must stay private unless the Attorney General's Ministry gives permission.** The wording was not changed; it was only split into files and lines. Lexifina's own contributions (the tools, the arrangement and the commit messages) are CC0. See [`LICENSE`](LICENSE) and [`SOURCES.md`](SOURCES.md).
