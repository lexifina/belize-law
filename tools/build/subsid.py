"""Split a file of the Subsidiary Laws of Belize, Revised Edition 2020, into its instruments.

Each file (one per Chapter: "CAP 004s Belize Constitution Act") holds every instrument made under that Chapter. Its
cover page lists them: "This edition contains a consolidation of the following laws: Page / 1. BELIZE ADVISORY
COUNCIL (PROCEDURE) RULES 3 / 2. ...". The page numbers are the printed ones (the running head of each page). Each
instrument opens with its Chapter line and title ("CHAPTER 4 / BELIZE ADVISORY COUNCIL (PROCEDURE) RULES"), often
part-way down a page that the instrument before ends on.

spans(pdf) -> (instruments, reason): instruments is a list of {'k', 'title', 'page', 'start': (page, y),
'end': (page, y) or None}, physical page indexes, end exclusive; or None, with the reason, when the file cannot be
split by what it prints (no contents list, numbers that do not run in order, an instrument's opening not found).
"""
import re
from collections import Counter

import pymupdf


def letters(s: str) -> str:
    return re.sub(r'[^0-9A-Z]', '', s.upper())


def front_text(doc) -> str:
    """The cover and contents pages: every page before the first printed page of the laws."""
    out = []
    for page in doc:
        t = page.get_text()
        if 'Printed by Authority' in t:
            break
        out.append(t)
    return '\n'.join(out)


def contents(doc) -> list[dict] | None:
    text = front_text(doc)
    m = re.search(r'following\s+laws?\W*(.*)$', text, re.S | re.I)
    if not m:
        return None
    body = re.sub(r'^\s*Page\s*$', ' ', m.group(1), flags=re.M)
    body = re.sub(r'[ \t]*\n[\s_]*', '\n', body).strip() + '\n'

    def marker(label: str):
        # "1. TITLE", "1.\nTITLE", "10.DEFENCE", "17a. BELIZE CITY ..."
        return re.compile(rf'(?<![\w(.,]){label}\.(?:\s|(?=[A-Z]))')

    items = []
    pos = 0
    n, suffix = 1, ''
    while True:
        a = marker(f'{n}{suffix}').search(body, pos)
        if not a:
            break
        # the next item: "18." or "17b." after "17a.", "17a." after "17."
        nexts = [(n + 1, ''), (n, chr(ord(suffix or '`') + 1))]
        found = [(mm.start(), nn, ss) for nn, ss in nexts for mm in [marker(f'{nn}{ss}').search(body, a.end())] if mm]
        nxt = min(found) if found else None
        seg = body[a.end(): nxt[0] if nxt else len(body)]
        p = re.search(r'(\d{1,4})\W*$', seg) if nxt else None
        if not p:
            # the last item (notes, or the first instrument itself, may follow the list): its page is the first
            # line-end number that is not a year
            p = next((x for x in re.finditer(r'(\d{1,4})[ .]*\n', seg) if int(x.group(1)) < 1800), None)
            nxt = None
        if not p:
            return None
        title = re.sub(r'\.{2,}', ' ', seg[:p.start()])
        items.append({'k': len(items) + 1, 'label': f'{n}{suffix}', 'title': re.sub(r'\s+', ' ', title).strip(' .'),
                      'printed': int(p.group(1))})
        pos = a.end()
        if not nxt:
            break
        n, suffix = nxt[1], nxt[2]
    return items or None


def page_offset(doc) -> int | None:
    """physical index - printed number, from the bare page numbers in the running heads."""
    votes = Counter()
    for i, page in enumerate(doc):
        lines = [l.strip() for l in page.get_text().splitlines() if l.strip()][:8]
        for l in lines:
            if re.fullmatch(r'\d{1,4}', l):
                votes[i - int(l)] += 1
                break
    return votes.most_common(1)[0][0] if votes else None


def opening(page, num_letters: str, title: str, full: bool = False) -> float | None:
    """The y of the line "CHAPTER <n>" that opens the instrument titled `title` on this page, or of the title line
    itself when no Chapter line is printed above it. `full`: only a Chapter line followed by the whole title."""
    lines = []
    for b in page.get_text('dict')['blocks']:
        for ln in b.get('lines', []):
            t = ''.join(s['text'] for s in ln['spans']).strip()
            if t:
                lines.append((round(ln['bbox'][1], 1), ln['bbox'][0], t))
    lines.sort()
    want = letters(title) if full else letters(title)[:24]
    words = {w for w in re.findall(r'[A-Z]{3,}', title.upper())}
    for strict in (True, False):
        for i, (y, _, t) in enumerate(lines):
            if not re.match(r'^CHAPTER\s+' + num_letters + r'\b', t, re.I):
                continue
            nxt = ' '.join(x[2] for x in lines[i + 1:i + 6])
            after = letters(nxt)
            if full:
                if want and after.startswith(want):
                    return y
                continue
            if strict and want and (after.startswith(want) or after.startswith(want[:12])):
                return y
            if not strict and words and re.match(r'ARRANGEMENT|[A-Z(]', lines[i + 1][2] if i + 1 < len(lines) else ''):
                have = set(re.findall(r'[A-Z]{3,}', nxt.upper()))
                if len(words & have) >= 0.7 * len(words):
                    return y
    if full:
        return None
    for i, (y, _, t) in enumerate(lines):
        joined = letters(' '.join(x[2] for x in lines[i:i + 4]))
        if want and joined.startswith(want):
            return y
    return None


def spans(pdf: str, chapter: str) -> tuple[list[dict] | None, str]:
    doc = pymupdf.open(pdf)
    items = contents(doc)
    if not items:
        return None, 'no list of the laws it contains on the cover'
    printed = [i['printed'] for i in items]
    # One misprinted page number (lower than the one before it) is looked for forward from the item before.
    bad = [k for k in range(1, len(items)) if printed[k] < printed[k - 1]]
    if len(bad) > 1:
        return None, 'the page numbers in its list do not run in order'
    for k in bad:
        items[k]['misprinted'] = True
    off = page_offset(doc)
    first = next((i for i, p in enumerate(doc) if 'Printed by Authority' in p.get_text()), None)
    if first is None:
        return None, 'no printed pages of laws'
    num = re.escape(chapter).replace(r'\.', '[.:]')
    out = []
    for it in items:
        prev = out[-1]['start'][0] if out else first
        if off is not None and not it.get('misprinted'):
            base = it['printed'] + off
            pages = [p for p in (base, base + 1, base - 1, base + 2) if p >= prev]
        else:  # no page numbers printed: look forward from the item before
            pages = list(range(prev, min(len(doc), prev + 80)))
        found = None
        # Two titles that open alike ("... INTEGRATED CIRCUITS ACT (COMMENCEMENT) ORDER" and "... INTEGRATED
        # CIRCUITS REGULATIONS"): the first 24 letters would find the other one, so look for the whole title first.
        alike = any(o is not it and letters(o['title'])[:24] == letters(it['title'])[:24] for o in items)
        for full in ((True, False) if alike else (False,)):
            for p in pages:
                if 0 <= p < len(doc):
                    y = opening(doc[p], num, it['title'], full)
                    if y is not None and (not out or (p, y) > out[-1]['start']):
                        found = (p, y)
                        break
            if found:
                break
        if not found and out and it['printed'] == out[-1]['page']:
            # The list's item before this one, on the same page, was a group heading ("DECLARATION ORDERS"), not an
            # instrument: it opens where this one does. Drop it; this item takes its place.
            page = out[-1]['start'][0]
            y = opening(doc[page], num, it['title'])
            if y is not None and abs(y - out[-1]['start'][1]) < 60:
                out.pop()
                found = (page, y)
        if not found and it['k'] == 1:
            found = (first, 0.0)  # the first item starts with the first printed page
        if not found:
            return None, f"the opening of item {it['label']} ({it['title'][:60]}) is not on its listed page"
        out.append({'k': it['k'], 'label': it['label'], 'title': it['title'], 'page': it['printed'], 'start': found})
    for a, b in zip(out, out[1:]):
        if b['start'] <= a['start']:
            return None, f"items {a['k']} and {b['k']} open at the same place"
        a['end'] = b['start']
    out[-1]['end'] = None

    def text(s: tuple, e: tuple | None, first_page_only: bool = False) -> str:
        parts = []
        last = e[0] if e else len(doc) - 1
        for p in range(s[0], (s[0] if first_page_only else last) + 1):
            r = pymupdf.Rect(doc[p].rect)
            if p == s[0]:
                r.y0 = s[1] - 1
            if e and p == e[0]:
                r.y1 = e[1] - 1
            if r.y1 > r.y0:
                parts.append(doc[p].get_text(clip=r))
        return '\n'.join(parts)

    # The same title listed twice in a row, once for the arrangement's page and once for the text's (Chapter 210,
    # items 24 and 25): one instrument, under the first number. Two instruments that only share a title (three
    # "Pensionable Offices (Declaration) Orders") each have their own text and stay apart.
    merged = []
    for it in out:
        prev = merged[-1] if merged else None
        if (prev and letters(it['title']) == letters(prev['title'])
                and 'ARRANGEMENT OF' in text(prev['start'], prev['end'])
                and 'ARRANGEMENT OF' not in text(it['start'], it['end'], True)
                and not re.search(r'^\s*1\.\s*\S', text(prev['start'], prev['end']).split('ARRANGEMENT OF')[0], re.M)):
            prev['also'], prev['end'] = it['label'], it['end']
            continue
        merged.append(it)
    return merged, ''
