r"""Read a Gazette or made date from an OCR text layer whose digits and month names carry the usual OCR slips.

Only these corrections are made, and each is recorded with the text as printed:
- in a day or year, the letters l, I, i, |, ! read as 1 and O, o as 0 (shapes OCR confuses with those digits);
  a space inside a two-digit day ("1 3th") is dropped;
- the ordinal suffix after the day may be garbled ("l8'h", "22^d", "6ft", "5u"): a short ending of letters or a
  quote mark, never a letter shaped like a digit ("1qth" may be 19th) or a mark where a digit was lost ("1$th");
- a month name may differ from one month by at most two letters, when every other month is at least two letters
  further away ("Octoher", "Novenber", "N1arch", "lonuary", "Augusr").
The clause may itself be garbled ("MADB", "MADEbythe", "l\{ADE this"), and a proclamation's "GIVEN under my hand"
(read as "GMN under my hand") counts as its making. Anything else (a "$" or "&" where a digit should be, a day over
31, a year that is not the instrument's) is not read.
"""
import re
from datetime import date

MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
          'november', 'december']
_ONE, _ZERO = 'lIi|!', 'Oo'
_D = r'[0-9lIi|!Oo]'
# day: one or two digit-shapes (one space allowed between two); suffix: up to 3 marks, checked in _day
DAY = rf'({_D}(?:\s?{_D})?)(\S{{0,3}}?)'
SUFFIX = re.compile(r"(?:st|nd|rd|th|[tdhsnmu]|ft|il|['’`\"^][a-z]?|[a-z]?['’\"])", re.I)
YEAR = r'([12][0-9lIi|!Oo]{3})(?![0-9A-Za-z])'
GAZ = re.compile(r'\(\s*G\s*[ao]\s*z\s*e\s*t\s*t\s*[a-z]{1,3}\s*:?\s*' + DAY + r'\s+([A-Za-z1][A-Za-z1 ]{1,11}?)\s*,?\s*'
                 + YEAR)
MADE = re.compile(r'(?:\bM\s*A\s*D\s*[EB]|\S{0,3}ADE(?=\s+this)|\bunder\s+my\s+hand)[^()]{0,160}?\bthis\s+' + DAY + r'\s+day\s+of\s*'
                  r'([A-Za-z1][A-Za-z1 ]{1,11}?)\s*[,.]?\s*' + YEAR, re.I | re.S)


def _digits(s: str) -> str | None:
    s = s.replace(' ', '')
    out = ''.join('1' if c in _ONE else '0' if c in _ZERO else c for c in s)
    return out if out.isdigit() else None


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def month_of(s: str) -> int | None:
    w = re.sub(r'\s+', '', s).lower().replace('1', 'l')
    if w in MONTHS:
        return MONTHS.index(w) + 1
    ds = sorted((_lev(w, m), k) for k, m in enumerate(MONTHS))
    (d0, k0), (d1, _) = ds[0], ds[1]
    if d0 <= 2 and d1 - d0 >= 2 and len(w) >= 3:
        return k0 + 1
    return None


def _day(m: re.Match, years: tuple[int, ...]) -> str | None:
    raw, suffix = m.group(1), m.group(2)
    if not any(c.isdigit() for c in raw):  # a lone 'l' or '|' could be any digit
        return None
    if ' ' in raw and not raw[-1].isdigit():  # '1 lh': a second digit, or the start of the suffix?
        return None
    # the suffix must look like an ordinal ending, garbled or not: never a letter shaped like a digit ('1qth' may be
    # 19th) or a mark where a digit was lost ('1$th', '1&th')
    if suffix and not SUFFIX.fullmatch(suffix):
        return None
    if suffix and len(raw.replace(' ', '')) == 1 and suffix[0] in _ONE + _ZERO:  # '1lth': 11th or 1st?
        return None
    d, y = _digits(raw), _digits(m.group(4))
    mon = month_of(m.group(3))
    if not d or not y or not mon or int(y) not in years:
        return None
    try:
        return date(int(y), mon, int(d)).isoformat()
    except ValueError:
        return None


def gazetted(text: str, year: int) -> tuple[str, str] | None:
    """(YYYY-MM-DD, text as printed) for the first readable '(Gazetted ...)' in the instrument's year."""
    for m in GAZ.finditer(text):
        day = _day(m, (year,))
        if day:
            return day, re.sub(r'\s+', ' ', m.group(0).lstrip('( ')).strip()
    return None


def made(text: str, year: int) -> tuple[str, str] | None:
    """(YYYY-MM-DD, text as printed) for the first readable 'MADE ... this <day> day of <month>, <year>' (or a
    proclamation's 'GIVEN under my hand ... this ...'), in the instrument's year or the year before."""
    for m in MADE.finditer(text):
        day = _day(m, (year - 1, year))
        if day:
            s = re.sub(r'\s+', ' ', m.group(0))
            return day, s[s.lower().rfind('this '):].strip()
    return None
