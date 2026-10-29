"""Independent letters-and-digits check: each law's PDF against what git holds for it.

    python scripts/belize-law/check_words.py ~/Documents/belize-law-build

The source side reads each PDF with PyMuPDF's plain `page.get_text()` and nothing from parse_pdf.py. It removes,
by its own simple rules, only what the build leaves out by design: the two cover pages (the page that says "SHOWING
THE SUBSTANTIVE LAWS AS AT"), and the printed boilerplate lines (the footer "THE SUBSTANTIVE LAWS OF BELIZE /
REVISED EDITION 2020 / Printed by Authority of the / Government of Belize", and the running head "[CAP. 101",
"Criminal Code", page number in the first lines of a page), and the arrangement of sections (from "ARRANGEMENT OF"
to where the CHAPTER line or the Act's number above it is printed again). Lines in a font with no usable text
mapping (control codes in the text) are left out of the source side, as the build leaves them out; they are counted
and listed. The git side is every file of that law at main, minus the repository's own markup
("- Margin notes:", "- Margin:", "#", the section number written again in each heading). Both are reduced to a
multiset of letters and digits (casefolded), so order does not matter.

"missing" = in the PDF, not in git (dropped text; the arrangement table at the head of each PDF is in here, since its
headings appear once more in the files only as margin headings). "extra" = in git, not in the PDF (text the build
invented or duplicated). A law is flagged when extra > 0.5% or missing > 15% of its letters.
"""
import csv
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from source_files import pdf_path  # noqa: E402  (where each retrieved PDF is)

BOILER = re.compile(r'^\s*(THE (SUBSTANTIVE|SUBSIDIARY) LAWS OF BELIZE|REVISED EDITION 20\d\d|Printed by Authority of the'
                    r'|Government of Belize|\[?\s*CAP\.\s*[\d.:]+\s*\]?|\[\s*No\.\s*\d+|No\.\s*\d+\s*\]|\d{1,4}|[\[\]\s]*)\s*$')


GARBLED: Counter = Counter()  # lines of each PDF with no readable text mapping


def letters(s: str) -> Counter:
    return Counter(c for c in s.casefold() if c.isalnum())


def source(pdf: str, running_title: str, span: str = '') -> Counter:
    """span: "p0:y0-p1:y1" or "p0:y0-end" (laws.csv), one instrument of a subsidiary-laws file: only the text from
    (p0, y0) to (p1, y1), cut with get_text(clip=...)."""
    out = Counter()
    pages = []
    lo = hi = None
    if span:
        a, b = span.split('-', 1)
        lo = (int(a.split(':')[0]), float(a.split(':')[1]))
        hi = None if b == 'end' else (int(b.split(':')[0]), float(b.split(':')[1]))
    for pno, page in enumerate(pymupdf.open(pdf)):
        if lo and (pno < lo[0] or (hi and pno > hi[0])):
            continue
        r = pymupdf.Rect(page.rect)
        if lo and pno == lo[0]:
            r.y0 = lo[1] - 1
        if hi and pno == hi[0]:
            r.y1 = hi[1] - 1
        if r.y1 <= r.y0:
            continue
        text = page.get_text(clip=r) if lo else page.get_text()
        if 'SHOWING THE SUBSTANTIVE LAWS AS AT' in text or 'SHOWING THE SUBSIDIARY LAWS AS AT' in text:
            continue
        pages.append(text.splitlines())
    # The arrangement of sections, which the repository leaves out by design: from "ARRANGEMENT OF" to where the
    # title printed just above it (the CHAPTER line, or an Act's "No. 5 of 2026") is printed again. If that line
    # never comes back, nothing is skipped.
    flat = [(p, i, l.strip()) for p, ls in enumerate(pages) for i, l in enumerate(ls)]
    skip: set[tuple[int, int]] = set()
    a = next((k for k, (_, _, l) in enumerate(flat) if re.match(r'ARRANGEMENT OF', l)), None)
    if a is not None:
        marks = {re.sub(r"[^0-9A-Za-z]", "", l) for _, _, l in flat[:a] if re.match(r'(CHAPTER\s+\d|No\.\s*\d+\s+of\s+\d{4}$)', l)}
        end = next((k for k in range(a + 1, len(flat)) if re.sub(r"[^0-9A-Za-z]", "", flat[k][2]) in marks
                    or re.match(r'(No\.\s*\d+\s+of\s+\d{4}$|AN ACT\b)', flat[k][2])), None)
        if end is not None:
            skip = {(p, i) for p, i, _ in flat[a:end]}
    for pno, lines in enumerate(pages):
        for i, line in enumerate(lines):
            if (pno, i) in skip:
                continue
            if re.search(r'[\x00-\x08\x0b-\x1f]', line):
                GARBLED[pdf] += 1
                continue  # a font with no usable text mapping ("6&+('8/(" for SCHEDULE): no readable text
            if BOILER.match(line) and not re.fullmatch(r'\s*\d{1,4}\s*', line):
                continue
            if re.fullmatch(r'\s*\d{1,4}\s*', line) and i < 6:
                continue  # the page number in the running head (a bare number lower down is a table cell)
            if i < 6 and running_title and line.strip() == running_title:
                continue  # the running head's title words
            out += letters(line)
    return out


def ours(text: str) -> Counter:
    keep = []
    for line in text.splitlines():
        line = re.sub(r'^- Margin notes: ', '', line)
        line = re.sub(r'^- Margin: ', '', line)
        line = re.sub(r'^#+ ', '', line)
        keep.append(line)
    return letters('\n'.join(keep))


def main() -> None:
    repo = Path(sys.argv[1])

    def git(*a: str) -> str:
        return subprocess.run(['git', '-c', 'core.quotepath=false', '-C', str(repo), *a], capture_output=True,
                              text=True, encoding='utf-8', check=True).stdout

    cat = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def blob(spec: str) -> str:
        cat.stdin.write(spec.encode('utf-8') + b'\n')
        cat.stdin.flush()
        header = cat.stdout.readline().split()
        if header[1] == b'missing':
            return ''
        data = cat.stdout.read(int(header[2]))
        cat.stdout.read(1)
        return data.decode('utf-8')

    tree: dict[str, list[str]] = {}
    for p in git('ls-tree', '-r', '--name-only', 'main').splitlines():
        if p.startswith(('cap/', 'acts/', 'sub/', 'si/')) and not p.endswith('index.txt'):
            tree.setdefault(p.rsplit('/', 1)[0], []).append(p)
    rows = list(csv.DictReader(open(repo / 'laws.csv', encoding='utf-8')))
    results = []
    tot_src = tot_miss = tot_extra = 0
    for row in rows:
        d = row['path'].rstrip('/')
        url = row['source_url'].replace('https://agm.gov.bz', '')
        pdf = pdf_path({'url': url})
        g = Counter()
        for p in tree.get(d, []):
            text = blob(f'main:{p}')
            if re.search(r'/[0-9]+[A-Z]*(~\d+)?\.md$', p):
                # the section number the heading repeats ("# 12. Interpretation." for the printed "12.")
                pass
            g += ours(text)
        s = source(pdf, '', row.get('span', ''))
        miss = sum((s - g).values())
        extra = sum((g - s).values())
        total = sum(s.values()) or 1
        tot_src += total
        tot_miss += miss
        tot_extra += extra
        results.append((extra / total, miss / total, d, miss, extra, total, (g - s).most_common(5)))
    cat.stdin.close()
    bad = [r for r in results if r[0] > 0.005 or r[1] > 0.15]
    print(f'checked {len(results)} laws, {tot_src} source letters and digits: {tot_miss} missing '
          f'({100 * tot_miss / max(1, tot_src):.3f}%), {tot_extra} extra ({100 * tot_extra / max(1, tot_src):.3f}%); '
          f'{len(bad)} laws flagged')
    for r in sorted(bad, reverse=True)[:30]:
        print(f'  {r[2]}: missing {r[3]}/{r[5]} ({100 * r[1]:.1f}%), extra {r[4]} ({100 * r[0]:.2f}%) {r[6]}')
    worst_missing = sorted(results, key=lambda r: -r[1])[:10]
    print('most missing:', ', '.join(f'{r[2]} {100 * r[1]:.1f}%' for r in worst_missing))
    print(f'PDFs with unreadable (garbled-font) lines, left out of both sides: {len(GARBLED)}: '
          + ', '.join(f'{Path(p).name[:40]} ({n})' for p, n in sorted(GARBLED.items())))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
