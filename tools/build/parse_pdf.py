"""Parse one Laws of Belize PDF (Revised Edition 2020, agm.gov.bz) into units.

Adapted from scripts/malta-law/parse_pdf.py. The Revised Edition PDFs are Word documents typeset alike:
- two cover pages ("REVISED EDITION 2020 / SHOWING THE SUBSTANTIVE LAWS AS AT 31ST DECEMBER, 2020"), dropped;
- a running header at the top of every page ("[CAP. 146   War Material   5"), dropped, and a footer
  ("THE SUBSTANTIVE LAWS OF BELIZE  REVISED EDITION 2020 / Printed by Authority of the Government of Belize"), dropped;
- the body in 11pt, with section numbers in bold at the start of a line ("1." or "5.-(1) Whenever");
- an 8pt margin column on the outer edge holding each section's heading and the laws that made or changed it,
  with no verb: "40 of 1963.", "S.I. 34 of 2010.", "16/1965.", "Ch. 175, R.L., 1958.", "CAP. 269, R.E. 1980-1990.";
- under the chapter title, an 8pt block listing the chapter's derivation and amending laws, and the date of
  commencement in brackets ("[13th December, 1913]");
- an arrangement table (10pt) before the text, skipped;
- centred headings between sections (PART II), and schedules at the end.

Output: {'preamble': [lines], 'title_notes': [citations], 'units': [{'id', 'kind', 'heading': [..], 'lines': [..],
'notes': [{'kind', 'by'}], 'refs': [..]}]}, units in document order.
"""
import re
import sys
from dataclasses import dataclass, field

import pymupdf

NOTE_KINDS = re.compile(r'^(Amended|Added|Substituted|Repealed|Renumbered|Revoked|Replaced|Inserted|Deleted|Corrected|'
                        r'Re-numbered)\s+(?:and\s+\w+\s+)?by\s*:?\s*', re.I)
# "1. The", "5.-(1)", and the forms printed without a space: "1.These", "1.\u2013These"
ARTICLE = re.compile(r'^\s*(\d{1,4}[A-Z]{0,3})\.(?:\s|$|(?=\s*[-\u2013\u2014]\s*(?:\(|[A-Z][a-z]))|(?=[A-Z][a-z]))')
# The laws a margin note cites. Belize notes name the law only; how it changed the section is not stated.
CITE = re.compile(r'(?P<si>S\.\s?I\.\s*(?:No\.\s*)?\d+[A-Z]?\s*[oO0][fF]\s*\d{4})'
                  r'|(?P<gn>G\.?\s?N?\.?\s?\d+/\d{4})'
                  r'|(?P<act>(?:(?:Act|Ord(?:inance)?\.?)\s+(?:No\.\s*)?)?\d+[A-Z]?\.?\s*[oO0][fF]\s*\d{4})'
                  r'|(?P<slash>\b\d+[A-Z]?/\d{4})'
                  r'|(?P<rev>(?:Ch\.|CAP\.|Cap\.)\s*\d+(?:[.:]\d+)?[A-Z]?(?:,\s*R\.\s?L\.,?\s*\d{4})?'
                  r'|R\.\s?E\.\s*\d{4}(?:\s*-\s*\d{4})?|R\.\s?L\.,?\s*\d{4})')
FOOTER = re.compile(r'^\s*(THE (SUBSTANTIVE|SUBSIDIARY) LAWS OF BELIZE(\s+REVISED EDITION 20\d\d)?|REVISED EDITION 20\d\d'
                    r'|Printed by Authority of the|Government of Belize|[\[\]]|\[\s*\])\s*$')
HEADER_HINT = re.compile(r'CAP\.\s*\d|\[\s*No\.\s*\d|No\.\s*\d+\s*\]|^\s*\d{1,4}\s*$')
COVER = re.compile(r'SHOWING THE (SUBSTANTIVE|SUBSIDIARY) LAWS AS AT')
SCHEDULE = re.compile(r'^\s*((?:[A-Z]+\s+){0,2}SCHEDULE(?:\s+[A-Z0-9]{1,4})?|ANNEX(?:\s+[A-Z0-9]{1,4})?|'
                      r'APPENDIX(?:\s+[A-Z0-9]{1,4})?)\s*$')
ENUM = re.compile(r'^\((?:\d{1,3}[A-Z]{0,2}|[a-z]{1,2}|[ivxl]{1,6}|[A-Z]{1,2})\)')
CITE_SPLIT = re.compile(r'\s*;\s*|\s*,\s*(?=(?:L\.N\.|[IVXLC]+\.\d{4}))')
HEADER_Y = 42
GARBLED = re.compile(r'[\x00-\x08\x0b-\x1f]')
GARBLED_AT: dict[str, list] = {}  # (page, y) of each line in a font with no usable text mapping
IMAGES_AT: dict[str, list] = {}   # pages that are scanned images with no text layer


@dataclass
class Line:
    page: int
    y: float
    x: float
    x1: float
    size: float
    bold: bool
    italic: bool
    text: str
    margin: bool = False   # in the margin column
    centred: bool = False  # a centred body row (a heading)
    tx: float = 0.0        # where the words start, relative to the wrap margin, after a lone "(a)" or "57."
    rel: float = 0.0       # x relative to the page's wrap margin


@dataclass
class Unit:
    id: str
    kind: str
    page: int
    y: float
    heading: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    first: object = None  # the printed first row (a Line), number and all, to give back if this is no section
    blocks: list = field(default_factory=list)  # margin blocks: [heading, notes, (page, y)]


LETTER_SPACED = re.compile(r'(?:\b\w ){5,}')


def respace(spans: list[dict]) -> None:
    """Justified lines are sometimes letter-spaced: a space glyph after every letter, flush with its neighbours.
    A real word break is a space glyph with a visible gap beside it; keep only those."""
    chars = [c for s in spans for c in s.get('chars', [])]
    keep: set[int] = set()
    for i, c in enumerate(chars):
        if c['c'] != ' ':
            continue
        before = c['bbox'][0] - chars[i - 1]['bbox'][2] if i > 0 else 0
        after = chars[i + 1]['bbox'][0] - c['bbox'][2] if i + 1 < len(chars) else 0
        if before > 0.5 or after > 0.5 or i == 0 or i + 1 == len(chars):
            keep.add(id(c))
    for s in spans:
        s['text'] = ''.join(c['c'] for c in s.get('chars', []) if c['c'] != ' ' or id(c) in keep)


def read_lines(path: str, pages: range | None = None) -> list[Line]:
    doc = pymupdf.open(path)
    out: list[Line] = []
    GARBLED_AT[path] = []
    IMAGES_AT[path] = []
    for pno, page in enumerate(doc):
        if pages is not None and pno not in pages:
            continue
        before = len(out)
        width = page.rect.width
        blocks = page.get_text('rawdict')['blocks']
        # The running header is the top line band of every page (y=26 on the old small pages, about 98 on A4).
        ys = [ln['bbox'][1] for bl in blocks for ln in bl.get('lines', [])
              if ''.join(c['c'] for s in ln['spans'] for c in s.get('chars', [])).strip()]
        page_text = ''.join(c['c'] for bl in blocks for ln in bl.get('lines', []) for s in ln['spans']
                            for c in s.get('chars', []))
        if COVER.search(page_text):
            continue
        top = min(ys) if ys else 0
        # The running header is the top band, but only when it looks like one (a blank-headed page keeps its text).
        band = [''.join(c['c'] for s in ln['spans'] for c in s.get('chars', [])) for bl in blocks
                for ln in bl.get('lines', []) if ln['bbox'][1] <= top + 6]
        header_y = top + 6 if top < page.rect.height * 0.2 and any(HEADER_HINT.search(t) for t in band) else -1
        if header_y < 0 and top < page.rect.height * 0.2:
            # A running head on two lines, its "[CAP. 256 7" on the second ("Protection of Layout-Designs
            # (Topographies) / of Integrated Circuits [CAP. 256 7"): both lines in running-head type (12pt and up,
            # above the 11pt text and 11.5pt titles), the second within 24pt of the first.
            two = [(ln['bbox'][1], ''.join(c['c'] for s in ln['spans'] for c in s.get('chars', [])),
                    [s['size'] for s in ln['spans'] if ''.join(c['c'] for c in s.get('chars', [])).strip()])
                   for bl in blocks for ln in bl.get('lines', []) if ln['bbox'][1] <= top + 24]
            two = [x for x in two if x[1].strip()]
            if (any(y > top + 6 and HEADER_HINT.search(t) for y, t, _ in two)
                    and all(sz and min(sz) >= 12 for _, _, sz in two)):
                header_y = max(y for y, _, _ in two) + 1
        height = page.rect.height
        for block in blocks:
            for ln in block.get('lines', []):
                for s in ln['spans']:
                    s['text'] = ''.join(c['c'] for c in s.get('chars', []))
                if LETTER_SPACED.search(''.join(s['text'] for s in ln['spans'])):
                    respace(ln['spans'])
                spans = [s for s in ln['spans'] if s['text'].strip()]
                if not spans:
                    continue
                if GARBLED.search(''.join(s['text'] for s in spans)):
                    GARBLED_AT[path].append((pno, ln['bbox'][1]))
                    continue  # a font with no usable text mapping (control codes for spaces): no readable text
                x0, y0, x1 = ln['bbox'][0], ln['bbox'][1], ln['bbox'][2]
                if y0 <= header_y:
                    continue
                # The footer sits about three quarters down the page box (the PDFs keep a large bottom margin): a
                # 9pt line of the footer's words, or the big empty "[ ]" brackets beside it.
                ftext = ''.join(s['text'] for s in spans)
                fsize = max(s['size'] for s in spans)
                if y0 > height * 0.6 and FOOTER.match(ftext) and (fsize < 9.5 or re.fullmatch(r'\s*[\[\]]\s*', ftext)):
                    continue
                size = max(s['size'] for s in spans)
                font = spans[0]['font']
                line = Line(pno, round(y0, 1), round(x0, 1), round(x1, 1), round(size, 1),
                            'Bold' in font or bool(spans[0]['flags'] & 16),
                            'Italic' in font or font.endswith('-It') or bool(spans[0]['flags'] & 2),
                            ''.join(s['text'] for s in ln['spans']))
                # The margin column: small type at the outer edge (far left on even pages, past the body on odd).
                # Belize: all 8pt type is margin or history-block type (headings and citations), never body.
                line.margin = size <= 8.6
                out.append(line)
        if len(out) == before and any(bl.get('type') == 1 for bl in blocks):
            IMAGES_AT[path].append(pno)  # a scanned page: an image, no text layer
    # Small type inside the body column is text, not margin: tables and schedules are often set in 8pt (a whole
    # page of tariff headings, an appropriation schedule). The body column of each page parity is the median edge
    # of the body type on pages of that parity; only small type wholly outside it is the margin column.
    # Only text type (9.5-11.4pt) sets the column: running heads and page numbers (12pt and up) sit outside it.
    edges: dict[int, tuple[list[float], list[float]]] = {}
    own: dict[int, tuple[float, float]] = {}
    for pno in sorted({l.page for l in out}):
        body = [l for l in out if l.page == pno and 9.5 <= l.size <= 11.4]
        if len(body) >= 5:
            own[pno] = (min(l.x for l in body), max(l.x1 for l in body))
            e = edges.setdefault(pno % 2, ([], []))
            e[0].append(own[pno][0])
            e[1].append(own[pno][1])
    for l in out:
        if not l.margin:
            continue
        if l.page in own:
            left, right = own[l.page]
        elif (l.page % 2) in edges:
            lefts, rights = edges[l.page % 2]
            left, right = sorted(lefts)[len(lefts) // 2], sorted(rights)[len(rights) // 2]
        else:
            continue
        if not (l.x1 <= left + 4 or l.x >= right - 4):
            l.margin = False
    return out


def merge_rows(lines: list[Line]) -> list[Line]:
    """Join the pieces of one visual line ("57." "(1)" "The Director...") into one row."""
    rows: list[Line] = []
    for ln in sorted(lines, key=lambda l: (l.page, l.y, l.x)):
        if rows and rows[-1].page == ln.page and abs(rows[-1].y - ln.y) <= 2.5:
            prev = rows[-1]
            lone = prev.text.strip()
            if prev.tx == prev.x and (ENUM.fullmatch(lone) or re.fullmatch(r'\d{1,4}[A-Z]{0,3}\.', lone)
                                      or ENUM.fullmatch(lone.split(' ')[-1])):
                prev.tx = ln.x
            prev.text = prev.text.rstrip() + ' ' + ln.text.lstrip()
            prev.x1 = max(prev.x1, ln.x1)
            continue
        rows.append(Line(ln.page, ln.y, ln.x, ln.x1, ln.size, ln.bold, ln.italic, ln.text, tx=ln.x))
    left: dict[int, float] = {}
    right: dict[int, float] = {}
    for r in rows:
        left[r.page] = min(left.get(r.page, 1e9), r.x)
        right[r.page] = max(right.get(r.page, 0.0), r.x1)
    for r in rows:
        # Article 1 is sometimes typeset with a letter: "l. The title of this Code is Criminal Code."
        if r.bold and re.match(r'^\s*[lI]\.\s', r.text):
            r.text = re.sub(r'^(\s*)[lI]\.', r'\g<1>1.', r.text, count=1)
        r.rel = r.x - left[r.page]
        r.tx = r.tx - left[r.page]
        mid = (left[r.page] + right[r.page]) / 2
        # A justified full-width row is also "centred"; a heading is clearly shorter than the column.
        r.centred = (r.rel > 25 and abs((r.x + r.x1) / 2 - mid) < 18
                     and (r.x1 - r.x) < 0.72 * (right[r.page] - left[r.page]))
    # The short last row of a paragraph can sit near the middle by chance ("protection of the law;"): a row flush
    # with the text column of the body row just above it is a wrapped row, not a centred heading.
    for prev, r in zip(rows, rows[1:]):
        if (r.centred and not prev.centred and prev.page == r.page and 0 < r.y - prev.y <= 14.5
                and (abs(r.rel - prev.tx) <= 3 or abs(r.rel - prev.rel) <= 3)):
            r.centred = False
    return rows


def clean(text: str) -> str:
    text = text.replace(' ', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def paragraphs(rows: list[Line]) -> list[str]:
    """Rows of one unit into one line per paragraph. A wrapped row comes back to the paragraph's text column (the
    wrap margin, or where the words of an enumerated item start); a row that starts with an enumerator, sits
    further right, is centred, or follows a gap starts a new paragraph."""
    out: list[str] = []
    prev = None
    first = None  # the first row of the current paragraph
    for r in rows:
        t = clean(r.text)
        if not t:
            continue
        # Where a wrapped row may start: back at the text column of the row before (its words, after a lone
        # enumerator), or, under an enumerated first row typeset as one span ("(a) affirm that ..."), a little to
        # the right of it, where the words after "(a)" start; or flush with the wrap rows before it.
        wraps = prev is not None and (
            abs(r.rel - prev.tx) <= 6 or r.rel <= 6
            or (prev is first and ENUM.match(clean(prev.text)) and 0 < r.rel - prev.rel <= 40)
            or (prev is not first and abs(r.rel - prev.rel) <= 6))
        new = (prev is None or bool(ENUM.match(t)) or r.centred or (prev is not None and prev.centred)
               or not wraps
               or (r.page == prev.page and r.y - prev.y > 14.5))
        if new:
            first = r
        if new or not out:
            out.append(t)
        else:
            last = out[-1]
            out[-1] = last + t if last.endswith('-') and t[:1].islower() else last + ' ' + t
        prev = r
    return out


def note_blocks(margin: list[Line]) -> list[list[Line]]:
    blocks: list[list[Line]] = []
    for ln in sorted(margin, key=lambda l: (l.page, l.y)):
        if blocks and blocks[-1][-1].page == ln.page and ln.y - blocks[-1][-1].y <= 11:
            blocks[-1].append(ln)
        else:
            blocks.append([ln])
    return blocks


def parse_note(block: list[Line]) -> tuple[str, list[dict], list[str]]:
    """A margin block: the heading words, then the laws it cites (one note per citation, kind by the form)."""
    text = clean(' '.join(clean(l.text) for l in block))
    notes: list[dict] = []
    for m in CITE.finditer(text):
        kind = m.lastgroup
        if kind == 'slash' and int(re.match(r'\d+', m.group(0)).group()) >= 1900:
            continue  # a financial year (2021/2022), not a law
        notes.append({'kind': kind, 'by': clean(m.group(0))})
    heading = clean(CITE.sub(' ', text))
    heading = re.sub(r'(?:^|\s)[.,;]+(?=\s|$)', ' ', heading)
    heading = clean(heading)
    if heading and not re.search(r'[A-Za-z]', heading):
        heading = ''
    return heading, notes, []


MOVED = [0]  # margin headings moved to the next section (a count, for the survey)
ORDINAL = {2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 6: 'sixth', 7: 'seventh', 8: 'eighth', 9: 'ninth'}


def resolve_repeats(units: list[Unit]) -> tuple[list[Unit], list[str]]:
    """A section number read twice. Usually one of them is a numbered item inside quoted or listed text (an
    amending Act's "10. "LPG Pricing Methodology", a qualifications list "5. An artiste ..."): the section is the
    one that does not open with a quotation mark, has a margin heading, and is longer; the others go back, number
    and all, into the text of the unit before them. A schedule heading printed again straight after itself (a
    schedule inside a schedule) goes back into it too. Any other repeated schedule heading is a separate printed
    part with the same name: it is named by its order ("schedule-a-second")."""
    def base(u: Unit) -> str:
        return u.id.split('~')[0]

    def score(u: Unit) -> tuple:
        rest = clean(u.first.text)[len(base(u)) + 1:].lstrip(' -–—') if u.first else ''
        quoted = rest[:1] in ('“', '"', '‘', "'")
        return (not quoted, any(b[0] for b in u.blocks), sum(len(l.text) for l in u.lines))

    groups: dict[str, list[int]] = {}
    for i, u in enumerate(units):
        if u.kind == 'article':
            groups.setdefault(base(u), []).append(i)
    false: set[int] = set()
    for idx in groups.values():
        if len(idx) > 1:
            best = max(idx, key=lambda i: (score(units[i]), -i))
            false.update(i for i in idx if i != best)
    for i, u in enumerate(units):
        if u.kind == 'schedule' and i and units[i - 1].kind == 'schedule' and base(units[i - 1]) == base(u):
            false.add(i)
    out: list[Unit] = []
    lead: list[str] = []
    best_of = {i: max(idx, key=lambda j: (score(units[j]), -j)) for idx in groups.values() if len(idx) > 1 for i in idx}
    for i, u in enumerate(units):
        if i in false and not out and u.kind == 'article':
            # A false first section, before any real one: the arrangement of sections printed with bold numbers
            # (subsidiary laws). The arrangement is left out by design; its margin citations go to the section.
            best = units[best_of[i]]
            best.blocks.extend(['', notes, refs] for _, notes, refs in u.blocks)
            # The title printed again after the arrangement ("CHAPTER 101", its name, "(section 3)") came in as
            # the section's headings: it is the title. Part headings stay with the section.
            k = next((j for j, h in enumerate(best.heading) if re.match(r'(PART|Part)\b', h)), len(best.heading))
            lead.extend(best.heading[:k])
            best.heading = best.heading[k:]
            continue
        if i not in false or not out:
            out.append(u)
            continue
        into = out[-1]
        into.lines.extend(Line(u.page, u.y, 0, 0, 10, False, False, h, centred=True) for h in u.heading)
        if u.first is not None and u.kind == 'article':  # a schedule's printed heading is in u.heading
            into.lines.append(u.first)
        skip = 1 if u.kind == 'article' and u.lines and u.first is not None and u.lines[0].y == u.first.y \
            and u.lines[0].page == u.first.page else 0
        into.lines.extend(u.lines[skip:])
        for head, notes, refs in u.blocks:
            if head:
                into.lines.append(Line(u.page, u.y, 0, 0, 8, False, False, head))
            into.blocks.append(['', notes, refs])
    # ids again: unique bases plain, repeated schedule names by their order
    seen: dict[str, int] = {}
    for u in out:
        b = base(u)
        n = seen.get(b, 0) + 1
        seen[b] = n
        u.id = b if n == 1 else (f'{b}-{ORDINAL.get(n, f"{n}th")}' if u.kind == 'schedule' else f'{b}~{n}')
    return out, lead


def parse(path: str, act: bool | str = False, span: tuple | None = None) -> dict:
    """act=True: an Act as enacted (the text starts at the first "1." after BE IT ENACTED, and section numbers need
    not be bold). False: a Chapter of the Revised Edition."""
    mode = 'act' if act is True else (act or 'chapter')  # chapter | act | si | sub
    act = mode in ('act', 'si')
    # span: ((page, y), (page, y) or None), one instrument of a subsidiary-laws file, end exclusive
    pages = range(span[0][0], (span[1][0] + 1) if span[1] else 10 ** 6) if span else None

    def inside(page: int, y: float) -> bool:
        if not span:
            return True
        return (page, y) >= (span[0][0], span[0][1] - 1) and (
            span[1] is None or (page, y) < (span[1][0], span[1][1] - 1))
    lines = [l for l in read_lines(path, pages) if inside(l.page, l.y)]
    unreadable = sum(1 for pg, y in GARBLED_AT[path] if inside(pg, y))
    image_pages = sum(1 for pg in IMAGES_AT[path] if not span or span[0][0] <= pg and (span[1] is None or pg < span[1][0]))
    body = [l for l in lines if not l.margin]
    margin = [l for l in lines if l.margin]
    # A printed rule ("____________", "-------") carries no words: it is not a heading or a paragraph.
    rows = [r for r in merge_rows(body) if not re.fullmatch(r'\s*[_\-–—=.·*]{3,}\s*', r.text)]

    # Front matter ends at the first bold "1." (the arrangement table has no bold numbers).
    def is_article(r: Line) -> bool:
        return r.bold and bool(ARTICLE.match(r.text))
    # Section 1 typeset without its dot ("1 This Act may be cited as") or with the number after the words
    # ("This Act may be cited as the ... Act. 1."): when the first bold section is 2, look just above it.
    fb = next((i for i, r in enumerate(rows) if is_article(r)), None)
    if fb is not None and ARTICLE.match(rows[fb].text).group(1) == '2':
        for i in range(fb - 1, max(fb - 4, -1), -1):
            r = rows[i]
            m1 = re.match(r'^\s*1\s+(?=[A-Z])', r.text)
            m2 = re.match(r'^\s*(.*\bcited as\b.*?)\s+1\.\s*$', r.text)
            if (m1 and r.bold) or m2:
                r.text = '1. ' + (r.text[m1.end():] if m1 and r.bold else m2.group(1))
                r.bold = True
                break
    start = next((i for i, r in enumerate(rows) if is_article(r) and ARTICLE.match(r.text).group(1) == '1'), None)
    first_bold = next((i for i, r in enumerate(rows) if is_article(r)), len(rows))
    # Article 1 is not always bold: take a plain "1." that comes after the arrangement table and before the first
    # bold article.
    arr = next((i for i, r in enumerate(rows) if re.match(r'^\s*ARRANGEMENT', r.text)), -1)
    plain = next((i for i, r in enumerate(rows[:first_bold]) if i > arr and ARTICLE.match(r.text)
                  and ARTICLE.match(r.text).group(1) == '1' and r.rel < 8 and r.size >= 10.5), None)
    if start is None or (plain is not None and plain < start):
        start = plain if plain is not None else (start if start is not None else first_bold)
    # Some arrangements print their numbers in bold (many subsidiary laws), so the "1." found may be the
    # arrangement's. The arrangement ends where the title is printed again ("CHAPTER 44"): start after that.
    if not act and arr >= 0 and start is not None and start > arr:
        again = next((i for i in range(arr + 1, len(rows)) if re.match(r'^\s*CHAPTER\s+\d', rows[i].text)), None)
        if again is not None and start < again:
            after = next((i for i in range(again + 1, len(rows)) if ARTICLE.match(rows[i].text)
                          and ARTICLE.match(rows[i].text).group(1) == '1' and (rows[i].bold or rows[i].rel < 8)), None)
            if after is not None:
                start = after
    # An Act as enacted: the text starts at the first "1." after the enacting words, bold or not.
    enact_mark = r'\bSTATUTORY\s*INSTRUMENT\b' if mode == 'si' else r'\bBE IT ENACTED\b'
    enact = next((i for i, r in enumerate(rows) if re.search(enact_mark, r.text, re.I)), None)
    act_mode = act and enact is not None
    if act_mode:
        start = next((i for i, r in enumerate(rows) if i > enact and ARTICLE.match(r.text)
                      and ARTICLE.match(r.text).group(1) == '1' and r.rel < 30), len(rows))
        # An arrangement printed after the enacting words (some statutory instruments: "STATUTORY INSTRUMENT
        # No. 80 of 2023", then the arrangement, then "REGULATIONS made by ... (Gazetted ...)"): start after the
        # words that open the instrument itself.
        arr2 = next((i for i in range(enact + 1, start) if re.match(r'^\s*ARRANGEMENT', rows[i].text)), None)
        if arr2 is not None:
            opens = next((i for i in range(arr2 + 1, len(rows)) if re.search(
                r'\b(made|MADE)\s+by\b|\(Gazetted|\bBE IT ENACTED\b|\bWHEREAS\b', rows[i].text)), None)
            if opens is not None:
                after = next((i for i in range(opens + 1, len(rows)) if ARTICLE.match(rows[i].text)
                              and ARTICLE.match(rows[i].text).group(1) == '1' and rows[i].rel < 30), None)
                if after is not None:
                    start = after
    pre: list[Line] = []
    before_arrangement: list[Line] = []
    skipping = False
    for r in rows[:start]:
        if re.match(r'^\s*ARRANGEMENT', r.text):
            skipping = True
            before_arrangement = pre
            pre = []  # the title is printed again after the arrangement table
            continue
        if skipping and re.match(r'^\s*(CHAPTER\s+\d|AN ACT\b|No\.\s*\d+\s+of\s+\d{4}|BELIZE\s*:|STATUTORY\s+INSTRUMENT'
                                 r'|[A-Z]+\s+(?:made|MADE)\s+by\b|\(Gazetted)', r.text):
            skipping = False
        if not skipping:
            pre.append(r)
    restored = skipping and not pre
    if restored:
        pre = before_arrangement  # the title is not printed again: keep it as printed above the arrangement
    # A Chapter's derivation block under its title (8pt, in the body column: "Ch. 175, R.L., 1958. 40 of 1963.")
    # is read like a margin note, so its citations go to title_notes.
    if not act:
        margin = margin + [r for r in pre if r.size <= 8.6]
        pre = [r for r in pre if r.size > 8.6]
        # The derivation block is sometimes set in body type (Cap. 1: "CAP.1.  [4th September, 1981]", then
        # "R.E. 1980-1990.", "18 of 1980." ...), its first citation on the row of the commencement date. A row that
        # is only citations, once the bracketed date is taken out, is derivation, not title.
        kept = []
        for r in pre:
            t = clean(r.text)
            date = re.search(r'\[[^\]]*\b\d{4}\s*\]', t)
            rest = clean(t[:date.start()] + ' ' + t[date.end():]) if date else t
            head, notes, _ = parse_note([Line(r.page, r.y, r.x, r.x1, r.size, False, False, rest)]) if rest else ('', [], [])
            if notes and not head:
                margin.append(Line(r.page, r.y, r.x, r.x1, 8.0, False, False, rest, margin=True))
                if not date:
                    continue
                r = Line(r.page, r.y, r.x, r.x1, r.size, r.bold, r.italic, date.group(0), centred=r.centred,
                         tx=r.tx, rel=r.rel)
            kept.append(r)
        pre = kept
    # Headings just before section 1 (PART I, Preliminary) belong to section 1, not the title.
    lead: list[str] = []
    while pre and not restored and pre[-1].centred and not re.match(r'^\s*\[', pre[-1].text) and len(pre) > 1:
        lead.insert(0, clean(pre.pop().text))

    units: list[Unit] = []
    pending: list[str] = lead
    seen: dict[str, int] = {}
    in_schedule = False
    last_num = 0
    for k, r in enumerate(rows[start:]):
        m = ARTICLE.match(r.text) if (r.bold or k == 0 or (act_mode and r.rel < 8)) and not in_schedule else None
        if m and units and int(re.match(r'\d+', m.group(1)).group()) < last_num:
            m = None  # numbering that runs backwards is a numbered list inside the text (a schedule, a form)
        if m and act_mode and units and int(re.match(r'\d+', m.group(1)).group()) > last_num + 2:
            m = None  # an Act's sections run in order; a bigger jump is a number inside the text
        if m:
            last_num = int(re.match(r'\d+', m.group(1)).group())
        s = SCHEDULE.match(clean(r.text)) if not m else None
        if s and not in_schedule and units and not r.centred and r.rel < 25:
            s = None  # "SCHEDULE" at the left margin inside an article's text is not a heading
        if m or s:
            in_schedule = in_schedule or bool(s)
            uid = m.group(1) if m else re.sub(r'\s+', '-', s.group(1).strip().lower())
            n = seen.get(uid, 0)
            seen[uid] = n + 1
            u = Unit(uid if n == 0 else f'{uid}~{n + 1}', 'article' if m else 'schedule', r.page, r.y, heading=pending,
                     first=r)
            pending = []
            if m:
                rest = re.sub(r'^\s*[-–—]\s*(?=\(|[A-Z][a-z])', '', r.text[m.end():])
                if rest.strip():
                    u.lines.append(Line(r.page, r.y, r.x, r.x1, r.size, False, r.italic, rest, tx=r.tx, rel=r.tx))
            else:
                u.heading.append(clean(r.text))
            units.append(u)
            continue
        if not units:
            pending.append(clean(r.text))
            continue
        cur = units[-1]
        # Centred headings between articles (BOOK FIRST, Title IV, PART II) belong to the next article.
        # But a centred row straight after a row that does not finish its sentence ("may be cited as the" /
        # "INTOXICATING LIQUOR LICENSING" / "ORDER, 2026.") goes on with that text.
        last = cur.lines[-1] if cur.lines and not pending else None
        goes_on = (last is not None and last.page == r.page and 0 < r.y - last.y <= 14.5
                   and not re.search(r'[.:;,–—)\]]\s*$', clean(last.text)))
        if (cur.kind == 'article' and r.centred and len(r.text.strip()) < 120 and not ENUM.match(r.text.strip())
                and not goes_on):
            pending.append(clean(r.text))
            continue
        if pending and cur.kind == 'article' and r.rel > 25 and (r.centred or r.text.strip().isupper()):
            pending.append(clean(r.text))
            continue
        if pending:
            # Not a heading after all (a centred line inside the article): give it back to the article.
            cur.lines.extend(Line(r.page, r.y, r.x, r.x1, r.size, False, False, h, centred=True) for h in pending)
            pending = []
        cur.lines.append(r)
    if pending and units:
        units[-1].lines.extend(Line(0, 0, 0, 0, 10, False, False, h, centred=True) for h in pending)

    # Margin notes belong to the unit that starts nearest at or above them; at the top of a page, to the unit
    # carried over from the page before.
    starts = [(u.page, u.y, i) for i, u in enumerate(units)]

    def target_of(ln: Line) -> int | None:
        t = None
        for page, y, i in starts:
            if (page, y) <= (ln.page, ln.y + 6):
                t = i
            else:
                break
        return t

    # Two short sections in one band: their headings run together into one block. Split it where a heading ends
    # ("Disposal of forfeits.") and the next heading line ("Repeal or") sits beside the next section.
    pieces: list[list[Line]] = []
    for block in note_blocks(margin):
        cur = [block[0]]
        for prev, ln in zip(block, block[1:]):
            t = clean(ln.text)
            if (target_of(ln) != target_of(cur[0]) and clean(prev.text).endswith('.')
                    and re.match(r'[A-Z][a-z]', t) and not CITE.match(t)):
                pieces.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        pieces.append(cur)
    title_notes: list[dict] = []
    title_heads: list[str] = []
    for piece in pieces:
        target = target_of(piece[0])
        head, notes, refs = parse_note(piece)
        if target is None:
            title_notes.extend(notes)
            if head:
                title_heads.append(head)
            continue
        units[target].blocks.append([head, notes, refs])

    units, lead2 = resolve_repeats(units)
    pre = pre + [Line(0, 0, 0, 0, 10, False, False, h, centred=True) for h in lead2]

    # A section's heading set at the foot of the page before it (the section starts at the top of the next page)
    # reads as a second heading of the section above. When a section has two margin headings and the next has
    # none, the second one is the next section's.
    for u, nx in zip(units, units[1:]):
        heads = [k for k, b in enumerate(u.blocks) if b[0]]
        if u.kind == nx.kind == 'article' and len(heads) >= 2 and not any(b[0] for b in nx.blocks):
            nx.blocks[:0] = u.blocks[heads[-1]:]
            del u.blocks[heads[-1]:]
            MOVED[0] += 1
    for u in units:
        for head, notes, refs in u.blocks:
            if head and head not in u.heading:
                u.heading.append(head)
            u.notes.extend(notes)
            u.refs.extend(refs)

    return {
        'preamble': paragraphs(pre),
        'title_notes': title_notes,
        'title_heads': title_heads,
        'units': [{'id': u.id, 'kind': u.kind, 'heading': u.heading, 'lines': paragraphs(u.lines), 'notes': u.notes,
                   'refs': u.refs} for u in units],
        'unreadable_lines': unreadable,
        'image_pages': image_pages,
    }


if __name__ == '__main__':
    import json
    d = parse(sys.argv[1])
    print(json.dumps(d, ensure_ascii=False, indent=1)[:int(sys.argv[2]) if len(sys.argv) > 2 else None])
