"""Build the Belize law repository from the retrieved agm.gov.bz PDFs (source_files.py says where they are).

    python scripts/belize-law/build.py ~/Documents/belize-law-build --today YYYY-MM-DD [--limit N]
        [--no-parse-cache]

The Attorney General's Ministry publishes the Laws of Belize as PDFs: the Revised Edition 2020 ("showing the
substantive laws as at 31st December, 2020"), one PDF per Chapter, and the Acts passed since, one PDF per Act as
enacted. It keeps no earlier consolidations. So the history here has two parts:

1. Every Chapter of the Revised Edition 2020 is one commit, `Kind: consolidated`, by the publisher, dated noon
   Belize time (UTC-6, no summer time) on 2020-12-31, the edition's as-at date. Each section (and each schedule)
   is one file, one paragraph per line, with its margin heading as the `#` line and the laws its margin cites as a
   last line ("- Margin notes: 40 of 1963; S.I. 34 of 2010."). Those citations are listed in data/amendments.csv.
   No line is credited to an amending law: the text before each amendment is not published.
2. Every Act of 2021-2026 is one commit as enacted, authored by that Act, dated noon on the day the Act says it was
   gazetted (`In-force-basis: gazetted`), in its own folder acts/<year>/<number>/. Its amendments are not applied
   to the Chapters (no consolidation after 2020 is published to check them against); the Chapters an Act names
   in its long title are listed in `Amends:` trailers and data/amendments.csv.

The whole history is written in one sorted git fast-import, so the same cache gives the same hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
CACHE = HERE / '.cache'
PARSED = CACHE / 'parsed'

from source_files import BASE, pdf_path  # noqa: E402
import parse_pdf  # noqa: E402
import subsid  # noqa: E402
import ocrdates  # noqa: E402
import titles  # noqa: E402

COMMITTER = 'Lexifina <belize-law@lexifina.com>'
PUBLISHER = ("Laws of Belize (Attorney General's Ministry)", 'laws-of-belize@agm-gov-bz.invalid')
EDITION_DAY = '2020-12-31'
CHECKOUT = (Path.home() / 'Documents' / 'belize-law').resolve()  # never build into the pushed checkout
MONTHS = {m: i for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
                                      'september', 'october', 'november', 'december'], 1)}
CAP_NAME = re.compile(r'^\s*Cap(?:ter)?\.?\s*(\d+)(?:\s*[.:]\s*(\d+))?([A-Z])?\b\.?\s*(.*)$', re.I)
ACT_NAME = re.compile(r'^\s*Act\s+No\.?\s*0*(\d+)\s+(?:of\s+)?(\d{4})\s*(.*)$', re.I)
GAZETTED = re.compile(r'Gazetted\s*:?\s*([^()]{6,30}?\d{4})', re.I)
_MON = r'(January|February|March|April|May|June|July|August|September|October|November|December)'
DAY = re.compile(r'\s*(?:(\d{1,2})\s*(?:st|nd|rd|th)?\s+' + _MON + r'\s*,?\s*(\d{4})'
                 r'|' + _MON + r'\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s*,?\s*(\d{4}))', re.I)
ASSENT = re.compile(r'Governor[\s-]*General\s*,?\s*([^()]{6,30}?\d{4})', re.I)
CITED_AS = re.compile(r'cited as\s+(?:the\s+)?(.+?\bACT\b,?\s*\d{4})', re.I | re.S)
AMENDS = re.compile(r'\bCHAPTER\s+(\d+)(?:\s*[.:]\s*(\d+))?([A-Z])?\b', re.I)


# ---------------------------------------------------------------------------------------------------- catalogue

def cap_number(m: re.Match) -> str:
    return str(int(m.group(1))) + (f'.{m.group(2)}' if m.group(2) else '') + (m.group(3) or '').upper()


def cap_key(num: str) -> tuple:
    m = re.match(r'(\d+)(?:\.(\d+))?([A-Z]?)$', num)
    return int(m.group(1)), int(m.group(2) or 0), m.group(3)


def load_catalogue(limit: int | None) -> tuple[list[dict], list[dict], list[dict]]:
    """(chapters, acts, issues) from .cache/catalogue.json, with the PDF each one reads."""
    rows = json.loads((CACHE / 'catalogue.json').read_text('utf-8'))['rows']
    chapters, acts, issues = [], [], []
    seen_cap: dict[str, dict] = {}
    for r in rows:
        if r['category'] != 'substantive':
            continue
        m = CAP_NAME.match(r['name'])
        num = cap_number(m)
        law = {'kind': 'chapter', 'num': num, 'title': re.sub(r'\s+', ' ', m.group(4)).strip(), 'row': r,
               'dir': f'cap/{num}', 'pdf': pdf_path(r)}
        if num in seen_cap:
            issues.append({'law': r['name'], 'issue': f'second PDF listed for Chapter {num}; not built'})
            continue
        seen_cap[num] = law
        chapters.append(law)
    by_act: dict[tuple, list[dict]] = {}
    for r in rows:
        if r['category'] != 'act':
            continue
        m = ACT_NAME.match(r['name'])
        if not m:
            issues.append({'law': r['name'], 'issue': 'Act number not in its listed name; not built'})
            continue
        by_act.setdefault((int(m.group(2)), int(m.group(1))), []).append(r)
    for (year, no), rs in sorted(by_act.items()):
        rs = sorted(rs, key=lambda r: r['url'])
        r = rs[-1]  # two uploads of one Act: the later upload (the upload id leads the file name and grows)
        for other in rs[:-1]:
            same = Path(pdf_path(other)).read_bytes() == Path(pdf_path(r)).read_bytes() if (
                os.path.exists(pdf_path(other)) and os.path.exists(pdf_path(r))) else False
            issues.append({'law': other['name'], 'issue': f"a second upload of Act No. {no} of {year} "
                           f"({'identical file' if same else 'a different file'}); the later upload is built"})
        title = re.sub(r'\s+', ' ', ACT_NAME.match(r['name']).group(3)).strip()
        acts.append({'kind': 'act', 'year': year, 'no': no, 'title': title, 'row': r, 'dir': f'acts/{year}/{no}',
                     'pdf': pdf_path(r)})
    chapters.sort(key=lambda l: cap_key(l['num']))
    for law in chapters + acts:
        if not os.path.exists(law['pdf']):
            issues.append({'law': law['row']['name'], 'issue': 'PDF not fetched (the site answered with a page, not a PDF)'})
    chapters = [l for l in chapters if os.path.exists(l['pdf'])]
    acts = [l for l in acts if os.path.exists(l['pdf'])]
    if limit:
        chapters, acts = chapters[:limit], acts[:limit]
    return chapters, acts, issues


def latest_upload(rs: list[dict], what: str, issues: list[dict]) -> dict:
    """Two uploads of one law: the later upload (the upload id leads the file name and grows)."""
    rs = sorted(rs, key=lambda r: r['url'].rsplit('/', 1)[1])
    r = rs[-1]
    for other in rs[:-1]:
        a, b = pdf_path(other), pdf_path(r)
        same = os.path.exists(a) and os.path.exists(b) and Path(a).read_bytes() == Path(b).read_bytes()
        issues.append({'law': other['name'], 'issue': f"a second upload of {what} "
                       f"({'identical file' if same else 'a different file'}); the later upload is built"})
    return r


SUB_NAME = re.compile(r'^\s*Cap\.?\s*(\d+)(?:\.(\d+))?\s*s?\b', re.I)
SI_NAME = re.compile(r'^\s*SI\s*No\.?\s*0*(\d+)\s*(?:of\s*)?(\d{4})\s*(.*)$', re.I)
SI_PRINTED = re.compile(r'STATUTORY\s*INSTRUMENT\s*No\.?\s*0*(\d+)\s*of\s*(\d{4})', re.I)
SUBSID_SHA = hashlib.sha256((HERE / 'subsid.py').read_bytes()).hexdigest()[:16]


def instrument_spans(pdf: str, num: str) -> tuple[list[dict] | None, str]:
    """subsid.spans(pdf), cached by the PDF's sha256 and subsid.py's."""
    key = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()[:24] + f'-{num}-' + SUBSID_SHA
    p = CACHE / 'spans' / f'{key}.json'
    if p.exists():
        d = json.loads(p.read_text('utf-8'))
    else:
        s, why = subsid.spans(pdf, num)
        d = {'spans': s, 'why': why}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding='utf-8', newline='\n')
    spans = d['spans']
    for s in spans or []:
        s['start'] = tuple(s['start'])
        s['end'] = tuple(s['end']) if s['end'] else None
    return spans, d['why']


def load_subsidiary(issues: list[dict], limit: int | None) -> list[dict]:
    """The instruments of the Subsidiary Laws, Revised Edition 2020: one law per instrument where the file's own
    list of contents marks where each starts, else the whole file as one law (sub/<chapter>/all)."""
    rows = json.loads((CACHE / 'catalogue.json').read_text('utf-8'))['rows']
    by_cap: dict[str, list[dict]] = {}
    listed_nums: list[tuple[str, dict]] = []
    for r in rows:
        if r['category'] != 'subsidiary':
            continue
        if r['name'].lower().startswith('practice direction'):
            issues.append({'law': r['name'], 'issue': 'a Practice Direction of the Senior Courts (2025), listed with the '
                           'subsidiary laws but not part of the Revised Edition 2020; not built'})
            continue
        m = SUB_NAME.match(r['name'])
        if not m:
            issues.append({'law': r['name'], 'issue': 'Chapter number not in its listed name; not built'})
            continue
        num = str(int(m.group(1))) + (f'.{m.group(2)}' if m.group(2) else '')
        if not os.path.exists(pdf_path(r)):
            issues.append({'law': r['name'], 'issue': 'PDF not fetched (the site answered with a page, not a PDF)'})
            continue
        listed_nums.append((num, r))
    listed = {n for n, _ in listed_nums}
    import pymupdf
    for num, r in listed_nums:
        # The cover prints the Chapter ("CHAPTER 54"). Where it names another Chapter that is not listed itself
        # ("CAP 097s Fiscal Incentives Act" holds the instruments under Chapter 54), the cover is followed.
        c = re.search(r'CHAPTER\s+(\d+)(?:\s*[:.]\s*(\d+))?', pymupdf.open(pdf_path(r))[0].get_text())
        cover = str(int(c.group(1))) + (f'.{c.group(2)}' if c.group(2) else '') if c else num
        if cover != num and cover not in listed:
            issues.append({'law': r['name'], 'issue': f'listed as Chapter {num}, but its cover and pages print Chapter '
                           f'{cover}; built as sub/{cover}'})
            num = cover
        by_cap.setdefault(num, []).append(r)
    out = []
    for num in sorted(by_cap, key=cap_key)[:limit] if limit else sorted(by_cap, key=cap_key):
        r = latest_upload(by_cap[num], f'the subsidiary laws of Chapter {num}', issues)
        pdf = pdf_path(r)
        spans, why = instrument_spans(pdf, num)
        cover = re.sub(r'\s+', ' ', r['name'][m.end():] if (m := SUB_NAME.match(r['name'])) else r['name']).strip()
        if not spans:
            issues.append({'law': r['name'], 'issue': f'not split into its instruments ({why}); built whole as '
                           f'sub/{num}/all'})
            out.append({'kind': 'subsidiary', 'num': num, 'label': 'all', 'whole': True, 'row': r, 'pdf': pdf,
                        'title': f'Subsidiary laws under {cover}, the whole file', 'span': None,
                        'dir': f'sub/{num}/all', 'count': 1})
            continue
        for s in spans:
            out.append({'kind': 'subsidiary', 'num': num, 'label': s['label'], 'whole': False, 'row': r, 'pdf': pdf,
                        'title': s['title'], 'span': [s['start'], s['end']], 'page': s['page'], 'also': s.get('also'),
                        'dir': f"sub/{num}/{s['label']}", 'count': len(spans)})
    return out


def load_sis(issues: list[dict], limit: int | None) -> list[dict]:
    rows = json.loads((CACHE / 'catalogue.json').read_text('utf-8'))['rows']
    by_si: dict[tuple, list[dict]] = {}
    unnamed = []
    si_rows = [r for r in rows if r['category'] == 'si']
    named = {(r['list'][:4], int(m.group(2)), int(m.group(1)))
             for r in si_rows for m in [SI_NAME.match(r['name'])] if m}
    for r in si_rows:
        m = SI_NAME.match(r['name'])
        if not m:
            unnamed.append(r)
            continue
        year, no = int(m.group(2)), int(m.group(1))
        listed = int(r['list'][:4])
        if year != listed and (r['list'][:4], listed, no) not in named:
            # "SI No. 006 of 2024" in the 2025 list, gazetted in January 2025, and no No. 6 of 2025 listed: the
            # name (and sometimes the heading) carries the year before; the list's year is the instrument's.
            issues.append({'law': r['name'], 'issue': f'listed among the S.I.s of {listed} with the year {year} in its '
                           f'name, and no other No. {no} of {listed} is listed; built as No. {no} of {listed}'})
            year = listed
        by_si.setdefault((year, no), []).append(r)
    # A listed name with no S.I. number: take the number the PDF prints under "STATUTORY INSTRUMENT", unless
    # another listing already has that number (then it is a part published on its own, such as a schedule).
    import pymupdf
    for r in unnamed:
        p = pdf_path(r)
        m = SI_PRINTED.search(' '.join(pg.get_text() for pg in pymupdf.open(p))) if os.path.exists(p) else None
        if not m:
            issues.append({'law': r['name'], 'issue': 'no S.I. number in its listed name or printed in it; not built',
                           'si': 'unnumbered'})
        elif (int(m.group(2)), int(m.group(1))) in by_si:
            issues.append({'law': r['name'], 'issue': f'prints S.I. No. {m.group(1)} of {m.group(2)}, which is listed '
                           'on its own; not built separately', 'si': 'part'})
        else:
            by_si[(int(m.group(2)), int(m.group(1)))] = [dict(r, printed_number=True)]
    out = []
    for (year, no), rs in sorted(by_si.items()):
        have = [r for r in rs if os.path.exists(pdf_path(r))]
        for r in rs:
            if not os.path.exists(pdf_path(r)):
                issues.append({'law': r['name'], 'issue': 'PDF not fetched (the site answered with a page, not a PDF)',
                               'si': 'page'})
        if not have:
            continue
        r = latest_upload(have, f'S.I. No. {no} of {year}', issues)
        m = SI_NAME.match(r['name'])
        title = re.sub(r'\s+', ' ', m.group(3) if m else r['name']).strip()
        out.append({'kind': 'si', 'year': year, 'no': no, 'title': title, 'row': r, 'dir': f'si/{year}/{no}',
                    'pdf': pdf_path(r)})
    return out[:limit] if limit else out


# ---------------------------------------------------------------------------------------------------- parse

PARSER_SHA = hashlib.sha256((HERE / 'parse_pdf.py').read_bytes()).hexdigest()[:16]


def parse_cached(pdf: str, mode: str, use_cache: bool = True, span: list | None = None) -> dict:
    """parse_pdf.parse(pdf, mode, span), cached under .cache/parsed by the PDF's sha256, the mode, the span and the
    parser's sha256."""
    data = Path(pdf).read_bytes()
    where = '' if not span else '.' + hashlib.sha256(json.dumps(span).encode()).hexdigest()[:10]
    key = hashlib.sha256(data).hexdigest()[:24] + {'chapter': '-', 'act': '.act-'}.get(mode, f'.{mode}{where}-') + PARSER_SHA
    p = PARSED / f'{key}.json'
    if use_cache and p.exists():
        return json.loads(p.read_text('utf-8'))
    d = parse_pdf.parse(pdf, mode, tuple(span) if span else None)
    PARSED.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.part')
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding='utf-8', newline='\n')
    os.replace(tmp, p)
    return d


# ---------------------------------------------------------------------------------------------------- files

def norm(s: str) -> str:
    """Whitespace and soft hyphens only; the wording, quotes and dashes are kept as printed."""
    s = s.replace('\xad', '').replace('\u200b', '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def safe(uid: str) -> str:
    return re.sub(r'[^0-9A-Za-z.~-]', '-', uid)


def unit_text(u: dict) -> str:
    out = []
    head = [norm(h) for h in u['heading'] if norm(h)]
    if u['kind'] == 'article':
        title = head[-1] if head else ''
        out += [f'## {h}' for h in head[:-1]]
        out.append(f"# {u['id'].split('~')[0]}. {title}".rstrip())
    else:
        out += [f'## {h}' for h in head[:-1]]
        out.append(f'# {head[-1]}' if head else f"# {u['id']}")
    out += [norm(l) for l in u['lines'] if norm(l)]
    cites = [norm(n['by']) for n in u['notes'] if norm(n['by'])]
    if cites:
        out.append('- Margin notes: ' + '; '.join(cites) + '.')
    return '\n'.join(out) + '\n'


def law_files(law: dict, parsed: dict) -> tuple[dict[str, str], list[list[str]]]:
    """path -> text, and amendments.csv rows [path, provision, source, kind, citation, year]."""
    files: dict[str, str] = {}
    order: list[str] = []
    amend: list[list[str]] = []
    title = [norm(l) for l in parsed['preamble'] if norm(l)]
    heads = [norm(h) for h in parsed.get('title_heads', []) if norm(h)]
    tcites = [norm(n['by']) for n in parsed.get('title_notes', []) if norm(n['by'])]
    if heads:
        title += [f'- Margin: {h}' for h in heads]
    if tcites:
        title.append('- Margin notes: ' + '; '.join(tcites) + '.')
    files[f"{law['dir']}/title.md"] = '\n'.join(title) + '\n'
    order.append('title.md')
    for n in parsed.get('title_notes', []):
        amend.append([law['dir'], 'title', 'margin', n['kind'], norm(n['by']), year_of(n['by'])])
    for u in parsed['units']:
        name = safe(u['id']) + '.md'
        files[f"{law['dir']}/{name}"] = unit_text(u)
        order.append(name)
        for n in u['notes']:
            amend.append([law['dir'], u['id'], 'margin', n['kind'], norm(n['by']), year_of(n['by'])])
    files[f"{law['dir']}/index.txt"] = '\n'.join(order) + '\n'
    return files, amend


def year_of(cite: str) -> str:
    m = re.search(r'(1[6-9]\d\d|20\d\d)', cite)
    return m.group(1) if m else ''


def day_of(s: str) -> str | None:
    """'28th January, 2026', 'June 12, 2026', 'September 2nd, 2026' -> YYYY-MM-DD."""
    m = DAY.match(s or '')
    if not m:
        return None
    d, mon, y = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(5), m.group(4), m.group(6))
    if mon.lower() not in MONTHS:
        return None
    try:
        return datetime(int(y), MONTHS[mon.lower()], int(d)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def act_details(law: dict, parsed: dict) -> None:
    """Assent day (the day an Act comes into force unless it says otherwise: Interpretation Act, Cap. 1, s. 41),
    gazetted day, short title, and the Chapters its long title names."""
    pre = ' '.join(parsed['preamble'])
    m = GAZETTED.search(pre)
    if not m:
        raw = ' '.join(p.get_text() for p in __import__('pymupdf').open(law['pdf']))
        m = GAZETTED.search(raw)
    law['gazetted'] = day_of(m.group(1)) if m else None
    a = ASSENT.search(pre)
    law['assent'] = day_of(a.group(1)) if a else None
    if law['assent'] and law['gazetted'] and not ('2020-12-31' < law['assent'] <= law['gazetted']):
        law['assent_odd'] = law['assent']
        law['assent'] = None  # a misprint (assent after gazetting, or before the year): use the gazetted day
    first = next((u for u in parsed['units'] if u['id'] == '1'), None)
    text = ' '.join(first['lines'][:4]) if first else pre
    c = CITED_AS.search(text)
    if c:
        t = norm(c.group(1)).rstrip(',.')
        law['cited'] = t if len(t) < 200 else ''
    else:
        law['cited'] = ''
    # The Chapters an Act names in its long title ("AN ACT to amend the Public Health Act, Chapter 40 of ...").
    k = next((i for i, l in enumerate(parsed['preamble']) if re.match(r'^\s*AN ACT\b', l)), None)
    lt = ''
    if k is not None:
        lt = ' '.join(parsed['preamble'][k:])
        lt = re.split(r'\(Gazetted|BE IT ENACTED', lt, flags=re.I)[0]
    law['long_title'] = norm(lt)
    law['amends'] = sorted({cap_number(x) for x in AMENDS.finditer(lt)}, key=cap_key)


MADE = re.compile(r'\bMADE\b[^()]{0,160}?\bthis\s+(\d{1,2})\s*(?:st|nd|rd|th)?\s+day\s+of\s*' + _MON + r'\s*,?\s*(\d{4})',
                  re.I | re.S)


def text_layer(pdf: str) -> tuple[str, int]:
    """('born', 0) for a PDF typeset with a text layer; ('scan', pages) for scanned pages with no text layer
    (fewer than 200 letters and digits in all); ('ocr', pages) when every page is a page-sized image under a text
    layer (the publisher's OCR); ('part-ocr', n) when some pages are."""
    import pymupdf
    doc = pymupdf.open(pdf)
    if sum(c.isalnum() for p in doc for c in p.get_text()) < 200:
        return 'scan', len(doc)
    ocr = 0
    for p in doc:
        area = p.rect.width * p.rect.height
        big = any(b['type'] == 1 and (b['bbox'][2] - b['bbox'][0]) * (b['bbox'][3] - b['bbox'][1]) > 0.6 * area
                  for b in p.get_text('dict')['blocks'])
        ocr += bool(big and p.get_text().strip())
    return ('ocr' if ocr == len(doc) else 'part-ocr' if ocr else 'born'), ocr


def si_details(law: dict, parsed: dict) -> None:
    """Gazetted day (an instrument has the force of law on its publication in the Gazette, or from a date it names:
    Interpretation Act, Cap. 1, s. 21(h)), made day, short title and the Chapter it is made under."""
    import pymupdf
    raw = ' '.join(p.get_text() for p in pymupdf.open(law['pdf']))
    pre = ' '.join(parsed['preamble'])
    m = GAZETTED.search(pre) or GAZETTED.search(raw)
    g = day_of(m.group(1)) if m else None
    law['gazetted_odd'] = g if g and g[:4] != str(law['year']) else None
    law['gazetted'] = None if law['gazetted_odd'] else g
    md = MADE.search(raw)
    made = day_of(f'{md.group(1)} {md.group(2)} {md.group(3)}') if md else None
    if made and (int(made[:4]) not in (law['year'] - 1, law['year']) or (law['gazetted'] and made > law['gazetted'])):
        law['made_odd'], made = made, None
    law['made'] = made
    # No clean date: read the OCR text with its usual slips corrected (ocrdates.py), keeping the text as printed.
    # A corrected date is used only when it agrees with the other date (made on or before gazetted, within 60 days).
    law['gazetted_read'] = law['made_read'] = None
    if not law['gazetted'] and not law['gazetted_odd']:
        r = ocrdates.gazetted(pre, law['year']) or ocrdates.gazetted(raw, law['year'])
        if r and not (made and not (0 <= (date.fromisoformat(r[0]) - date.fromisoformat(made)).days <= 60)):
            law['gazetted'], law['gazetted_read'] = r
    if not law['made'] and not law.get('made_odd'):
        r = ocrdates.made(raw, law['year'])
        g = law['gazetted']
        if r and not (g and not (0 <= (date.fromisoformat(g) - date.fromisoformat(r[0])).days <= 60)):
            law['made'], law['made_read'] = r
    first = next((u for u in parsed['units'] if u['id'] == '1'), None)
    printed = titles.extract(first['lines']) if first else ''
    law['printed_title'] = norm(printed) if len(norm(printed)) < 300 else ''
    enabling = re.split(r'\(Gazetted', pre, flags=re.I)[0]
    law['under'] = sorted({cap_number(x) for x in AMENDS.finditer(enabling)}, key=cap_key)


def si_titles(chapters: list[dict], subs: list[dict], acts: list[dict], sis: list[dict], issues: list[dict],
              names: dict[int, str]) -> None:
    """Each built SI's label: its printed short title, with OCR slips repaired from words printed elsewhere in the
    source (titles.py), else its listed name."""
    vocab: set[str] = set()
    for l in chapters + subs + acts:
        vocab |= set(titles.words(l['title']))
    for l in sis:
        if l['printed_title'] and titles.key(l['printed_title']) == titles.key(l['title']):
            vocab |= set(titles.words(l['printed_title'])) & set(titles.words(l['title']))
    for l in sis:
        if not l['printed_title']:
            l['label'], l['label_from'] = l['title'], "the publisher's listing (no citation clause read)"
            continue
        t, fixes, unknown = titles.clean(l['printed_title'], l['title'], vocab, l['layer'] != 'born')
        if fixes and fixes[-1].startswith('listed name used'):
            l['label'], l['label_from'] = t, ("the publisher's listing (the OCR citation clause has words no source "
                                              'gives, or margin citations in it)')
        elif fixes:
            l['label'] = t
            l['label_from'] = 'citation clause, with ' + '; '.join(fixes)
        else:
            l['label'], l['label_from'] = t, 'citation clause'
        if unknown:
            issues.append({'law': names[id(l)], 'issue': f"short title read as {t!r}; {', '.join(unknown)} not found "
                           'in the listed name or any title of the Revised Edition (kept as printed)'})


# ---------------------------------------------------------------------------------------------------- write

def git_date(day: str) -> str:
    """Noon Belize time: UTC-6 all year (Belize has kept no summer time since 1983)."""
    d = datetime.strptime(day, '%Y-%m-%d')
    ts = int(datetime(d.year, d.month, d.day, 18, 0, tzinfo=timezone.utc).timestamp())
    return f'{ts} -0600'


def chapter_message(law: dict, n_units: int, n_cites: int) -> tuple[str, str]:
    name, email = PUBLISHER
    subject = f"Chapter {law['num']}, {law['title']}: Revised Edition 2020, as at 31 December 2020"
    body = [f"The text of Chapter {law['num']} of the Substantive Laws of Belize, Revised Edition 2020, which shows",
            'the law as at 31st December, 2020, as the Attorney General\'s Ministry publishes it (agm.gov.bz).',
            'No earlier text is published, so this commit holds the whole Chapter and nobody is credited with single',
            f'lines. The laws its margin notes cite are kept in the files ({n_cites} citations over {n_units} units)',
            'and listed in data/amendments.csv.']
    trailers = ['Kind: consolidated', f'In-force: {EDITION_DAY}', f'Consolidated: {EDITION_DAY}',
                'In-force-basis: edition as-at date', f"Law: {law['title']}", f"Chapter: {law['num']}",
                f"Source: {BASE}{law['row']['url']}"]
    return f'{name} <{email}>', '\n'.join([subject, '', *body, '', *trailers]) + '\n'


def sub_message(law: dict, n_units: int, n_cites: int) -> tuple[str, str]:
    name, email = PUBLISHER
    if law['whole']:
        subject = f"Chapter {law['num']}, subsidiary laws (whole file): Revised Edition 2020, as at 31 December 2020"
        how = ('This file is kept whole, as one law, because its own list of contents does not mark where each '
               'instrument starts in a way that could be followed (see data/issues.csv).')
    else:
        subject = (f"Chapter {law['num']}, {law['title'][:150]}: subsidiary law, Revised Edition 2020, "
                   'as at 31 December 2020')
        how = (f"It is item {law['label']} of the {law['count']} the file lists on its cover (from printed page "
               f"{law['page']}), split off where its Chapter line and title are printed."
               + (f" The list names it again as item {law['also']}, for its text after the arrangement."
                  if law.get('also') else ''))
    body = [f"Subsidiary legislation under Chapter {law['num']} of the Substantive Laws of Belize, from the Subsidiary",
            'Laws of Belize, Revised Edition 2020, which shows the law as at 31st December, 2020, as the Attorney',
            "General's Ministry publishes it (agm.gov.bz).", how,
            'No earlier text is published, so nobody is credited with single lines. The laws its margin notes cite',
            f'are kept in the files ({n_cites} citations over {n_units} units) and listed in data/amendments.csv.']
    trailers = ['Kind: consolidated', f'In-force: {EDITION_DAY}', f'Consolidated: {EDITION_DAY}',
                'In-force-basis: edition as-at date', f"Law: {law['title'][:200]}", f"Chapter: {law['num']}",
                f"Instrument: {law['label']}", f"Source: {BASE}{law['row']['url']}"]
    return f'{name} <{email}>', '\n'.join([subject, '', *body, '', *trailers]) + '\n'


def si_message(law: dict) -> tuple[str, str]:
    label = law['label']
    author = f"{label[:150]} (S.I. No. {law['no']} of {law['year']}) <si-{law['year']}-{law['no']}@agm-gov-bz.invalid>"
    subject = f"S.I. No. {law['no']} of {law['year']}, {label[:150]}: as made"
    if law['basis'] == 'gazetted':
        when = (f"It is dated by the day it says it was gazetted ({law['day']}): an instrument has the force of law "
                'on its publication in the Gazette, or from a date it names (Interpretation Act, Cap. 1, s. 21(h)).')
    else:
        when = (f"It is dated by the day it says it was made ({law['day']}), because no readable Gazette date is "
                'printed on it.')
    body = [f"Statutory Instrument No. {law['no']} of {law['year']} as made, from the Attorney General's Ministry's PDF.",
            when, 'An instrument may name a later day for its commencement in its own text; that is not read here.',
            'Its changes to other instruments are not applied to them.']
    read = [(w, law[f'{w}_read']) for w in ('gazetted', 'made') if law.get(f'{w}_read')]
    if read:
        body.append('The ' + ' and '.join('Gazette date' if w == 'gazetted' else 'made date' for w, _ in read) +
                    (' was' if len(read) == 1 else ' were') + ' read from OCR text with slips in its digits or month name corrected (printed: ' +
                    '; '.join(f'"{t}"' for _, t in read) + '); see ocrdates.py in the builder.')
    if law['layer'] in ('ocr', 'part-ocr'):
        body.append('The PDF is a scan: its text is the text layer the publisher added by optical character '
                    'recognition, copied as it is, errors and all; it was not checked against the page images.')
    trailers = ['Kind: enacted', f"In-force: {law['day']}", f"In-force-basis: {law['basis']}"]
    if law.get('gazetted'):
        trailers.append(f"Gazetted: {law['gazetted']}")
    if law.get('made'):
        trailers.append(f"Made: {law['made']}")
    for w, t in read:
        trailers.append(f"{w.capitalize()}-as-printed: {t}")
    trailers += [f"Law: {label[:200]}", f"Law-title-from: {law['label_from']}",
                 f"Statutory-instrument: No. {law['no']} of {law['year']}"]
    trailers += [f'Made-under: Chapter {c}' for c in law['under']]
    if law['layer'] in ('ocr', 'part-ocr'):
        trailers.append('Text-layer: ' + ('OCR (every page)' if law['layer'] == 'ocr' else 'OCR (some pages)'))
    trailers.append(f"Source: {BASE}{law['row']['url']}")
    return author, '\n'.join([subject, '', *body, '', *trailers]) + '\n'


def act_message(law: dict) -> tuple[str, str]:
    label = law['cited'] or law['title']
    author = f"{label} (No. {law['no']} of {law['year']}) <act-{law['year']}-{law['no']}@agm-gov-bz.invalid>"
    subject = f"Act No. {law['no']} of {law['year']}, {label}: as enacted"
    if law['basis'] == 'assent':
        when = (f"It is dated by the day the Governor-General assented to it ({law['day']}), the day an Act comes into "
                'force unless it sets another (Interpretation Act, Cap. 1, s. 41).')
    else:
        when = (f"It is dated by the day it says it was gazetted ({law['day']}), because no readable assent date "
                'is printed on it.')
    body = [f"Act No. {law['no']} of {law['year']} as enacted, from the Attorney General's Ministry's PDF of the Act.",
            when, 'An Act may set a later day for its commencement in its own text, or leave it to an order; that '
            'is not read here.', 'Its changes to other laws are not applied to the Chapters of the Revised Edition, '
            'because no later consolidation is published to check them against.']
    trailers = ['Kind: enacted', f"In-force: {law['day']}", f"In-force-basis: {law['basis']}"]
    if law.get('assent'):
        trailers.append(f"Assented: {law['assent']}")
    if law.get('gazetted'):
        trailers.append(f"Gazetted: {law['gazetted']}")
    trailers += [f"Law: {label}", f"Act: No. {law['no']} of {law['year']}"]
    trailers += [f'Names-chapter: {c}' for c in law['amends']]
    trailers.append(f"Source: {BASE}{law['row']['url']}")
    return author, '\n'.join([subject, '', *body, '', *trailers]) + '\n'


def fast_import(repo: Path, commits: list[tuple[str, str, str, dict]], docs: dict[str, bytes], today: str) -> None:
    buf = io.BytesIO()
    w = buf.write
    for day, author, msg, files in commits:
        when = git_date(day)
        w(b'commit refs/heads/main\n')
        w(f'author {author} {when}\ncommitter {COMMITTER} {when}\n'.encode('utf-8'))
        m = msg.encode('utf-8')
        w(f'data {len(m)}\n'.encode() + m + b'\n')
        for path, text in sorted(files.items()):
            t = text.encode('utf-8')
            w(f'M 100644 inline {path}\ndata {len(t)}\n'.encode('utf-8') + t + b'\n')
        w(b'\n')
    when = git_date(today)
    msg = (f'Documentation: README, REPRODUCE, SOURCES, corpus.json, tools and data\n\n'
           f'Built from the agm.gov.bz PDF cache on {today}.\n\nKind: documentation\nIn-force: {today}\n').encode()
    w(b'commit refs/heads/main\n')
    w(f'author {COMMITTER} {when}\ncommitter {COMMITTER} {when}\n'.encode())
    w(f'data {len(msg)}\n'.encode() + msg + b'\n')
    for path, data in sorted(docs.items()):
        w(f'M 100644 inline {path}\ndata {len(data)}\n'.encode('utf-8') + data + b'\n')
    w(b'\n')
    r = subprocess.run(['git', '-C', str(repo), 'fast-import', '--quiet', '--force'], input=buf.getvalue(),
                       capture_output=True)
    if r.returncode:
        sys.exit(r.stderr.decode('utf-8', 'replace')[-3000:])


def fresh_repo(repo: Path) -> None:
    import shutil
    import stat
    if repo.resolve() == CHECKOUT:
        sys.exit(f'refusing to build into {CHECKOUT}: build into a separate folder')

    def onerr(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    repo.mkdir(parents=True, exist_ok=True)
    if (repo / '.git').exists():
        shutil.rmtree(repo / '.git', onerror=onerr)
    for child in repo.iterdir():
        shutil.rmtree(child, onerror=onerr) if child.is_dir() else child.unlink()
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], check=True)
    for k, v in (('core.autocrlf', 'false'), ('core.longpaths', 'true'), ('core.quotepath', 'false')):
        subprocess.run(['git', '-C', str(repo), 'config', k, v], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('repo', type=Path)
    ap.add_argument('--today', required=True)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--no-parse-cache', action='store_true', help='parse every PDF again (slow, about 10 minutes)')
    args = ap.parse_args()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.today):
        sys.exit('--today must be YYYY-MM-DD')
    retrieved = (CACHE / 'pdf_fetched_on.txt').read_text().strip()[:10]
    if retrieved > args.today:
        sys.exit(f'PDFs retrieved {retrieved}, after --today')

    chapters, acts, issues = load_catalogue(args.limit)
    subs = load_subsidiary(issues, args.limit)
    sis = load_sis(issues, args.limit)
    commits: list[tuple[str, str, str, dict]] = []
    amend: list[list[str]] = []
    sha_of: dict[str, str] = {}
    pending_si: list[tuple[int, dict, str]] = []
    for i, law in enumerate(chapters + subs + acts + sis):
        name = law['row']['name'] + (f" (item {law['label']})" if law['kind'] == 'subsidiary' and not law['whole'] else '')
        if law['pdf'] not in sha_of:
            sha_of[law['pdf']] = hashlib.sha256(Path(law['pdf']).read_bytes()).hexdigest()
        law['sha256'] = sha_of[law['pdf']]
        if law['kind'] == 'si':
            law['layer'], n = text_layer(law['pdf'])
            if law['layer'] == 'scan':
                issues.append({'law': name, 'issue': f'{n} page(s), all scanned images with no text layer; not built',
                               'si': 'scan'})
                continue
            if law['layer'] in ('ocr', 'part-ocr'):
                issues.append({'law': name, 'issue': f"{'every page' if law['layer'] == 'ocr' else f'{n} page(s)'} "
                               "a scan under the publisher's OCR text layer; built from that text, not checked"})
        mode = {'chapter': 'chapter', 'subsidiary': 'sub', 'act': 'act', 'si': 'si'}[law['kind']]
        parsed = parse_cached(law['pdf'], mode, not args.no_parse_cache, law.get('span'))
        files, rows = law_files(law, parsed)
        law['units'] = sum(1 for p in files if not p.endswith(('/title.md', '/index.txt')))
        law['cites'] = len(rows)
        if parsed.get('unreadable_lines'):
            issues.append({'law': name, 'issue': f"{parsed['unreadable_lines']} printed lines in a font "
                           'with no usable text mapping (no readable text layer, usually a schedule table); left out'})
        if parsed.get('image_pages'):
            issues.append({'law': name, 'issue': f"{parsed['image_pages']} page(s) are scanned images "
                           'with no text layer; left out'})
        if not parsed['units']:
            issues.append({'law': name, 'issue': 'no numbered sections found; the whole text is in title.md'})
        if law['kind'] == 'chapter':
            author, msg = chapter_message(law, law['units'], len(rows))
            law['day'] = EDITION_DAY
        elif law['kind'] == 'subsidiary':
            author, msg = sub_message(law, law['units'], len(rows))
            law['day'] = EDITION_DAY
        elif law['kind'] == 'si':
            si_details(law, parsed)
            day = law['gazetted'] or law['made']
            law['basis'] = 'gazetted' if law['gazetted'] else 'made'
            if law.get('gazetted_odd'):
                issues.append({'law': name, 'issue': f"Gazette date read as {law['gazetted_odd']}, not in "
                               f"{law['year']}; not used"})
            if law.get('made_odd'):
                issues.append({'law': name, 'issue': f"made date read as {law['made_odd']}, not in {law['year'] - 1} "
                               f"or {law['year']} or after its Gazette date; not used"})
            if not day:
                issues.append({'law': name, 'issue': 'no readable Gazette or made date; not built', 'si': 'undated'})
                continue
            if day > args.today:
                issues.append({'law': name, 'issue': f'dated {day}, after the build day; not built'})
                continue
            law['day'] = day
            for c in law['under']:
                rows.append([law['dir'], 'title', 'enabling words', 'made under', f'Chapter {c}', str(law['year'])])
            # the message waits for the title vocabulary, which needs every SI's printed title (below)
            pending_si.append((len(commits), law, name))
            amend += rows
            commits.append((law['day'], '', '', files))
            continue
        else:
            act_details(law, parsed)
            day = law['assent'] or law['gazetted']
            law['basis'] = 'assent' if law['assent'] else 'gazetted'
            if law.get('assent_odd'):
                issues.append({'law': name, 'issue': f"assent date printed as {law['assent_odd']}, "
                               f"not between 2021 and the gazetted date {law['gazetted']}; dated by the gazetted date"})
            if not day:
                issues.append({'law': name, 'issue': 'no assent or Gazetted date found; not built'})
                continue
            if day > args.today:
                issues.append({'law': name, 'issue': f'dated {day}, after the build day; not built'})
                continue
            if day <= EDITION_DAY:
                issues.append({'law': name, 'issue': f'dated {day}, not after the Revised Edition; not built'})
                continue
            law['day'] = day
            for c in law['amends']:
                rows.append([law['dir'], 'title', 'long title', 'names', f'Chapter {c}', str(law['year'])])
            author, msg = act_message(law)
        author = re.sub(r'[<>\n]', '', author.rsplit(' <', 1)[0]) + ' <' + author.rsplit(' <', 1)[1]
        amend += rows
        commits.append((law['day'], author, msg, files))
        if (i + 1) % 100 == 0:
            print(f'{i + 1} laws read', flush=True)
    si_titles(chapters, subs, acts, [l for _, l, _ in pending_si], issues, {id(l): n for _, l, n in pending_si})
    for k, law, _ in pending_si:
        author, msg = si_message(law)
        author = re.sub(r'[<>\n]', '', author.rsplit(' <', 1)[0]) + ' <' + author.rsplit(' <', 1)[1]
        commits[k] = (commits[k][0], author, msg, commits[k][3])
    order = {id(c): k for k, c in enumerate(commits)}
    # by date; within a date, Chapters by number, their subsidiary laws, then Acts, then statutory instruments
    commits.sort(key=lambda c: (c[0], order[id(c)]))
    built = [l for l in chapters + subs + acts + sis if l.get('day')]
    print(f'{len(chapters)} chapters, {len(subs)} subsidiary, {len(acts)} acts, {len(sis)} SIs, {len(commits)} commits, '
          f'{len(issues)} issues, {len(amend)} amendment rows', flush=True)

    import docs as docmod
    docs = docmod.render(chapters, acts, built, issues, amend, args.today, retrieved)

    fresh_repo(args.repo)
    fast_import(args.repo, commits, docs, args.today)
    subprocess.run(['git', '-C', str(args.repo), 'checkout', '-q', '-f', 'main'], check=True)
    head = subprocess.run(['git', '-C', str(args.repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    count = subprocess.run(['git', '-C', str(args.repo), 'rev-list', '--count', 'HEAD'], capture_output=True,
                           text=True).stdout.strip()
    print(f'built {args.repo}: {count} commits, head {head}', flush=True)


if __name__ == '__main__':
    main()
