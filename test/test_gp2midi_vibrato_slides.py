"""Tests for vibrato and slides in gp2midi.py."""

import pytest

from dataclasses import replace

from conftest import convert
from gp2midi import (
    DEFAULT_HOPO_CUT,
    DEFAULT_SLIDE_DISTANCE,
    DEFAULT_SLIDE_TIME,
    MidiOptions,
    bend_value,
    note_pitch_curve,
    ramp,
)
from gpif import TICKS_PER_BEAT, Note

BASE = Note()
BEAT = TICKS_PER_BEAT


def curve(note: dict, duration: int = BEAT, bpm: float = 120,
          glide_to: int | None = None, **options):
    """note_pitch_curve's curve function; options are MidiOptions fields."""
    result = note_pitch_curve(replace(BASE, **note), duration, bpm, glide_to, MidiOptions(**options))
    return result[0] if result else None


def pitchwheel(msgs):
    return [(t, m.pitch) for t, m in msgs if m.type == 'pitchwheel']


def semis(value: float, bend_range: int = 12) -> int:
    return bend_value(value, bend_range)

# ---------------------------------------------------------------------------
# ramp / note_pitch_curve
# ---------------------------------------------------------------------------

def test_ramp():
    assert [ramp(t, 100, 100) for t in (0, 100, 150, 200, 300)] == [0, 0, 0.5, 1, 1]
    assert ramp(99, 100, 0) == 0 and ramp(100, 100, 0) == 1


def test_no_effect_returns_none():
    assert note_pitch_curve(BASE, BEAT, 120) is None


def test_vibrato_is_sharp_only_with_peak_depth():
    fn = curve({'vibrato': 'slight'})
    values = [fn(t) for t in range(BEAT + 1)]
    assert min(values) == pytest.approx(0, abs=1e-9)
    assert max(values) == pytest.approx(0.5, abs=1e-3)


def test_wide_vibrato_is_double():
    fn = curve({'vibrato': 'wide'})
    assert max(fn(t) for t in range(BEAT + 1)) == pytest.approx(1.0, abs=1e-3)


def test_vibrato_rate_follows_tempo():
    # 5.5 Hz: at 60 bpm one beat is a second → peaks 5.5 times per beat
    def peaks(bpm):
        fn = curve({'vibrato': 'slight'}, duration=BEAT, bpm=bpm)
        v = [fn(t) for t in range(BEAT)]
        return sum(1 for i in range(1, BEAT - 1) if v[i - 1] < v[i] >= v[i + 1])
    assert peaks(60) in (5, 6)
    assert peaks(120) in (2, 3)


def test_vibrato_sampling_step_shrinks_for_fast_cycles():
    _, _, step = note_pitch_curve(replace(BASE, vibrato='slight'), BEAT, 60)
    assert step < 20


def test_vibrato_options():
    assert curve({'vibrato': 'slight'}, vibrato_depth=0) is None
    assert curve({'vibrato': 'slight'}, vibrato_rate=0) is None
    fn = curve({'vibrato': 'slight'}, vibrato_depth=1.0)
    assert max(fn(t) for t in range(BEAT + 1)) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize('direction, sign', [('below', -1), ('above', 1)])
def test_slide_in(direction, sign):
    fn = curve({'slide_in': direction})
    assert fn(0) == sign * DEFAULT_SLIDE_DISTANCE
    assert fn(DEFAULT_SLIDE_TIME / 2) == pytest.approx(sign * DEFAULT_SLIDE_DISTANCE / 2)
    assert fn(DEFAULT_SLIDE_TIME) == 0
    assert fn(BEAT) == 0


@pytest.mark.parametrize('direction, sign', [('down', -1), ('up', 1)])
def test_slide_out(direction, sign):
    fn = curve({'slide_out': direction})
    assert fn(0) == 0
    assert fn(BEAT - DEFAULT_SLIDE_TIME) == 0
    assert fn(BEAT) == sign * DEFAULT_SLIDE_DISTANCE


@pytest.mark.parametrize('kind', ['shift', 'legato'])
def test_slide_to_next_glides_to_interval(kind):
    fn = curve({'slide_out': kind}, glide_to=-3)
    assert fn(BEAT - DEFAULT_SLIDE_TIME) == 0
    assert fn(BEAT) == -3


def test_slide_to_next_without_target_is_no_effect():
    assert curve({'slide_out': 'shift'}, glide_to=None) is None


def test_slide_time_capped_at_note_length():
    fn = curve({'slide_out': 'down'}, duration=60)
    assert fn(0) == 0 and fn(30) == pytest.approx(-DEFAULT_SLIDE_DISTANCE / 2)


def test_slide_options():
    assert curve({'slide_in': 'below'}, slide_time=0) is None
    assert curve({'slide_in': 'below'}, slide_distance=0) is None
    assert curve({'slide_in': 'below'}, slide_distance=2)(0) == -2


def test_effects_add_up():
    fn = curve({'bend': [(0.0, 2.0), (1.0, 2.0)], 'slide_out': 'down'})
    assert fn(0) == 2.0
    assert fn(BEAT) == 2.0 - DEFAULT_SLIDE_DISTANCE

# ---------------------------------------------------------------------------
# track_to_midi
# ---------------------------------------------------------------------------

def test_shift_slide_glides_into_next_note(tmp_path):
    # Fret 5 → 7 on the same string: glide +2 over the end, reset, next note picked
    msgs = convert(tmp_path, [{'fret': 5, 'slide_out': 'shift'}, {'fret': 7}], dynamics=['F', 'F'])
    pw = pitchwheel(msgs)
    assert pw[0][0] == BEAT - DEFAULT_SLIDE_TIME + 20       # first non-zero sample
    assert (BEAT - 1, semis(2)) in pw
    assert (BEAT, 0) in pw
    ons = [(t, m.note, m.velocity) for t, m in msgs if m.type == 'note_on']
    assert ons == [(0, 55, 96), (BEAT, 57, 96)]


def test_legato_slide_destination_is_softer(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, 'slide_out': 'legato'}, {'fret': 7}], dynamics=['F', 'F'])
    assert [m.velocity for _, m in msgs if m.type == 'note_on'] == [96, 96 - DEFAULT_HOPO_CUT]


def test_legato_slide_into_hammer_on_not_cut_twice(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, 'slide_out': 'legato'}, {'fret': 7, 'hopo_dest': True}],
                   dynamics=['F', 'F'])
    assert [m.velocity for _, m in msgs if m.type == 'note_on'] == [96, 96 - DEFAULT_HOPO_CUT]


def test_slide_down_to_next_note(tmp_path):
    msgs = convert(tmp_path, [{'fret': 7, 'slide_out': 'shift'}, {'fret': 2}])
    assert (BEAT - 1, semis(-5)) in pitchwheel(msgs)


def test_slide_needs_next_note_on_same_string(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, 'slide_out': 'shift'}, {'fret': 7, 'string': 3}])
    assert pitchwheel(msgs) == []


def test_slide_to_same_pitch_is_ignored(tmp_path):
    msgs = convert(tmp_path, [{'fret': 5, 'slide_out': 'shift'}, {'fret': 5}])
    assert pitchwheel(msgs) == []


def test_slide_in_set_before_note_on(tmp_path):
    msgs = convert(tmp_path, [{'slide_in': 'below'}])
    first_pw = next(i for i, (_, m) in enumerate(msgs) if m.type == 'pitchwheel')
    first_on = next(i for i, (_, m) in enumerate(msgs) if m.type == 'note_on')
    assert first_pw < first_on
    assert msgs[first_pw][1].pitch == semis(-DEFAULT_SLIDE_DISTANCE)


def test_vibrato_in_track(tmp_path):
    msgs = convert(tmp_path, [{'vibrato': 'slight'}, {}])
    pw = pitchwheel(msgs)
    assert max(p for _, p in pw) == pytest.approx(semis(0.5), abs=2)
    assert all(p >= 0 for _, p in pw)
    assert pw[-1] == (BEAT, 0)          # reset for the plain note


def test_vibrato_and_slides_off(tmp_path):
    notes = [{'vibrato': 'wide', 'slide_in': 'below', 'fret': 5, 'slide_out': 'legato'}, {'fret': 7}]
    msgs = convert(tmp_path, notes, dynamics=['F', 'F'], vibrato_depth=0, slide_time=0)
    assert pitchwheel(msgs) == []
    assert [m.velocity for _, m in msgs if m.type == 'note_on'] == [96, 96]
