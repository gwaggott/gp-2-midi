"""Humanize: seeded random generator, velocity variation, pick direction and strum spread."""

from dataclasses import replace

import pytest

from conftest import TRACK, ScriptedRandom, convert
from gp2midi import (
    ACCENT_BOOST, GHOST_CUT, MidiOptions, beat_stroke, ms_to_ticks, picked_onsets,
    stroke_directions,
    strum_delays, track_rng,
)
from gpif import TICKS_PER_BEAT, Beat, Note


def draws(rng, n=5):
    return [rng.randint(-100, 100) for _ in range(n)]


def test_humanize_on_by_default():
    assert MidiOptions().humanize is True


def test_track_rng_same_seed_same_values():
    assert draws(track_rng(TRACK, MidiOptions(seed=1))) == draws(track_rng(TRACK, MidiOptions(seed=1)))


def test_track_rng_differs_by_seed_and_track():
    base = draws(track_rng(TRACK))
    assert draws(track_rng(TRACK, MidiOptions(seed=1))) != base
    assert draws(track_rng(replace(TRACK, id=1))) != base


def test_scripted_random_returns_values_in_order():
    rng = ScriptedRandom([3, -5])
    assert [rng.randint(-5, 5), rng.randint(-5, 5)] == [3, -5]


def test_scripted_random_rejects_out_of_range_and_extra_draws():
    with pytest.raises(AssertionError):
        ScriptedRandom([6]).randint(-5, 5)
    with pytest.raises(AssertionError):
        ScriptedRandom([]).randint(-5, 5)


# track_to_midi

CHORD = [{'string': 0, 'fret': 3}, {'string': 1, 'fret': 2}, {'string': 2, 'fret': 0}]


def test_humanize_seeded_runs_identical(tmp_path):
    first = convert(tmp_path, CHORD, chords=[[0, 1, 2]], humanize=True, seed=7)
    second = convert(tmp_path, CHORD, chords=[[0, 1, 2]], humanize=True, seed=7)
    assert first == second


def velocities(events):
    """note_on velocities in order."""
    return [msg.velocity for _, msg in events if msg.type == 'note_on']


def humanized(tmp_path, note_list, offsets, **kwargs):
    """
    convert with humanize on and the given scripted random offsets; no strum
    spread unless strum_time is given.
    """
    kwargs = {'strum_time': 0, **kwargs}
    return convert(tmp_path, note_list, humanize=True, rng=ScriptedRandom(offsets), **kwargs)


# Velocity randomisation

def test_chord_notes_share_offset(tmp_path):
    events = humanized(tmp_path, CHORD, [3], chords=[[0, 1, 2]])
    assert velocities(events) == [83, 83, 83]


def test_offset_per_onset(tmp_path):
    notes = CHORD + [{'string': 3, 'fret': 2}]
    events = humanized(tmp_path, notes, [3, -5], chords=[[0, 1], [2, 3]])
    assert velocities(events) == [83, 83, 75, 75]


def test_offset_shared_across_staves(tmp_path):
    events = humanized(tmp_path, CHORD[:2], [4], staff_of=[0, 1])
    assert velocities(events) == [84, 84]


def test_accent_and_ghost_apply_on_top(tmp_path):
    notes = [{'string': 0, 'fret': 3, 'accent': 'normal'},
             {'string': 1, 'fret': 2, 'ghost': True},
             {'string': 2, 'fret': 0}]
    events = humanized(tmp_path, notes, [3], chords=[[0, 1, 2]])
    assert velocities(events) == [83 + ACCENT_BOOST['normal'], 83 - GHOST_CUT, 83]


def test_tied_continuation_draws_nothing(tmp_path):
    notes = [{'fret': 5}, {'fret': 5, 'is_tie_dest': True}, {'fret': 7}]
    # ScriptedRandom fails if a third value is drawn
    events = humanized(tmp_path, notes, [2, -2])
    assert velocities(events) == [82, 78]


def test_offset_clamped(tmp_path):
    notes = [{'fret': 5}, {'fret': 7, 'ghost': True}]
    events = humanized(tmp_path, notes, [5, -5], dynamics=['FFF', 'PPP'])
    assert velocities(events) == [127, 1]


@pytest.mark.parametrize('options', [
    {'velocity_spread': 0},
    {'velocity': 100},
])
def test_no_draws_when_off(tmp_path, options):
    # An empty script fails on any draw
    on = humanized(tmp_path, CHORD, [], chords=[[0, 1, 2]], **options)
    off = convert(tmp_path, CHORD, chords=[[0, 1, 2]], **options)
    assert on == off


def test_no_draws_without_humanize(tmp_path):
    events = convert(tmp_path, CHORD, chords=[[0, 1, 2]], humanize=False, rng=ScriptedRandom([]))
    assert velocities(events) == [80, 80, 80]


def test_seeded_offsets_within_spread(tmp_path):
    notes = [{'fret': f} for f in range(8)]
    first = velocities(convert(tmp_path, notes, humanize=True, seed=1))
    assert first == velocities(convert(tmp_path, notes, humanize=True, seed=1))
    assert first != velocities(convert(tmp_path, notes, humanize=True, seed=2))
    assert all(75 <= v <= 85 for v in first)


# Pick direction

Q, E8, E16 = TICKS_PER_BEAT, TICKS_PER_BEAT // 2, TICKS_PER_BEAT // 4  # quarter, eighth, 16th
BAR = 4 * Q


def run(ticks, step=0, scored=None, bar_starts=None):
    """stroke_directions on onsets at the given ticks (or n onsets step apart)."""
    if isinstance(ticks, int):
        ticks = [i * step for i in range(ticks)]
    scored = scored or {}
    onsets = {t: scored.get(t) for t in ticks}
    return [d for _, d in sorted(stroke_directions(onsets, bar_starts).items())]


def test_eighths_alternate():
    assert run(4, E8) == ['down', 'up', 'down', 'up']


def test_sixteenths_alternate():
    assert run(8, E16) == ['down', 'up', 'down', 'up'] * 2


def test_quarters_all_down():
    assert run(3, Q) == ['down', 'down', 'down']


def test_offbeat_eighth_is_up_after_a_rest():
    # A riff of offbeat eighths: ...3.3 up, (rest), 4.3 up, next bar 1.1 down
    assert run([2 * Q + E8, 3 * Q + E8, BAR], bar_starts=[0, BAR]) == ['up', 'up', 'down']


def test_offbeat_eighths_only_all_up():
    assert run([E8, Q + E8, 2 * Q + E8]) == ['up', 'up', 'up']


def test_gallop_uses_sixteenth_grid():
    # Eighth + two sixteenths: 1 . (and) a -> down, down, up
    assert run([0, E8, E8 + E16]) == ['down', 'down', 'up']


def test_sixteenth_grid_only_in_its_beat():
    # Beat 1: 1 e (16th grid); beat 2: 2 and (8th grid)
    assert run([0, E16, Q, Q + E8]) == ['down', 'up', 'down', 'up']


def test_dotted_rhythm_on_sixteenth_grid():
    # Beat 2: the 'e' and the 'a' are both upstrokes
    assert run([0, E8, Q + E16, Q + 3 * E16]) == ['down', 'up', 'up', 'up']


def test_beats_counted_from_bar_start():
    # After a 7/8 bar the next bar starts off the quarter-note grid
    bar_78 = 7 * E8
    ticks = [bar_78, bar_78 + E8]
    assert run(ticks, bar_starts=[0, bar_78]) == ['down', 'up']
    assert run(ticks) == ['up', 'down']        # counted from 0 instead


def test_eighth_triplets_alternate_off_grid():
    assert run(6, Q // 3) == ['down', 'up', 'down', 'down', 'up', 'down']


def test_off_grid_after_long_gap_is_down():
    # A 32nd-note offset more than an eighth after the previous onset
    assert run([0, Q + E16 // 2]) == ['down', 'down']


def test_scored_stroke_wins():
    assert run(3, E8, scored={0: 'up'}) == ['up', 'up', 'down']
    assert run(3, E8, scored={E8: 'down'}) == ['down', 'down', 'down']


def test_scored_stroke_sets_previous_for_off_grid():
    assert run([0, Q // 3], scored={0: 'up'}) == ['up', 'down']


def test_no_onsets():
    assert stroke_directions({}) == {}


def occurrence(tick, stroke=None, grace=False, **note):
    return {'tick': tick, 'note': Note(**note), 'grace': grace,
            'stroke': stroke, 'stroke_kind': 'pick'}


def test_picked_onsets_skips_unpicked_notes():
    occurrences = [
        {'tempo': (0, 120.0)},
        occurrence(0),
        occurrence(E8, hopo_dest=True),
        occurrence(2 * E8, is_tie_dest=True),
        occurrence(3 * E8 - 60, grace=True),
        occurrence(3 * E8),
        occurrence(4 * E8),          # legato-slide destination (index 6)
    ]
    assert picked_onsets(occurrences, unpicked={6}) == {0: None, 3 * E8: None}


def test_picked_onsets_marked_stroke_wins_at_a_tick():
    occurrences = [occurrence(0), occurrence(0, stroke='up'), occurrence(0, stroke='down')]
    assert picked_onsets(occurrences) == {0: 'up'}


def test_hammer_on_does_not_flip_direction():
    # Picked eighths with a hammer-on between: down, (hammer-on), up
    occurrences = [occurrence(0), occurrence(E16, hopo_dest=True), occurrence(E8)]
    assert stroke_directions(picked_onsets(occurrences)) == {0: 'down', E8: 'up'}


# Strum spread

# 12.5 ms per string at convert's 120 BPM = 12 ticks
STRUM = {'humanize': True, 'velocity_spread': 0, 'strum_time': 12.5}


def strum_occ(string, tick=0, staff=0, bpm=120.0, kind='pick', **note):
    return {'tick': tick, 'staff': staff, 'bpm': bpm, 'grace': False,
            'stroke': None, 'stroke_kind': kind, 'note': Note(string=string, **note)}


def test_ms_to_ticks():
    assert ms_to_ticks(12.5, 120.0) == 12
    assert ms_to_ticks(12.5, 60.0) == 6


def delays(occurrences, direction='down', **options):
    return strum_delays(occurrences, {0: direction}, options=MidiOptions(**{'strum_time': 12.5, **options}))


def test_strum_delays_down_and_up():
    chord = [strum_occ(0), strum_occ(1), strum_occ(2)]
    assert delays(chord, 'down') == {1: 12, 2: 24}
    assert delays(chord, 'up') == {0: 24, 1: 12}


def test_strum_delays_count_skipped_strings():
    assert delays([strum_occ(1), strum_occ(4)]) == {1: 36}


def test_strum_delays_follow_tempo():
    assert delays([strum_occ(0, bpm=60.0), strum_occ(1, bpm=60.0)]) == {1: 6}


def test_strum_delays_per_staff():
    assert delays([strum_occ(0), strum_occ(2, staff=1), strum_occ(3, staff=1)]) == {2: 12}


def test_strum_delays_skip_unpicked_and_undirected():
    chord = [strum_occ(0), strum_occ(1, hopo_dest=True), strum_occ(2, is_tie_dest=True),
             strum_occ(3), strum_occ(4, tick=E8)]
    # The first string is the lowest struck one; E8 has no direction
    assert delays(chord) == {3: 36}
    assert strum_delays(chord, {0: 'down'}, unpicked={3}, options=MidiOptions(strum_time=12.5)) == {}


def test_strum_delays_off():
    assert delays([strum_occ(0), strum_occ(1)], strum_time=0) == {}


def note_ons(events):
    return [(t, msg.note, msg.channel) for t, msg in events if msg.type == 'note_on']


def note_offs(events):
    return [(t, msg.note) for t, msg in events if msg.type == 'note_off']


def pitchwheels(events):
    return [(t, msg.channel, msg.pitch) for t, msg in events if msg.type == 'pitchwheel']


def test_downstroke_spreads_low_to_high_and_ends_together(tmp_path):
    events = convert(tmp_path, CHORD, chords=[[0, 1, 2]], **STRUM)
    assert note_ons(events) == [(0, 43, 0), (12, 47, 0), (24, 50, 0)]
    assert {t for t, _ in note_offs(events)} == {480}


def test_upstroke_spreads_high_to_low(tmp_path):
    events = convert(tmp_path, CHORD, chords=[[0, 1, 2]], beat_fields=[{'pick_stroke': 'up'}], **STRUM)
    assert note_ons(events) == [(0, 50, 0), (12, 47, 0), (24, 43, 0)]


def test_single_notes_not_delayed(tmp_path):
    events = convert(tmp_path, CHORD, **STRUM)
    assert [t for t, _, _ in note_ons(events)] == [0, 480, 960]


def test_delay_capped_below_sounding_length(tmp_path):
    # Dead notes sound 30 ticks; five strings away would be 60
    notes = [{'string': 0, 'fret': 0, 'dead': True}, {'string': 5, 'fret': 0, 'dead': True}]
    events = convert(tmp_path, notes, chords=[[0, 1]], **STRUM)
    assert note_ons(events) == [(0, 40, 0), (29, 64, 0)]
    assert note_offs(events) == [(30, 40), (30, 64)]


def test_strum_time_zero_unchanged(tmp_path):
    on = convert(tmp_path, CHORD, chords=[[0, 1, 2]], **{**STRUM, 'strum_time': 0})
    off = convert(tmp_path, CHORD, chords=[[0, 1, 2]])
    assert on == off


BENT_CHORD = [{'string': 0, 'fret': 3}, {'string': 1, 'fret': 2},
              {'string': 2, 'fret': 7, 'bend': [(0.0, 0.0), (0.5, 2.0), (1.0, 2.0)]}]


def test_pitch_events_stay_on_shared_channel(tmp_path):
    strummed = convert(tmp_path, BENT_CHORD, chords=[[0, 1, 2]], **STRUM)
    plain = convert(tmp_path, BENT_CHORD, chords=[[0, 1, 2]])
    assert pitchwheels(strummed) == pitchwheels(plain)


def test_pitch_events_move_with_note_per_string(tmp_path):
    events = convert(tmp_path, BENT_CHORD, chords=[[0, 1, 2]], channel_per_string=True, **STRUM)
    # String 2 (GPIF) is the 4th string from the top: channel 3
    assert (24, 57, 3) in note_ons(events)
    plain = convert(tmp_path, BENT_CHORD, chords=[[0, 1, 2]], channel_per_string=True)
    bend = [(t, p) for t, ch, p in pitchwheels(events) if ch == 3]
    plain_bend = [(t, p) for t, ch, p in pitchwheels(plain) if ch == 3]
    # The curve starts 24 ticks later and is squeezed to end as written
    assert bend[0][0] == plain_bend[0][0] + 24
    assert all(24 < t <= 480 for t, _ in bend)
    assert max(p for _, p in bend) == max(p for _, p in plain_bend)


def test_shift_slide_from_strummed_chord_reaches_target(tmp_path):
    notes = [{'string': 0, 'fret': 3}, {'string': 1, 'fret': 2, 'slide_out': 'shift'},
             {'string': 1, 'fret': 4}]
    strummed = convert(tmp_path, notes, chords=[[0, 1], [2]], channel_per_string=True, **STRUM)
    plain = convert(tmp_path, notes, chords=[[0, 1], [2]], channel_per_string=True)
    glide = [p for t, ch, p in pitchwheels(strummed) if ch == 4 and 0 < t < 480]
    # Glides up the 2 semitones to the target, as without the strum
    assert glide and max(glide) == max(p for t, ch, p in pitchwheels(plain) if ch == 4 and t < 480)
    assert (480, 49, 4) in note_ons(strummed)


# Brush and arpeggio

@pytest.mark.parametrize('fields, expected', [
    ({}, (None, 'pick')),
    ({'pick_stroke': 'up'}, ('up', 'pick')),
    ({'brush': 'down'}, ('down', 'brush')),
    ({'arpeggio': 'up'}, ('up', 'arpeggio')),
    # The slowest spread wins
    ({'pick_stroke': 'down', 'brush': 'up'}, ('up', 'brush')),
    ({'brush': 'down', 'arpeggio': 'up'}, ('up', 'arpeggio')),
])
def test_beat_stroke(fields, expected):
    assert beat_stroke(Beat(**fields)) == expected


def test_strum_delays_by_kind():
    # 25 / 50 ms at 120 BPM = 24 / 48 ticks per string
    options = {'brush_time': 25, 'arpeggio_time': 50}
    assert delays([strum_occ(0, kind='brush'), strum_occ(1, kind='brush')], **options) == {1: 24}
    assert delays([strum_occ(0, kind='arpeggio'), strum_occ(1, kind='arpeggio')], **options) == {1: 48}


def test_strum_delays_slowest_kind_in_chord():
    chord = [strum_occ(0), strum_occ(1, kind='brush'), strum_occ(2)]
    assert delays(chord, brush_time=25) == {1: 24, 2: 48}


def test_strum_delays_kind_off():
    chord = [strum_occ(0, kind='brush'), strum_occ(1, kind='brush')]
    assert delays(chord, brush_time=0) == {}
    # A brush off doesn't turn off pick strokes
    assert delays([strum_occ(0), strum_occ(1)], brush_time=0) == {1: 12}


def test_brush_up_spreads_high_to_low(tmp_path):
    events = convert(tmp_path, CHORD, chords=[[0, 1, 2]], beat_fields=[{'brush': 'up'}],
                     **STRUM, brush_time=25)
    assert note_ons(events) == [(0, 50, 0), (24, 47, 0), (48, 43, 0)]


def test_arpeggio_down_spreads_low_to_high(tmp_path):
    events = convert(tmp_path, CHORD, chords=[[0, 1, 2]], beat_fields=[{'arpeggio': 'down'}],
                     **STRUM, arpeggio_time=50)
    assert note_ons(events) == [(0, 43, 0), (48, 47, 0), (96, 50, 0)]
    assert {t for t, _ in note_offs(events)} == {480}


def test_brush_direction_sets_previous_stroke():
    # An up-brush on the beat, then an off-grid (triplet) onset: down
    occurrences = [occurrence(0, stroke='up'), occurrence(Q // 3)]
    assert stroke_directions(picked_onsets(occurrences)) == {0: 'up', Q // 3: 'down'}
