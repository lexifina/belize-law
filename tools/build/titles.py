"""The short title an SI prints in its citation clause ("These Regulations may be cited as the ..."), read from the
upper-case run that follows, with margin notes ("Citation.", "Short title.") that the text layer puts inside the
clause left out. The title must end with its kind ("ORDER", "REGULATIONS", ... outside brackets), else the listed
name is used, as before.

OCR slips are repaired only from words printed elsewhere in the source:
- `vocab`: the words of the titles the Revised Edition prints for its Chapters and subsidiary laws, the Acts'
  listed names, and the words SI titles share with their listed names when the two agree letter for letter;
- `listed`: this SI's own name in the publisher's listing (`POST /api-laws/`).

A word in neither is repaired only when one of these gives it:
- a lower-case letter or a 0/1 inside an upper-case word, read as the capital ("DUTlES", "REGULATI0NS", "oRDER");
  this is the only repair made in a typeset PDF (its font maps capital I to l);
- in an OCR text layer, also: two pieces joined ("DEFENC E"), one run split ("APPROVEDENTERPRISE"), a word (or two)
  of the listed name within two letters ("APPOTNTMENT" -> "APPOINTMENT", "OFREGTSTRAR" -> "OF REGISTRAR"), or the
  one vocabulary word within one letter;
- a year read as OCR letters ("2Ol9" -> "2019"), or a year the printed title leaves off, taken from the listed name
  when the two otherwise agree letter for letter.
Nothing else is changed. An OCR title with words no source gives, or with margin citations caught in it, gives way
to the listed name when every word of that is in the vocabulary; otherwise it stays as printed and is reported."""
import re

KEYWORD = r'(?:ORDER|REGULATIONS|RULES|BY-LAWS|NOTICE|PROCLAMATION|DIRECTIONS?|DECLARATION|NOTIFICATION)'
_YEAR = r'[12][0-9OolI]{3}'
TOKEN = re.compile(r'\S+')
MARGIN = re.compile(r'^[-–—\s]*(?:Citation|Citetion|Citatian|Citatioo|Short\s*title|Shorl\s*title|Title)\.?$', re.I)
END = re.compile(r'([^A-Za-z]*\)|)' + KEYWORD + r'[,.]?(' + _YEAR + r')?[.,;:)]*', re.I)


def words(s: str) -> list[str]:
    return re.findall(r"[A-Z0-9’']+", s.upper())


def key(s: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', s.upper())


def _upperish(tok: str) -> bool:
    """A token of an upper-case title: mostly capitals, "No.", a number or year (OCR'd or not), or punctuation."""
    if re.fullmatch(r'\W*' + _YEAR + r'\W*', tok) or re.fullmatch(r'\(?No\.?\d*\)?', tok):
        return True
    letters = [c for c in tok if c.isalpha()]
    if not letters:
        return True
    return sum(c.isupper() for c in letters) >= 0.6 * len(letters)


def extract(lines: list[str]) -> str:
    """The printed short title from the first section's lines; '' when there is no citation clause or the title
    does not end with its kind."""
    lines = [l for l in lines[:10] if not MARGIN.match(l.strip())]
    text = re.sub(r'\s+', ' ', ' '.join(lines))
    m = re.search(r'cited\s+as\s*(?:the\s+)?[-–—]?\s*', text, re.I)
    if not m:
        return ''
    out, skipped, lead, state, loose = [], 0, 0, '', None
    for t in TOKEN.findall(text[m.end():]):
        if state == 'year':
            if re.fullmatch(_YEAR + r'[.,;:)]*', t):
                out.append(t)
            state = 'end'
            break
        if not _upperish(t):
            if out and skipped < 3:
                skipped += 1  # a margin note inside the clause; the title goes on after it
                continue
            if out or lead >= 4:
                break
            lead += 1  # margin words before the title
            continue
        depth = sum(x.count('(') - x.count(')') for x in out)  # before this token: a kind in brackets goes on
        out.append(t)
        skipped = 0
        e = END.fullmatch(t)
        if e and not t.startswith('('):
            if depth + e.group(1).count('(') - e.group(1).count(')') <= 0:
                if e.group(2):
                    state = 'end'
                    break
                state = 'year'
            else:
                loose = len(out)  # a kind inside an unclosed bracket: the end, if no other comes
        if len(out) > 40:
            break
    if state not in ('end', 'year'):
        if loose is None:
            return ''
        out = out[:loose]
    return ' '.join(out).strip(' ,;:-–—').rstrip('.').rstrip(',')


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _year(tok: str) -> str:
    return re.sub(_YEAR, lambda m: m.group(0).translate(str.maketrans('OolI', '0011')), tok)


def _shape(tok: str) -> str:
    """A lower-case letter, or a 0/1 between two letters, inside an upper-case word read as the capital; a year
    with OCR letters in it ("2Ol9") read as digits. Numbers ("NO.14", "COVID-19") are left alone."""
    tok = re.sub(r'(?<![A-Za-z0-9])[12][0-9OolI]{3}(?![A-Za-z0-9])',
                 lambda m: _year(m.group(0)) if sum(c.isdigit() for c in m.group(0)) >= 2 else m.group(0), tok)
    if sum(c.isalpha() for c in tok) < 2 or re.fullmatch(r'\(?No\.?\d*\)?', tok):
        return tok
    tok = re.sub(r'(?<=[A-Za-z])[01](?=[A-Za-z])', lambda m: 'O' if m.group(0) == '0' else 'I', tok)
    return ''.join('I' if c == 'l' else c.upper() if c.islower() else c for c in tok)


def _pieces_known(tok: str, known: set[str]) -> bool:
    ps = re.findall(r"[A-Z0-9’']+", tok.upper())
    return bool(ps) and all(p in known or p.isdigit() or (len(p) <= 2 and p.isalpha()) for p in ps)


def _wrap(orig: str, word: str) -> str:
    return re.match(r'^\W*', orig).group(0) + word + re.search(r'\W*$', orig).group(0)


def clean(printed: str, listed: str, vocab: set[str], ocr: bool) -> tuple[str, list[str], list[str]]:
    """(title, repairs made, words left unknown)."""
    listed_w = words(listed)
    known = vocab | set(listed_w)
    toks = printed.split()
    fixes, unknown, out = [], [], []
    core = lambda s: re.sub(r"[^A-Z0-9’']", '', s.upper())
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.endswith('-') and i + 1 < len(toks) and core(t) + core(toks[i + 1]) in known:
            # a word broken at a line end ("SCHED- ULE)", "(COM- MENCEMENT")
            new = re.match(r'^\W*', t).group(0) + core(t) + core(toks[i + 1]) + re.search(r'\W*$', toks[i + 1]).group(0)
            fixes.append(f'{t} {toks[i + 1]} -> {new}')
            out.append(new)
            i += 2
            continue
        if _pieces_known(t, known) and t == _shape(t) or not re.search('[A-Za-z]', t):
            out.append(t)
            i += 1
            continue
        s = _shape(t)
        if s != t and (_pieces_known(s, known) or re.fullmatch(r'\W*\d{4}\W*', s)):
            fixes.append(f'{t} -> {s}')
            out.append(s)
            i += 1
            continue
        if _pieces_known(t, known):
            out.append(t)
            i += 1
            continue
        if not ocr:
            unknown.append(t)
            out.append(t)
            i += 1
            continue
        cs = core(s)
        nxt = core(_shape(toks[i + 1])) if i + 1 < len(toks) else ''
        if nxt and cs + nxt in known and (nxt not in known or len(nxt) <= 2) and not toks[i + 1].startswith('('):
            new = re.match(r'^\W*', t).group(0) + cs + nxt + re.search(r'\W*$', toks[i + 1]).group(0)
            fixes.append(f'{t} {toks[i + 1]} -> {new}')
            out.append(new)
            i += 2
            continue
        split = next((k for k in range(len(cs) - 2, 1, -1) if cs[:k] in known and cs[k:] in known), None)
        if split:
            new = _wrap(t, f'{cs[:split]} {cs[split:]}')
            fixes.append(f'{t} -> {new}')
            out.append(new)
            i += 1
            continue
        best = None
        for n in (1, 2):
            for k in range(len(listed_w) - n + 1):
                cand = listed_w[k:k + n]
                if not all(w in vocab for w in cand):
                    continue
                d = _lev(cs, ''.join(cand))
                if d <= 2 and d <= len(cs) // 4 and (best is None or d < best[0]):
                    best = (d, ' '.join(cand))
        if not best and len(cs) >= 6:
            near = [w for w in vocab if abs(len(w) - len(cs)) <= 1 and _lev(cs, w) <= 1]
            if len(near) == 1:
                best = (1, near[0])
        if best:
            new = _wrap(t, best[1])
            fixes.append(f'{t} -> {new}')
            out.append(new)
            i += 1
            continue
        unknown.append(t)
        out.append(t)
        i += 1
    title = ' '.join(out)
    title = re.sub(r'\b(' + KEYWORD + r'),(?=\d{4}$)', r'\1, ', title)
    if not re.search(r'\d{4}$', title):
        y = re.search(r'(\d{4})$', key(listed))
        if y and key(listed) == key(title) + y.group(1):
            fixes.append(f'year {y.group(1)} from the listed name')
            title += f', {y.group(1)}'
    if ocr:
        caught = [t for t in out[:-1] if re.fullmatch(r'\W*S\.?I\.?\W*|\d{4}\.', t, re.I)]  # margin citations
        if unknown or caught:
            if listed_w and all(w in vocab or w.isdigit() for w in listed_w):
                return listed, fixes + [f'listed name used ({len(unknown)} unknown, {len(caught)} margin words)'], []
    return title, fixes, unknown
