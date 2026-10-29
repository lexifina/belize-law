"""Print a law of Belize, or one section of it, as this repository has it on a date.

    python tools/in_force_on.py 2026-10-01 cap/101            # the whole Criminal Code, Chapter 101
    python tools/in_force_on.py 2026-10-01 cap/101 12         # section 12
    python tools/in_force_on.py 2026-10-01 acts/2026/5 2      # section 2 of Act No. 5 of 2026, as enacted

Reads the `In-force:` trailer of each commit (the date the record gives it). The Chapters have one version, the
Revised Edition 2020 as at 2020-12-31, so a date before that has no version here, and a date after it still shows
the 2020 text: Acts of 2021 onwards are in acts/<year>/<number>/ as enacted and are not applied to the Chapters.
Standard library only.
"""
import subprocess
import sys


def git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def commit_on(day: str, path: str) -> tuple[str | None, str | None]:
    """The last commit on or before `day` that touched `path`, and the earliest date known for it."""
    fmt = '%H%x1f%(trailers:key=In-force,valueonly,separator=)'
    earliest = None
    for line in git('log', '--first-parent', f'--format={fmt}', 'main', '--', path).splitlines():
        h, _, inforce = line.partition('\x1f')
        d = inforce.strip()
        if not d:
            continue
        earliest = d
        if d <= day:
            return h, d
    return None, earliest


def main() -> None:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    day, law = sys.argv[1], sys.argv[2].strip('/')
    unit = sys.argv[3] if len(sys.argv) > 3 else None
    if unit and unit.endswith('.md'):
        unit = unit[:-3]
    path = f'{law}/{unit}.md' if unit else law
    h, earliest = commit_on(day, path)
    if not h:
        if earliest:
            sys.exit(f'{path}: no version on or before {day}; the record starts at {earliest} '
                     '(the Revised Edition 2020, or the Act as enacted; no earlier text is published)')
        sys.exit(f'{path}: not found')
    if unit:
        sys.stdout.write(git('show', f'{h}:{path}'))
        return
    try:
        names = [n for n in git('show', f'{h}:{law}/index.txt').splitlines() if n]
    except subprocess.CalledProcessError:
        # a folder of laws (cap/, acts/2026/): list what it holds on that date
        sys.stdout.write(git('ls-tree', '--name-only', h, f'{law}/'))
        return
    for n in names:
        sys.stdout.write(git('show', f'{h}:{law}/{n}') + '\n')


if __name__ == '__main__':
    main()
