"""Shared test setup: make src/ importable; XML and MIDI conversion helpers."""

import sys
from dataclasses import replace
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / 'src'))

IN_DIR = ROOT_DIR / 'in'

import mido  # noqa: E402

from gp2midi import MidiOptions, track_to_midi  # noqa: E402
from gpif import (  # noqa: E402
    TICKS_PER_BEAT, Bar, Beat, MasterBar, Note, Rhythm, Score, Staff, Tempo, Track, Voice,
)

TRACK = Track(id=0, name='Gtr', program=29, channel=0, is_tab=True, is_fretted=True,
              staves=[Staff(tuning=[40, 45, 50, 55, 59, 64])])


class ScriptedRandom:
    """
    Stands in for random.Random in track_to_midi(rng=...): randint returns
    the given values in order, so tests know each humanize value exactly.
    Fails if a value is outside randint's range or more are drawn than given.
    """

    def __init__(self, values: list[int]):
        self.values = list(values)

    def randint(self, a: int, b: int) -> int:
        assert self.values, 'more random values drawn than scripted'
        value = self.values.pop(0)
        assert a <= value <= b, f'scripted {value} outside randint({a}, {b})'
        return value


def gpif(body: str) -> ET.Element:
    """Wrap XML fragments in a <GPIF> root element and parse them."""
    return ET.fromstring(f'<GPIF>{body}</GPIF>')


@pytest.fixture
def in_dir() -> Path:
    return IN_DIR


def convert(
    tmp_path: Path,
    note_list: list[dict],
    dynamics: list[str | None] | None = None,
    graces: list[str | None] | None = None,
    chords: list[list[int]] | None = None,
    staff_of: list[int] | None = None,
    beat_fields: list[dict] | None = None,
    track: dict | None = None,
    rng: ScriptedRandom | None = None,
    **kwargs,
) -> list[tuple[int, mido.Message]]:
    """
    Run track_to_midi on one 4/4 bar with one quarter-note beat per note.

    Each dict in note_list gives Note fields (default: string 2, fret 7); dynamics gives
    each beat's dynamic (default MF); graces marks beats as grace beats
    ('before' / 'on'), which get a 32nd-note rhythm and take no bar time.
    chords groups notes into beats by index (e.g. [[0, 1]] plays notes 0 and
    1 together); dynamics and graces are then per beat. staff_of puts each
    beat on a staff (default all on staff 0); each staff's beats start at the
    bar start. beat_fields gives each beat more Beat fields (e.g.
    {'pick_stroke': 'up'} or {'brush': 'down'}). track replaces TRACK (default: TRACK, with its staff repeated
    for each staff used). kwargs become the MidiOptions fields (e.g.
    velocity, bend_range); humanize is off unless given. rng goes to
    track_to_midi (e.g. a ScriptedRandom). Returns [(abs_tick, msg), ...].
    """
    notes = {i: Note(**{'string': 2, 'fret': 7, **n}) for i, n in enumerate(note_list)}
    chords = chords or [[i] for i in notes]
    dynamics = dynamics or ['MF'] * len(chords)
    graces = graces or [None] * len(chords)
    beat_fields = beat_fields or [{}] * len(chords)
    beats = {i: Beat(rhythm_id=1 if graces[i] else 0, note_ids=chord,
                     dynamic=dynamics[i], grace=graces[i], **beat_fields[i])
             for i, chord in enumerate(chords)}
    staff_of = staff_of or [0] * len(chords)
    staff_ids = range(max(staff_of) + 1)
    track = track or replace(TRACK, staves=TRACK.staves * len(staff_ids))
    out = tmp_path / 'out.mid'
    # One bar and one voice per staff, with the same id as the staff
    score = Score(
        tracks=[track],
        master_bars=[MasterBar(bar_ids=list(staff_ids), numerator=4, denominator=4)],
        bars={staff: Bar(voice_ids=[staff]) for staff in staff_ids},
        voices={staff: Voice(beat_ids=[b for b in beats if staff_of[b] == staff])
                for staff in staff_ids},
        beats=beats,
        notes=notes,
        rhythms={0: Rhythm(beats=1.0, ticks=TICKS_PER_BEAT),
                 1: Rhythm(beats=0.125, ticks=TICKS_PER_BEAT // 8)},
        tempos=[Tempo(bar=0, position=0.0, bpm=120.0)],
    )
    options = MidiOptions(**{'humanize': False, **kwargs})
    track_to_midi(track, score, output_path=str(out), options=options, rng=rng)
    tick, result = 0, []
    for msg in mido.MidiFile(out).tracks[0]:
        tick += msg.time
        result.append((tick, msg))
    return result
