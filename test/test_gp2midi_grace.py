"""Tests for grace notes in gp2midi.py."""

from dataclasses import replace

from conftest import TRACK, convert
from gp2midi import DEFAULT_GRACE_CUT, DEFAULT_HOPO_CUT, MidiOptions, note_velocity
from gpif import TICKS_PER_BEAT, Note, Staff

BEAT = TICKS_PER_BEAT
GRACE = BEAT // 8          # the 32nd-note rhythm conftest gives grace beats
PLAIN = Note()


def notes_played(msgs):
    """[(start, end, pitch, velocity)] in start order."""
    open_notes, out = {}, []
    for t, m in msgs:
        if m.type == 'note_on':
            open_notes[m.note] = (t, m.velocity)
        elif m.type == 'note_off':
            start, vel = open_notes.pop(m.note)
            out.append((start, t, m.note, vel))
    return sorted(out)


def test_grace_velocity():
    assert note_velocity('F', PLAIN, is_grace=True) == 96 - DEFAULT_GRACE_CUT
    assert note_velocity('F', PLAIN, MidiOptions(grace_cut=0), is_grace=True) == 96


def test_before_beat_grace_takes_no_bar_time(tmp_path):
    # Quarter (fret 5), grace (fret 4), quarter (fret 7), quarter (fret 9)
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 4}, {'fret': 7}, {'fret': 9}],
                   dynamics=['F'] * 4, graces=[None, 'before', None, None])
    assert notes_played(msgs) == [
        (0, BEAT - GRACE, 55, 96),                  # cut short: same string as the grace
        (BEAT - GRACE, BEAT, 54, 96 - DEFAULT_GRACE_CUT),
        (BEAT, 2 * BEAT, 57, 96),                   # main note on the beat
        (2 * BEAT, 3 * BEAT, 59, 96),               # rest of the bar unchanged
    ]


def test_grace_on_other_string_leaves_previous_note(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 4, 'string': 3}, {'fret': 7}],
                   graces=[None, 'before', None])
    assert notes_played(msgs)[0][:2] == (0, BEAT)


def test_on_beat_grace_delays_main_note(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 4}, {'fret': 7}, {'fret': 9}],
                   graces=[None, 'on', None, None])
    played = notes_played(msgs)
    assert played[1][:3] == (BEAT, BEAT + GRACE, 54)
    assert played[2][:3] == (BEAT + GRACE, 2 * BEAT, 57)     # later and shorter
    assert played[3][:3] == (2 * BEAT, 3 * BEAT, 59)


def test_before_beat_grace_at_song_start_plays_on_beat(tmp_path):
    msgs = convert(tmp_path, [{'fret': 4}, {'fret': 7}], graces=['before', None])
    played = notes_played(msgs)
    assert played[0][:2] == (0, GRACE)
    assert played[1][:2] == (GRACE, BEAT)


def test_grace_length_option(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 4}, {'fret': 7}],
                   graces=[None, 'before', None], grace_length=30)
    assert notes_played(msgs)[1][:2] == (BEAT - 30, BEAT)


def test_hammer_on_grace(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 5, 'hopo_origin': True}, {'fret': 7, 'hopo_dest': True}],
                   dynamics=['F'] * 3, graces=[None, 'before', None], hopo_overlap=20)
    played = notes_played(msgs)
    # Grace origin is held into the main note; main note is softer as a hammer-on
    assert played[1][:2] == (BEAT - GRACE, BEAT + 20)
    assert played[2][3] == 96 - DEFAULT_HOPO_CUT


def test_slide_grace_glides_into_main_note(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 5, 'slide_out': 'shift'}, {'fret': 7}],
                   graces=[None, 'before', None])
    pw = [(t, m.pitch) for t, m in msgs if m.type == 'pitchwheel']
    # Whole grace note is the glide: +2 semitones reached just before the beat
    assert pw[0][0] > BEAT - GRACE and (BEAT - 1, round(2 / 12 * 8192)) in pw
    assert (BEAT, 0) in pw


def test_shortened_note_bend_fits_new_length(tmp_path):
    # A full bend over the previous note completes before the grace note starts
    msgs = convert(tmp_path, [{'fret': 5, 'bend': [(0.0, 0.0), (1.0, 2.0)]}, {'fret': 4}, {'fret': 7}],
                   graces=[None, 'before', None])
    pw = [(t, m.pitch) for t, m in msgs if m.type == 'pitchwheel']
    assert (BEAT - GRACE - 1, round(2 / 12 * 8192)) in pw
    assert (BEAT - GRACE, 0) in pw


def test_drum_grace_does_not_cut_other_drums(tmp_path):
    # Drum notes have no real string: a flam mustn't shorten other drum hits
    drums = replace(TRACK, is_drum=True, staves=[Staff()])
    msgs = convert(tmp_path, [{'midi': 42}, {'midi': 38}, {'midi': 38}],
                   graces=[None, 'before', None], track=drums)
    assert notes_played(msgs)[0][:3] == (0, BEAT, 42)
