"""Tests for dynamics, accents, ghost notes and staccato in gp2midi.py."""

import pytest

from dataclasses import replace

from conftest import convert
from gp2midi import DYNAMIC_VELOCITY, note_velocity
from gpif import TICKS_PER_BEAT, Note

PLAIN = Note()

# ---------------------------------------------------------------------------
# note_velocity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('dynamic, expected', [
    ('PPP', 16), ('PP', 32), ('P', 48), ('MP', 64),
    ('MF', 80), ('F', 96), ('FF', 112), ('FFF', 127),
])
def test_dynamic_velocities(dynamic, expected):
    assert note_velocity(dynamic, PLAIN) == expected


def test_dynamic_velocities_increase():
    assert list(DYNAMIC_VELOCITY.values()) == sorted(DYNAMIC_VELOCITY.values())


@pytest.mark.parametrize('dynamic', [None, 'XYZ'])
def test_missing_or_unknown_dynamic_is_mf(dynamic):
    assert note_velocity(dynamic, PLAIN) == 80


def test_accents_add_velocity():
    assert note_velocity('MF', replace(PLAIN, accent='normal')) == 96
    assert note_velocity('MF', replace(PLAIN, accent='heavy')) == 112


def test_ghost_note_is_softer():
    assert note_velocity('MF', replace(PLAIN, ghost=True)) == 48


def test_velocity_clamped():
    assert note_velocity('FFF', replace(PLAIN, accent='heavy')) == 127
    assert note_velocity('PPP', replace(PLAIN, ghost=True)) == 1

# ---------------------------------------------------------------------------
# track_to_midi
# ---------------------------------------------------------------------------

def note_ons(msgs):
    return [(t, m.velocity) for t, m in msgs if m.type == 'note_on']


def note_offs(msgs):
    return [t for t, m in msgs if m.type == 'note_off']


def test_velocity_follows_dynamics_and_accents(tmp_path):
    msgs = convert(tmp_path,
                   [{}, {'accent': 'normal'}, {'ghost': True}, {}],
                   dynamics=['P', 'F', 'F', 'FFF'])
    assert [v for _, v in note_ons(msgs)] == [48, 112, 64, 127]


def test_fixed_velocity_overrides_score(tmp_path):
    msgs = convert(tmp_path, [{}, {'accent': 'heavy'}, {'ghost': True}],
                   dynamics=['PPP', 'FFF', 'F'], velocity=100)
    assert [v for _, v in note_ons(msgs)] == [100, 100, 100]


def test_staccato_halves_sounding_length(tmp_path):
    msgs = convert(tmp_path, [{'staccato': True}, {}])
    assert note_offs(msgs) == [TICKS_PER_BEAT // 2, 2 * TICKS_PER_BEAT]
    # The next note still starts on the beat
    assert [t for t, _ in note_ons(msgs)] == [0, TICKS_PER_BEAT]


def test_tie_extends_staccato_note_to_full_tied_length(tmp_path):
    # The tie continuation sets the end: the origin's staccato is overridden
    msgs = convert(tmp_path, [{'staccato': True}, {'is_tie_dest': True}])
    assert note_offs(msgs) == [2 * TICKS_PER_BEAT]


def test_note_dynamic_overrides_beat_dynamic(tmp_path):
    # GP3-5 notes carry their own dynamic; a chord can mix them
    msgs = convert(tmp_path, [{'string': 0, 'dynamic': 'PP'}, {'string': 1}],
                   chords=[[0, 1]], dynamics=['F'])
    assert sorted(m.velocity for _, m in msgs if m.type == 'note_on') == [
        DYNAMIC_VELOCITY['PP'], DYNAMIC_VELOCITY['F']]
