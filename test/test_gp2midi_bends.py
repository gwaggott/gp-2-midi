"""Tests for pitch-bend output in gp2midi.py."""

import mido
import pytest

from gp2midi import (
    BEND_STEP_TICKS,
    SK_BEND,
    bend_curve_at,
    bend_events,
    bend_range_rpn,
    bend_value,
    drop_redundant_bends,
)
from conftest import convert
from gpif import TICKS_PER_BEAT

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('semitones, bend_range, expected', [
    (0, 12, 0),
    (2, 12, 1365),
    (12, 12, 8191),      # top of range clamps to the max value
    (-12, 12, -8192),
    (5, 2, 8191),        # wider than the range: clamped
    (1, 2, 4096),
])
def test_bend_value(semitones, bend_range, expected):
    assert bend_value(semitones, bend_range) == expected


def test_bend_curve_at_interpolates_and_holds():
    points = [(0.0, 0.0), (0.5, 2.0), (1.0, 2.0)]
    assert bend_curve_at(points, 0.0) == 0.0
    assert bend_curve_at(points, 0.25) == 1.0
    assert bend_curve_at(points, 0.75) == 2.0
    assert bend_curve_at(points, 1.0) == 2.0


def test_bend_curve_at_before_first_point_and_jumps():
    assert bend_curve_at([(0.5, 1.0), (1.0, 2.0)], 0.2) == 1.0
    # Two points at the same offset: a jump, the later value applies from there
    assert bend_curve_at([(0.0, 0.0), (0.5, 0.0), (0.5, 2.0), (1.0, 2.0)], 0.5) == 2.0


def test_bend_events_ramp():
    events = bend_events(1000, TICKS_PER_BEAT, [(0.0, 0.0), (1.0, 2.0)], 12, channel=3)
    ticks = [t for t, _, _ in events]
    values = [m.pitch for _, _, m in events]
    assert ticks[0] == 1000
    assert ticks[-1] == 1000 + TICKS_PER_BEAT - 1     # stops before the note's end tick
    assert ticks[1] - ticks[0] == BEND_STEP_TICKS
    assert values[0] == 0
    assert values[-1] == bend_value(2.0, 12)          # final value reached
    assert values == sorted(values)
    assert all(sk == SK_BEND and m.channel == 3 for _, sk, m in events)


def test_bend_events_breakpoint_is_sampled_exactly():
    # Breakpoint at 30% of 480 = tick 144, which is not on the 20-tick grid
    events = bend_events(0, 480, [(0.0, 0.0), (0.3, 2.0), (1.0, 2.0)], 12, channel=0)
    assert (144, bend_value(2.0, 12)) in [(t, m.pitch) for t, _, m in events]


def test_drop_redundant_bends():
    def pw(tick, value):
        return (tick, SK_BEND, mido.Message('pitchwheel', pitch=value))
    note = (0, 3, mido.Message('note_on', note=60))
    events = [pw(0, 0), note, pw(10, 100), pw(20, 100), pw(30, 0), pw(40, 0)]
    kept = drop_redundant_bends(events)
    assert [(t, m.type, getattr(m, 'pitch', None)) for t, _, m in kept] == [
        (0, 'note_on', None), (10, 'pitchwheel', 100), (30, 'pitchwheel', 0),
    ]


def test_bend_range_rpn():
    msgs = bend_range_rpn(channel=4, semitones=12)
    assert [(m.control, m.value) for m in msgs] == [
        (101, 0), (100, 0), (6, 12), (38, 0), (101, 127), (100, 127),
    ]
    assert all(m.channel == 4 for m in msgs)

# ---------------------------------------------------------------------------
# track_to_midi end-to-end on a tiny score
# ---------------------------------------------------------------------------

FULL_BEND = [(0.0, 0.0), (0.5, 2.0), (1.0, 2.0)]


def test_unbent_track_has_no_bend_messages(tmp_path):
    msgs = convert(tmp_path, [{}, {}])
    assert not [m for _, m in msgs if m.type in ('pitchwheel', 'control_change')]


def test_bent_note_then_unbent_note_resets(tmp_path):
    msgs = convert(tmp_path, [{'bend': FULL_BEND}, {}])
    assert [m.value for _, m in msgs if m.type == 'control_change'][2] == 12   # RPN data entry
    pw = [(t, m.pitch) for t, m in msgs if m.type == 'pitchwheel']
    assert max(p for _, p in pw) == bend_value(2.0, 12)
    # The second note starts at 480 with the bend reset before its note_on
    second_on = next(i for i, (t, m) in enumerate(msgs) if m.type == 'note_on' and t == TICKS_PER_BEAT)
    assert msgs[second_on - 1][1].type == 'pitchwheel' and msgs[second_on - 1][1].pitch == 0


def test_bend_happens_before_note_on(tmp_path):
    # Pre-bent note: the origin value must be set before the note sounds
    msgs = convert(tmp_path, [{'bend': [(0.0, 2.0), (1.0, 0.0)]}])
    first_pw = next(i for i, (_, m) in enumerate(msgs) if m.type == 'pitchwheel')
    first_on = next(i for i, (_, m) in enumerate(msgs) if m.type == 'note_on')
    assert first_pw < first_on
    assert msgs[first_pw][1].pitch == bend_value(2.0, 12)


def test_tied_note_holds_bend(tmp_path):
    msgs = convert(tmp_path, [{'bend': FULL_BEND}, {'is_tie_dest': True}])
    pw = [(t, m.pitch) for t, m in msgs if m.type == 'pitchwheel']
    # Held through the tied note: no reset until the end of the track
    assert all(p == bend_value(2.0, 12) for t, p in pw if TICKS_PER_BEAT // 2 <= t < 2 * TICKS_PER_BEAT)
    assert pw[-1] == (2 * TICKS_PER_BEAT, 0)
    assert len([m for _, m in msgs if m.type == 'note_on']) == 1


def test_track_ends_unbent(tmp_path):
    msgs = convert(tmp_path, [{'bend': FULL_BEND}])
    assert [m for _, m in msgs if m.type == 'pitchwheel'][-1].pitch == 0
