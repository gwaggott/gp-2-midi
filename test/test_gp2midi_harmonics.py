"""Tests for harmonics in gp2midi.py."""

from conftest import convert
from gp2midi import SEMI_HARMONIC_CUT, MidiOptions, note_velocity
from gpif import TICKS_PER_BEAT, Harmonic, Note

BEAT = TICKS_PER_BEAT
PLAIN = Note()


def harm(htype: str, hfret: float) -> dict:
    return {'harmonic': Harmonic(type=htype, fret=hfret)}


def note_ons(msgs):
    return [(t, m.note, m.velocity) for t, m in msgs if m.type == 'note_on']


def test_harmonic_velocity():
    assert note_velocity('F', PLAIN, harmonic='full') == 96          # default cut is 0
    assert note_velocity('F', PLAIN, MidiOptions(harmonic_cut=10), harmonic='full') == 86
    assert note_velocity('F', PLAIN, MidiOptions(harmonic_cut=10), harmonic='semi') == 86 - SEMI_HARMONIC_CUT


def test_artificial_harmonic_pitch(tmp_path):
    # D string fret 7 (57), artificial harmonic 7 frets above → +19
    msgs = convert(tmp_path, [{'fret': 7, **harm('artificial', 7)}], dynamics=['F'])
    assert note_ons(msgs) == [(0, 57 + 19, 96)]


def test_gp8_midi_value_is_overridden(tmp_path):
    # GP8 stores the fretted pitch in Midi; the harmonic must still apply
    msgs = convert(tmp_path, [{'fret': 7, 'midi': 57, **harm('artificial', 12)}])
    assert [n for _, n, _ in note_ons(msgs)] == [69]


def test_natural_harmonic_pitch(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, **harm('natural', 5)}])
    assert [n for _, n, _ in note_ons(msgs)] == [50 + 24]


def test_semi_harmonic_plays_both(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, **harm('semi', 12)}], dynamics=['F'])
    assert sorted(note_ons(msgs)) == [(0, 55, 96), (0, 67, 96 - SEMI_HARMONIC_CUT)]
    assert sorted(t for t, m in msgs if m.type == 'note_off') == [BEAT, BEAT]


def test_no_harmonics_option(tmp_path):
    msgs = convert(tmp_path, [{'fret': 7, **harm('artificial', 7)}, {'fret': 5, **harm('semi', 12)}],
                   harmonics=False)
    assert [n for _, n, _ in note_ons(msgs)] == [57, 55]


def test_harmonic_cut_option(tmp_path):
    msgs = convert(tmp_path, [{'fret': 7, **harm('artificial', 12)}], dynamics=['F'], harmonic_cut=20)
    assert note_ons(msgs)[0][2] == 76


def test_no_node_plays_fretted(tmp_path):
    msgs = convert(tmp_path, [{'fret': 7, **harm('artificial', 12.5)}])
    assert [n for _, n, _ in note_ons(msgs)] == [57]


def test_tied_harmonic_extends(tmp_path):
    h = harm('artificial', 12)
    msgs = convert(tmp_path, [{'fret': 7, **h}, {'fret': 7, 'is_tie_dest': True, **h}])
    assert [n for _, n, _ in note_ons(msgs)] == [69]
    assert [t for t, m in msgs if m.type == 'note_off'] == [2 * BEAT]


def test_tied_semi_harmonic_extends_both(tmp_path):
    h = harm('semi', 12)
    msgs = convert(tmp_path, [{'fret': 7, **h}, {'fret': 7, 'is_tie_dest': True, **h}])
    assert len(note_ons(msgs)) == 2
    assert [t for t, m in msgs if m.type == 'note_off'] == [2 * BEAT, 2 * BEAT]
