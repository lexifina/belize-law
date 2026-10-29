"""README, REPRODUCE.md, SOURCES.md, LICENSE, corpus.json, laws.csv, data/ and tools for the Belize law repository
(called by build.py)."""
import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
REPO_FILES = HERE / 'repo'
CACHE = HERE / '.cache'
# Published with the record: what a reader needs to rebuild from the retrieved PDFs and to check the result. The
# retrieval script and its notes stay private (the user's rule of 2026-10-29), and publish_gate (gitlaw_common,
# private) checks every file before it is written.
BUILD_FILES = ('source_files.py', 'parse_pdf.py', 'subsid.py', 'ocrdates.py', 'titles.py', 'build.py', 'docs.py',
               'check_words.py')
sys.path.insert(0, str(HERE.parent / 'gitlaw_common'))
try:
    from publish_gate import publish_gate  # noqa: E402
except ImportError:          # an outside reader rebuilding from the published tools: no private rule to apply
    if os.environ.get('GITLAW_PUBLIC_REBUILD') != '1':
        raise SystemExit('publish gate missing: run from lexifina/scripts, or set GITLAW_PUBLIC_REBUILD=1')

    def publish_gate(files): return files
TEMPLATES = ('README.md', 'REPRODUCE.md', 'SOURCES.md', 'LICENSE')
RECORD_NOTE = ('The Chapters of the Substantive Laws of Belize and the instruments of the Subsidiary Laws, Revised '
               'Edition 2020, as at 31 December 2020 (one version each, current-only: agm.gov.bz publishes no earlier '
               'consolidation); the Acts of 2021 to 2026 as enacted, dated by assent; and the statutory instruments '
               'of 2020 to 2026 that have a text layer, as made, dated by their Gazette date. Later Acts and '
               'instruments are not applied to the texts they amend; scanned instruments with no text layer are '
               'listed, not built.')


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _csv(rows: list[list]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    for r in rows:
        w.writerow(r)
    return out.getvalue().encode('utf-8')


def render(chapters: list[dict], acts: list[dict], built: list[dict], issues: list[dict], amend: list[list[str]],
           today: str, retrieved: str) -> dict[str, bytes]:
    b_ch = [l for l in built if l['kind'] == 'chapter']
    b_act = [l for l in built if l['kind'] == 'act']
    b_sub = [l for l in built if l['kind'] == 'subsidiary']
    b_si = [l for l in built if l['kind'] == 'si']
    si_days = sorted(l['day'] for l in b_si)
    act_days = sorted(l['day'] for l in b_act)
    margin = [r for r in amend if r[2] == 'margin']
    names = [r for r in amend if r[2] == 'long title']
    catalogue = json.loads((CACHE / 'catalogue.json').read_text('utf-8'))
    listed = Counter(r['category'] for r in catalogue['rows'])
    stats = {
        'today': today, 'retrieved': retrieved,
        'chapters': len(b_ch), 'acts': len(b_act), 'laws': len(built),
        'chapter_units': sum(l['units'] for l in b_ch), 'act_units': sum(l['units'] for l in b_act),
        'units': sum(l['units'] for l in built), 'commits': len(built) + 1,
        'margin_cites': len(margin), 'margin_cites_chapters': sum(1 for r in margin if r[0].startswith('cap/')),
        'names_rows': len(names),
        'first_day': min(l['day'] for l in built) if built else '',
        'first_act': act_days[0] if act_days else '', 'last_act': act_days[-1] if act_days else '',
        'assent_dated': sum(1 for l in b_act if l['basis'] == 'assent'),
        'gazette_dated': sum(1 for l in b_act if l['basis'] == 'gazetted'),
        'issues': len(issues),
        'subsidiary': len(b_sub), 'subsidiary_units': sum(l['units'] for l in b_sub),
        'subsidiary_files': len({l['pdf'] for l in b_sub}),
        'subsidiary_whole': sum(1 for l in b_sub if l['whole']),
        'subsidiary_split_files': len({l['pdf'] for l in b_sub if not l['whole']}),
        'sis': len(b_si), 'si_units': sum(l['units'] for l in b_si),
        'first_si': si_days[0] if si_days else '', 'last_si': si_days[-1] if si_days else '',
        'si_gazette_dated': sum(1 for l in b_si if l['basis'] == 'gazetted'),
        'si_made_dated': sum(1 for l in b_si if l['basis'] == 'made'),
        'si_ocr': sum(1 for l in b_si if l['layer'] == 'ocr'),
        'si_part_ocr': sum(1 for l in b_si if l['layer'] == 'part-ocr'),
        'si_scans': sum(1 for i in issues if i.get('si') == 'scan'),
        'si_pages': sum(1 for i in issues if i.get('si') == 'page'),
        'si_undated': sum(1 for i in issues if i.get('si') == 'undated'),
        'si_ocr_dates': sum(1 for l in b_si if l.get('gazetted_read') or l.get('made_read')),
        'si_titles_repaired': sum(1 for l in b_si if l.get('label_from', '').startswith('citation clause, with')),
        'si_titles_listed': sum(1 for l in b_si if l.get('label_from', '').startswith("the publisher's listing")),
        'sis_by_year': dict(sorted(Counter(str(l['year']) for l in b_si).items())),
        'listed_chapters': listed.get('substantive', 0), 'listed_acts': listed.get('act', 0),
        'listed_subsidiary': listed.get('subsidiary', 0), 'listed_si': listed.get('si', 0),
        'acts_by_year': dict(sorted(Counter(str(l['year']) for l in b_act).items())),
        'margin_kinds': dict(sorted(Counter(r[3] for r in margin).items())),
    }
    texts = {}
    for name in TEMPLATES:
        t = (REPO_FILES / name).read_text('utf-8')
        for k, v in stats.items():
            if isinstance(v, (str, int)):
                t = t.replace('{{' + k.upper() + '}}', f'{v:,}' if isinstance(v, int) else v)
        for f in BUILD_FILES:
            t = t.replace('{{SHA_' + f.upper().replace('.', '_') + '}}', _sha(HERE / f))
        texts[name] = t
        if '{{' in t:
            raise SystemExit(f'{name}: unfilled placeholder near ' + t[t.index('{{'):t.index('{{') + 40])

    def number(l: dict) -> str:
        if l['kind'] == 'chapter':
            return l['num']
        if l['kind'] == 'subsidiary':
            return f"{l['num']} item {l['label']}"
        return f"{'S.I. ' if l['kind'] == 'si' else ''}No. {l['no']} of {l['year']}"

    def span(l: dict) -> str:
        """Where an instrument sits in its file: start page:y - end page:y (0-based pages, end exclusive)."""
        s = l.get('span')
        if not s:
            return ''
        a, b = s
        return f'{a[0]}:{a[1]}-' + (f'{b[0]}:{b[1]}' if b else 'end')

    laws_csv = _csv([['path', 'kind', 'chapter_or_act', 'title', 'in_force', 'in_force_basis', 'assented', 'gazetted',
                      'made', 'units', 'margin_citations', 'names_chapters', 'text_layer', 'span', 'source_url',
                      'pdf_sha256']] +
                    [[l['dir'] + '/', l['kind'], number(l),
                      l['title'] if l['kind'] in ('chapter', 'subsidiary') else (l.get('label') or l.get('cited') or l['title']),
                      l['day'], 'edition as-at date' if l['kind'] in ('chapter', 'subsidiary') else l['basis'],
                      l.get('assent') or '', l.get('gazetted') or '', l.get('made') or '', l['units'], l['cites'],
                      ' '.join(l.get('amends', []) or l.get('under', [])), l.get('layer', 'born'), span(l),
                      'https://agm.gov.bz' + l['row']['url'], l['sha256']]
                     for l in built])
    not_built = _csv([['statutory_instrument', 'reason']] +
                     [[i['law'], {'scan': 'scanned, no text layer', 'page': 'the site answers with a web page, not a PDF',
                                  'undated': 'no readable Gazette or made date',
                                  'unnumbered': 'no S.I. number in its listed name or its text',
                                  'part': 'a part of a listed S.I., published on its own'}[i['si']]]
                      for i in issues if i.get('si')])
    amend_csv = _csv([['path', 'provision', 'source', 'kind', 'citation', 'year']] + amend)
    issues_csv = _csv([['law', 'issue']] + [[i['law'], i['issue']] for i in issues])

    corpus = {
        'corpus': 'bz/national/acts',
        'name': 'Laws of Belize (Revised Edition 2020, Acts 2021-2026 and statutory instruments 2020-2026)',
        'label': 'Belize',
        'language': 'en',
        'laws': {'chapters': len(b_ch), 'subsidiary_instruments': len(b_sub), 'acts': len(b_act),
                 'statutory_instruments': len(b_si)},
        'history': 'current-only',
        'history_from': stats['first_day'] or '2020-12-31',
        'record_to': max(l['day'] for l in built) if built else '2020-12-31',
        'record_note': RECORD_NOTE,
        'checked_on': today,
        'built': today,
        'in_force_trailer': 'In-force',
        'baseline_trailer': 'Consolidated',
        'dates': {
            'commit': 'Chapters: the Revised Edition 2020 as-at date (2020-12-31). Acts: the day of assent, the day '
                      'an Act comes into force unless it sets another (Interpretation Act, Cap. 1, s. 41); the '
                      'gazetted day where no assent date is printed. Subsidiary laws: the Revised Edition 2020 as-at '
                      'date. Statutory instruments: the day gazetted, when an instrument has the force of law unless '
                      'it names another day (Cap. 1, s. 21(h)); the made day where no Gazette date is readable',
            'baseline_trailer': 'Consolidated',
            'other_trailers': ['In-force-basis', 'Assented', 'Gazetted', 'Made', 'Names-chapter', 'Made-under',
                               'Instrument', 'Statutory-instrument', 'Text-layer'],
            'time': '12:00 UTC-6 (Belize, no summer time)',
        },
        'author': {
            'consolidated': "Laws of Belize (Attorney General's Ministry)",
            'enacted': 'the Act or instrument itself (act-<year>-<number>@agm-gov-bz.invalid, '
                       'si-<year>-<number>@agm-gov-bz.invalid)',
            'amendment': 'none: no amendment is applied to a Chapter',
        },
        'scope': {
            'trailer': 'Applies',
            'when_absent': 'not extracted for Belize; commencement, savings and transitional rules are in each Act',
            'default_reach': {
                'rule': 'presumption against retroactivity, and savings on repeal',
                'meaning': 'unless the contrary intention appears, a repeal does not revive anything not in force, or '
                           'affect the previous operation of the repealed law, rights and liabilities accrued under '
                           'it, penalties incurred, or proceedings about them',
                'authority': 'Interpretation Act, Chapter 1 of the Substantive Laws of Belize, R.E. 2020, s. 28 '
                             '(other effects of repeal); s. 41 (an Act comes into force on assent unless it says '
                             'otherwise)',
                'decided_here': False,
            },
        },
        'citation': {'file': r'(cap/[0-9]+(?:\.[0-9]+)?[A-Z]?|acts/[0-9]{4}/[0-9]+)/0*([0-9]+[A-Z]*)\.md',
                     'cites': r'([Ss]ection|s\.) ?{n}([^0-9A-Za-z]|$)'},
        'reuse': 'none found: the Copyright Act, Cap. 252, excludes no legislation and gives the State copyright in '
                 'works made by or under the direction or control of the Government (s. 25(4)); private repository',
        'tool': 'tools/in_force_on.py',
    }

    files = {
        'corpus.json': (json.dumps(corpus, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
        'laws.csv': laws_csv,
        'data/amendments.csv': amend_csv,
        'data/issues.csv': issues_csv,
        'data/si-not-built.csv': not_built,
        'data/stats.json': (json.dumps(stats, indent=1, sort_keys=True) + '\n').encode('utf-8'),
        'data/source-sha256.tsv': ''.join(f"{l['dir']}/\t{l['sha256']}\n" for l in built).encode('utf-8'),
        'tools/in_force_on.py': (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes(),
    }
    for name, t in texts.items():
        files[name] = t.encode('utf-8')
    for name in BUILD_FILES:
        files[f'tools/build/{name}'] = (HERE / name).read_bytes()
    for name in TEMPLATES:
        files[f'tools/build/repo/{name}'] = (REPO_FILES / name).read_bytes()
    files['tools/build/repo/tools/in_force_on.py'] = (REPO_FILES / 'tools' / 'in_force_on.py').read_bytes()
    return publish_gate(files)
