"""Tests for hammer-on / pull-off handling in gp2midi.py."""

from dataclasses import replace

from conftest import convert
from gp2midi import DEFAULT_HOPO_CUT, MidiOptions, note_velocity
from gpif import TICKS_PER_BEAT, Note

PLAIN = Note()

# Hammer-on from fret 5 to 7 on the same string, then a picked note
ORIGIN = {'fret': 5, 'hopo_origin': True}
DEST = {'fret': 7, 'hopo_dest': True}


def note_ons(msgs):
    return [(t, m.note, m.velocity) for t, m in msgs if m.type == 'note_on']


def note_off_tick(msgs, pitch):
    return next(t for t, m in msgs if m.type == 'note_off' and m.note == pitch)

# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------

def test_hopo_dest_is_softer():
    assert note_velocity('MF', replace(PLAIN, hopo_dest=True)) == 80 - DEFAULT_HOPO_CUT
    assert note_velocity('MF', replace(PLAIN, hopo_dest=True), MidiOptions(hopo_cut=30)) == 50
    assert note_velocity('MF', replace(PLAIN, hopo_dest=True), MidiOptions(hopo_cut=0)) == 80


def test_hopo_cut_combines_with_accent_and_clamps():
    assert note_velocity('F', replace(PLAIN, accent='normal', hopo_dest=True)) == 96
    assert note_velocity('PPP', replace(PLAIN, hopo_dest=True), MidiOptions(hopo_cut=127)) == 1


def test_hopo_velocities_in_track(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST, {'fret': 9}], dynamics=['F', 'F', 'F'])
    assert [v for _, _, v in note_ons(msgs)] == [96, 96 - DEFAULT_HOPO_CUT, 96]


def test_hopo_cut_option(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST], dynamics=['F', 'F'], hopo_cut=0)
    assert [v for _, _, v in note_ons(msgs)] == [96, 96]


def test_fixed_velocity_ignores_hopo_cut(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST], velocity=100)
    assert [v for _, _, v in note_ons(msgs)] == [100, 100]

# ---------------------------------------------------------------------------
# Legato overlap
# ---------------------------------------------------------------------------

def test_no_overlap_by_default(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST])
    assert note_off_tick(msgs, 50 + 5) == TICKS_PER_BEAT


def test_overlap_extends_origin(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST], hopo_overlap=20)
    assert note_off_tick(msgs, 50 + 5) == TICKS_PER_BEAT + 20
    # The destination itself is unchanged
    assert note_off_tick(msgs, 50 + 7) == 2 * TICKS_PER_BEAT


def test_overlap_chain(tmp_path):
    # 5 → 7 → 5 (hammer then pull-off): each origin overlaps the next note
    msgs = convert(tmp_path, [ORIGIN, {**DEST, 'hopo_origin': True}, {'fret': 5, 'hopo_dest': True}],
                   hopo_overlap=20)
    offs = [(t, m.note) for t, m in msgs if m.type == 'note_off']
    assert (TICKS_PER_BEAT + 20, 55) in offs
    assert (2 * TICKS_PER_BEAT + 20, 57) in offs


def test_overlap_capped_at_destination_length(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, DEST], hopo_overlap=10_000)
    assert note_off_tick(msgs, 55) == 2 * TICKS_PER_BEAT


def test_no_overlap_without_origin_flag(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5}, DEST], hopo_overlap=20)
    assert note_off_tick(msgs, 55) == TICKS_PER_BEAT


def test_no_overlap_on_another_string(tmp_path):
    msgs = convert(tmp_path, [ORIGIN, {**DEST, 'string': 3}], hopo_overlap=20)
    assert note_off_tick(msgs, 55) == TICKS_PER_BEAT


def test_no_overlap_after_staccato_origin(tmp_path):
    # The origin was cut short, so there's no slur to make
    msgs = convert(tmp_path, [{**ORIGIN, 'staccato': True}, DEST], hopo_overlap=20)
    assert note_off_tick(msgs, 55) == TICKS_PER_BEAT // 2


def test_overlap_from_tied_origin(tmp_path):
    # Origin held over a tie, then hammered: the tied note's end is extended
    msgs = convert(tmp_path, [{'fret': 5}, {'fret': 5, 'is_tie_dest': True, 'hopo_origin': True}, DEST],
                   hopo_overlap=20)
    assert note_off_tick(msgs, 55) == 2 * TICKS_PER_BEAT + 20
