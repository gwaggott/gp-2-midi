#!/usr/bin/env python3
"""
List the fretted-instrument tracks of Guitar Pro files, with string count
and tuning.

Usage:
    python gpinfo.py                       # every Guitar Pro file in in/ (.gp, .gpx, .gpif, .gp3/4/5)
    python gpinfo.py song.gp other_dir/    # given files and directories
    python gpinfo.py --json                # machine-readable output
"""

import argparse
import json
import sys
from pathlib import Path

from gpif import Track, load_score, pitch_name, tuning_label

GP_SUFFIXES = ('.gp', '.gpx', '.gpif', '.gp3', '.gp4', '.gp5')


def track_info(track: Track) -> dict:
    tuning = track.tuning
    return {
        'id':           track.id,
        'name':         track.name,
        'instrument':   track.instrument,
        'strings':      len(tuning),
        'tuning':       tuning,
        'tuning_notes': [pitch_name(p) for p in tuning],
        'tuning_name':  tuning_label(tuning, track.instrument),
        'capo':         track.capo,
    }


def file_info(path: Path) -> dict:
    score = load_score(path)
    return {
        'file':   str(path),
        'title':  score.info.title,
        'artist': score.info.artist,
        'tracks': [track_info(t) for t in score.tracks if t.is_fretted],
    }


def find_files(paths: list[str]) -> list[Path]:
    files = []
    for arg in paths:
        p = Path(arg)
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in GP_SUFFIXES)
        else:
            files.append(p)
    return files


def print_info(info: dict) -> None:
    heading = ' - '.join(x for x in (info['artist'], info['title']) if x)
    print(info['file'] + (f'  ({heading})' if heading else ''))
    if not info['tracks']:
        print('  (no fretted tracks)\n')
        return

    rows = [('#', 'Track', 'Instrument', 'Strings', 'Tuning')]
    for t in info['tracks']:
        tuning = ' '.join(t['tuning_notes'])
        extras = [x for x in (t['tuning_name'], f"capo {t['capo']}" if t['capo'] else None) if x]
        if extras:
            tuning += f"  ({', '.join(extras)})"
        rows.append((str(t['id']), t['name'], t['instrument'] or '-', str(t['strings']), tuning))

    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
    for row in rows:
        cells = [cell.ljust(w) for cell, w in zip(row, widths)] + [row[-1]]
        print('  ' + '  '.join(cells))
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description='List fretted-instrument tracks of Guitar Pro files with string count and tuning.')
    parser.add_argument('paths', nargs='*', default=['in'],
                        help='Guitar Pro files or directories (default: in/)')
    parser.add_argument('--json', action='store_true', help='Output JSON')
    args = parser.parse_args()

    results = []
    failed = False
    for path in find_files(args.paths):
        try:
            info = file_info(path)
        except Exception as exc:  # report and carry on with the other files
            print(f'{path}: error: {exc}', file=sys.stderr)
            failed = True
            continue
        if args.json:
            results.append(info)
        else:
            print_info(info)

    if args.json:
        json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
        print()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
