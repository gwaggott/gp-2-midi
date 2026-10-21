"""Tests for palm muting and dead notes in gp2midi.py."""

import pytest

from dataclasses import replace

from conftest import convert
from gp2midi import (
    DEFAULT_DEAD_NOTE_CUT,
    DEFAULT_DEAD_NOTE_LENGTH,
    DEFAULT_PALM_MUTE_CUT,
    MidiOptions,
    note_velocity,
    palm_mute_chords,
    sounding_ticks,
)
from gpif import TICKS_PER_BEAT, Note

PLAIN = Note()
PALM = replace(PLAIN, palm_muted=True)
DEAD = replace(PLAIN, dead=True)


def note_ons(msgs):
    return [(t, m.velocity) for t, m in msgs if m.type == 'note_on']


def note_offs(msgs):
    return [t for t, m in msgs if m.type == 'note_off']

# ---------------------------------------------------------------------------
# sounding_ticks
# ---------------------------------------------------------------------------

def test_plain_note_sounds_full_length():
    assert sounding_ticks(480, PLAIN) == 480


def test_palm_mute_length():
    assert sounding_ticks(480, PALM) == 240
    assert sounding_ticks(480, PALM, MidiOptions(palm_mute_length=0.25)) == 120
    assert sounding_ticks(480, PALM, MidiOptions(palm_mute_length=1.0)) == 480


def test_dead_note_length_is_fixed_ticks():
    assert sounding_ticks(480, DEAD) == DEFAULT_DEAD_NOTE_LENGTH
    assert sounding_ticks(1920, DEAD) == DEFAULT_DEAD_NOTE_LENGTH
    assert sounding_ticks(480, DEAD, MidiOptions(dead_note_length=60)) == 60


def test_dead_note_never_longer_than_written():
    assert sounding_ticks(20, DEAD) == 20


@pytest.mark.parametrize('note, expected', [
    (replace(PALM, staccato=True), 240),                    # both halve: no double cut
    (replace(PALM, dead=True), DEFAULT_DEAD_NOTE_LENGTH),   # shortest wins
])
def test_shortest_shortening_wins(note, expected):
    assert sounding_ticks(480, note) == expected


def test_sounding_at_least_one_tick():
    assert sounding_ticks(480, PALM, MidiOptions(palm_mute_length=0.0)) == 1

# ---------------------------------------------------------------------------
# note_velocity
# ---------------------------------------------------------------------------

def test_palm_mute_and_dead_velocity_cuts():
    assert note_velocity('F', PALM) == 96 - DEFAULT_PALM_MUTE_CUT
    assert note_velocity('F', DEAD) == 96 - DEFAULT_DEAD_NOTE_CUT
    assert note_velocity('F', PALM, MidiOptions(palm_mute_cut=0)) == 96
    assert note_velocity('F', DEAD, MidiOptions(dead_note_cut=40)) == 56


def test_cuts_stack_and_clamp():
    assert note_velocity('F', replace(PALM, dead=True, hopo_dest=True)) == 96 - 8 - 16 - 16
    assert note_velocity('PPP', DEAD, MidiOptions(dead_note_cut=127)) == 1

# ---------------------------------------------------------------------------
# track_to_midi
# ---------------------------------------------------------------------------

def test_palm_muted_and_dead_notes_in_track(tmp_path):
    msgs = convert(tmp_path, [{'palm_muted': True}, {'dead': True}, {}],
                   dynamics=['F', 'F', 'F'])
    assert note_ons(msgs) == [(0, 88), (TICKS_PER_BEAT, 80), (2 * TICKS_PER_BEAT, 96)]
    assert note_offs(msgs) == [TICKS_PER_BEAT // 2, TICKS_PER_BEAT + 30, 3 * TICKS_PER_BEAT]


def test_options_pass_through(tmp_path):
    msgs = convert(tmp_path, [{'palm_muted': True}, {'dead': True}], dynamics=['F', 'F'],
                   palm_mute_length=1.0, palm_mute_cut=0, dead_note_length=120, dead_note_cut=0)
    assert note_ons(msgs) == [(0, 96), (TICKS_PER_BEAT, 96)]
    assert note_offs(msgs) == [TICKS_PER_BEAT, TICKS_PER_BEAT + 120]


def test_fixed_velocity_ignores_mute_cuts(tmp_path):
    msgs = convert(tmp_path, [{'palm_muted': True}, {'dead': True}], velocity=100)
    assert [v for _, v in note_ons(msgs)] == [100, 100]


def test_tie_extends_palm_muted_note(tmp_path):
    # As with staccato, a tie continuation sets the end
    msgs = convert(tmp_path, [{'palm_muted': True}, {'is_tie_dest': True}])
    assert note_offs(msgs) == [2 * TICKS_PER_BEAT]


def test_no_hopo_overlap_after_palm_muted_origin(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, 'hopo_origin': True, 'palm_muted': True},
                              {'fret': 7, 'hopo_dest': True}], hopo_overlap=20)
    assert note_offs(msgs)[0] == TICKS_PER_BEAT // 2

# ---------------------------------------------------------------------------
# palm_mute_chords (--palm-mute-chords, on by default)
# ---------------------------------------------------------------------------

def occ(tick, note, staff=0):
    return {'tick': tick, 'staff': staff, 'note': note}


def test_palm_mute_chords_marks_the_rest_of_the_onset():
    occurrences = [occ(0, PALM), occ(0, PLAIN), {'tempo': (480, 120)}, occ(480, PLAIN), occ(480, PLAIN)]
    assert palm_mute_chords(occurrences) == {1}


def test_palm_mute_chords_per_staff():
    assert palm_mute_chords([occ(0, PALM, staff=0), occ(0, PLAIN, staff=1)]) == set()


def test_palm_mute_chords_skips_ties_and_dead_notes():
    tied = replace(PLAIN, is_tie_dest=True)
    assert palm_mute_chords([occ(0, PALM), occ(0, tied), occ(0, DEAD)]) == set()
    # A tied palm-muted continuation doesn't mute the notes struck with it
    assert palm_mute_chords([occ(0, replace(PALM, is_tie_dest=True)), occ(0, PLAIN)]) == set()


def test_chord_with_one_muted_note_is_muted_in_track(tmp_path):
    # A power chord where the tab marks only the A-string note
    msgs = convert(tmp_path, [{'string': 0}, {'string': 1, 'palm_muted': True}], chords=[[0, 1]],
                   dynamics=['F'])
    assert note_ons(msgs) == [(0, 96 - DEFAULT_PALM_MUTE_CUT)] * 2
    assert note_offs(msgs) == [TICKS_PER_BEAT // 2] * 2


def test_no_palm_mute_chords_keeps_marks_per_note(tmp_path):
    msgs = convert(tmp_path, [{'string': 0}, {'string': 1, 'palm_muted': True}], chords=[[0, 1]],
                   dynamics=['F'], palm_mute_chords=False)
    assert sorted(note_ons(msgs)) == [(0, 96 - DEFAULT_PALM_MUTE_CUT), (0, 96)]
    assert sorted(note_offs(msgs)) == [TICKS_PER_BEAT // 2, TICKS_PER_BEAT]
