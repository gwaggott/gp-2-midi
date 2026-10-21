"""Tests for tracks with more than one staff in gp2midi.py."""

from dataclasses import replace

from conftest import TRACK, convert
from gp2midi import MidiOptions, string_channels
from gpif import TICKS_PER_BEAT, Staff

BEAT = TICKS_PER_BEAT
GRACE = BEAT // 8          # the 32nd-note rhythm conftest gives grace beats
GUITAR = Staff(tuning=[40, 45, 50, 55, 59, 64])
BASS = Staff(tuning=[28, 33, 38, 43])


def notes_played(msgs):
    """[(start, end, pitch, channel)] in start order."""
    open_notes, out = {}, []
    for t, m in msgs:
        if m.type == 'note_on':
            open_notes[(m.channel, m.note)] = t
        elif m.type == 'note_off':
            out.append((open_notes.pop((m.channel, m.note)), t, m.note, m.channel))
    return sorted(out)


def test_both_staves_play_with_their_own_tuning(tmp_path):
    # Staff 0 guitar D string fret 7 (A3); staff 1 bass open low string (E1)
    track = replace(TRACK, staves=[GUITAR, BASS])
    msgs = convert(tmp_path, [{'string': 2, 'fret': 7}, {'string': 0, 'fret': 0}],
                   staff_of=[0, 1], track=track)
    assert notes_played(msgs) == [(0, BEAT, 28, 0), (0, BEAT, 57, 0)]


def test_second_staff_alone_plays(tmp_path):
    # As in a real two-staff string track: the first staff is empty
    msgs = convert(tmp_path, [{'string': 2, 'fret': 7}], staff_of=[1])
    assert notes_played(msgs) == [(0, BEAT, 57, 0)]


def test_staves_play_in_parallel_from_the_bar_start(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 7}, {'fret': 9}],
                   staff_of=[0, 0, 1])
    assert notes_played(msgs) == [(0, BEAT, 55, 0), (0, BEAT, 59, 0), (BEAT, 2 * BEAT, 57, 0)]


def test_grace_note_does_not_cut_same_string_on_other_staff(tmp_path):
    # Staff 0: D string fret 7 for a beat. Staff 1: a quarter on another
    # string, then a before-beat grace on the D string just before beat 2.
    # Each staff has its own strings, so staff 0's note keeps its full length.
    msgs = convert(tmp_path,
                   [{'string': 2, 'fret': 7},
                    {'string': 5, 'fret': 0}, {'string': 2, 'fret': 9}, {'string': 5, 'fret': 0}],
                   graces=[None, None, 'before', None], staff_of=[0, 1, 1, 1])
    played = notes_played(msgs)
    assert (0, BEAT, 57, 0) in played                    # not cut to BEAT - GRACE
    assert (BEAT - GRACE, BEAT, 59, 0) in played


def test_slide_target_is_not_taken_from_other_staff(tmp_path):
    # A shift slide on staff 0 with nothing after it on its string; staff 1
    # has a note on the same string number at the slide's end. No glide.
    msgs = convert(tmp_path,
                   [{'string': 2, 'fret': 5, 'slide_out': 'shift'},
                    {'string': 2, 'fret': 0}, {'string': 2, 'fret': 9}],
                   staff_of=[0, 1, 1])
    assert all(m.pitch == 0 for _, m in msgs if m.type == 'pitchwheel')


def test_slide_target_on_own_staff_still_glides(tmp_path):
    msgs = convert(tmp_path,
                   [{'string': 2, 'fret': 0}, {'string': 2, 'fret': 9},
                    {'string': 2, 'fret': 5, 'slide_out': 'shift'}, {'string': 2, 'fret': 7}],
                   staff_of=[0, 0, 1, 1])
    assert any(m.pitch > 0 for _, m in msgs if m.type == 'pitchwheel')


def test_channel_per_string_off_for_multi_staff_tracks(tmp_path):
    on = MidiOptions(channel_per_string=True)
    assert string_channels(replace(TRACK, staves=[GUITAR, GUITAR]), on) is None
    msgs = convert(tmp_path, [{'string': 0, 'fret': 0}, {'string': 5, 'fret': 0}],
                   staff_of=[0, 1], channel_per_string=True)
    assert {m.channel for _, m in msgs if hasattr(m, 'channel')} == {0}
