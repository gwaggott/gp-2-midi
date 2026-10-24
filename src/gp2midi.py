#!/usr/bin/env python3
"""
Convert Guitar Pro tab tracks to MIDI files.

Supports (the format is detected from the file's content):
  - .gp   (Guitar Pro 7/8 — ZIP archive containing Content/score.gpif)
  - .gpx  (Guitar Pro 6 — BCFZ-compressed container holding score.gpif)
  - .gpif (raw XML)
  - .xml  (raw GPIF XML exported from Guitar Pro)
  - .gp3 / .gp4 / .gp5 (Guitar Pro 3-5, read with PyGuitarPro)

Usage:
  python gp2midi.py song.gp
  python gp2midi.py song.gpx -o ./output
  python gp2midi.py song.gp5 -o ./output
  python gp2midi.py song.gpif --all-tracks
"""

import math
import random
from bisect import bisect_right
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
import argparse

try:
    from mido import MidiFile, MidiTrack, Message, MetaMessage
except ImportError:
    print("Error: 'mido' library required. Install with: pip install mido")
    sys.exit(1)

from typing import Callable

from gpif import (
    TICKS_PER_BEAT,
    Beat,
    Note,
    Score,
    Track,
    harmonic_pitch,
    load_score,
    midi_pitch,
    track_bars,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Dynamic marking → note-on velocity (evenly spaced, MF = 80 as before).
# The default for --dynamic-velocity.
DYNAMIC_VELOCITY = {
    'PPP': 16, 'PP': 32, 'P': 48, 'MP': 64,
    'MF': 80, 'F': 96, 'FF': 112, 'FFF': 127,
}
DEFAULT_DYNAMIC = 'MF'

# Velocity adjustments, one dynamic level (16) per step
ACCENT_BOOST = {'normal': 16, 'heavy': 32}
GHOST_CUT = 32

# Staccato notes sound for this fraction of their written length
STACCATO_FRACTION = 0.5

# Hammer-on / pull-off destination notes aren't picked: play them softer by
# this much (one dynamic level). --hopo-cut overrides; 0 disables.
DEFAULT_HOPO_CUT = 16

# Ticks the origin note overlaps a hammer-on / pull-off destination so that
# synths with a legato / mono mode slur into it. Off by default because on a
# polyphonic patch both notes sound together briefly. --hopo-overlap sets it.
DEFAULT_HOPO_OVERLAP = 0

# Palm-muted notes are damped: they sound for this fraction of their written
# length and play this much softer. --palm-mute-length / --palm-mute-cut.
DEFAULT_PALM_MUTE_LENGTH = 0.5
DEFAULT_PALM_MUTE_CUT = 8

# The picking hand mutes every string it strikes, so when one note struck at
# an onset (tick and staff) is palm muted, the other struck notes there are
# too: tabs often mark only some of a chord (e.g. one note of a power chord).
# --no-palm-mute-chords keeps the marks per note.
DEFAULT_PALM_MUTE_CHORDS = True

# Dead (muted, 'x') notes are a percussive click: they sound for at most this
# many ticks (480 / 16 = a 64th note) and play this much softer.
# --dead-note-length / --dead-note-cut.
DEFAULT_DEAD_NOTE_LENGTH = 30
DEFAULT_DEAD_NOTE_CUT = 16

# Vibrato: a pitch wave that only goes sharp, as on a guitar. Peak depth in
# semitones for 'slight' vibrato ('wide' is double) and rate in Hz.
# --vibrato-depth / --vibrato-rate; depth 0 disables.
DEFAULT_VIBRATO_DEPTH = 0.5
DEFAULT_VIBRATO_RATE = 5.5
VIBRATO_WIDTH = {'slight': 1.0, 'wide': 2.0}

# Slides: glide time in ticks (capped at the note's length) for slides into,
# out of, and between notes, and how far slide-in / slide-out notes travel.
# --slide-time / --slide-distance; time 0 disables slides.
DEFAULT_SLIDE_TIME = 120
DEFAULT_SLIDE_DISTANCE = 5

# Grace notes: how long they sound (0 = their written length, usually a 32nd)
# and how much softer they play. --grace-length / --grace-cut.
DEFAULT_GRACE_LENGTH = 0
DEFAULT_GRACE_CUT = 16

# Harmonics play at the harmonic's pitch (--no-harmonics: the fretted pitch)
# and this much softer (--harmonic-cut). A semi harmonic plays the fretted
# note plus the harmonic, which is softer by a further SEMI_HARMONIC_CUT.
DEFAULT_HARMONIC_CUT = 0
SEMI_HARMONIC_CUT = 16

# Humanize: small random and timing variations so the output sounds played
# rather than sequenced (see docs/humanize.md). On by default; --no-humanize
# gives the exact score. Random values come from a generator seeded per track
# from --seed and the track id, so runs are reproducible.
DEFAULT_HUMANIZE = True
DEFAULT_SEED = 0

# Humanize: each onset (all notes struck at one tick) gets one random velocity
# offset of up to ± this much, added to the dynamic's velocity before accents
# and the other adjustments. --velocity-spread; 0 disables.
DEFAULT_VELOCITY_SPREAD = 5

# Humanize: an onset with no pick stroke in the score is picked by where it
# falls in the beat, as the picking hand keeps swinging down and up in time
# (through rests too). On the eighth-note grid: on the beat down, the 'and'
# up. A beat with an onset on a sixteenth between the eighths uses the
# sixteenth grid: the 1st and 3rd sixteenths down, the 2nd and 4th up. Off
# both grids (e.g. triplets): the opposite of the previous picked onset when
# at most ALTERNATE_PICK_TICKS after it, else a downstroke.
EIGHTH_TICKS = TICKS_PER_BEAT // 2
SIXTEENTH_TICKS = TICKS_PER_BEAT // 4
ALTERNATE_PICK_TICKS = EIGHTH_TICKS

# Humanize: the notes of a picked chord sound one after another as the pick
# crosses the strings (low to high on a downstroke, high to low on an
# upstroke), this many milliseconds per string. --strum-time; 0 disables.
DEFAULT_STRUM_TIME = 6.0

# Humanize: the same for chords marked in the score as a brush (a strum) or
# an arpeggio (a slow roll). --brush-time / --arpeggio-time; 0 disables.
DEFAULT_BRUSH_TIME = 15.0
DEFAULT_ARPEGGIO_TIME = 40.0

# Stroke kinds, slowest spread last: when a beat (or the beats at one tick)
# has more than one marking, the later one wins
STROKE_KINDS = ('pick', 'brush', 'arpeggio')

# Pitch-bend range in semitones, set on the channel via RPN 0. GP bends go up
# to 2.5 tones (5 semitones); a wider range keeps headroom at the cost of
# resolution (8192 steps per direction either way).
DEFAULT_BEND_RANGE = 12

# --channel-per-string: string 1 (the highest) goes on the first of these
# channels, string 2 on the next, and so on. Channel 10 (index 9) is left
# out because General MIDI reserves it for drums, which leaves 15 channels.
STRING_CHANNELS = [c for c in range(16) if c != 9]

# --mpe: an MPE lower zone. Channel 1 (index 0) is the manager channel for
# zone-wide messages (program change, the MPE Configuration Message); the
# strings go on the member channels from channel 2 up, highest string first.
MPE_MANAGER_CHANNEL = 0
MPE_MEMBER_CHANNELS = list(range(1, 16))

# --mpe: MPE's timbre control (CC74) carries palm muting, set on each struck
# note's channel just before its note-on. --open-timbre / --palm-mute-timbre.
TIMBRE_CC = 74
DEFAULT_OPEN_TIMBRE = 0
DEFAULT_PALM_MUTE_TIMBRE = 127

# Spacing of pitch-bend messages along a bend ramp (480 / 24 = 1/24 beat)
BEND_STEP_TICKS = 20

# Event sort keys at equal ticks: note-offs and meta first, then pitch-bend
# resets for unbent notes (and MPE timbre for new notes), then bend curves (so a bend wins over a reset from
# another note in the same chord), then note-ons (so the bend is in place
# before the note sounds).
SK_OFF, SK_RESET, SK_BEND, SK_ON = 0, 1, 2, 3


@dataclass(frozen=True)
class MidiOptions:
    """
    Settings for how articulations become MIDI (one per command-line switch).
    Defaults match the CLI defaults; see the DEFAULT_* constants above.
    """
    velocity: int | None = None           # fixed velocity for every note; None = from the score
    # dynamic marking → velocity; must include DEFAULT_DYNAMIC (MF)
    dynamic_velocity: dict[str, int] = field(default_factory=lambda: dict(DYNAMIC_VELOCITY))
    bend_range: int = DEFAULT_BEND_RANGE  # pitch-bend range in semitones (RPN 0)
    hopo_cut: int = DEFAULT_HOPO_CUT
    hopo_overlap: int = DEFAULT_HOPO_OVERLAP
    palm_mute_length: float = DEFAULT_PALM_MUTE_LENGTH
    palm_mute_cut: int = DEFAULT_PALM_MUTE_CUT
    palm_mute_chords: bool = DEFAULT_PALM_MUTE_CHORDS  # palm mute a whole onset if any note there is
    dead_note_length: int = DEFAULT_DEAD_NOTE_LENGTH
    dead_note_cut: int = DEFAULT_DEAD_NOTE_CUT
    vibrato_depth: float = DEFAULT_VIBRATO_DEPTH
    vibrato_rate: float = DEFAULT_VIBRATO_RATE
    slide_time: int = DEFAULT_SLIDE_TIME
    slide_distance: int = DEFAULT_SLIDE_DISTANCE
    grace_length: int = DEFAULT_GRACE_LENGTH
    grace_cut: int = DEFAULT_GRACE_CUT
    harmonics: bool = True
    harmonic_cut: int = DEFAULT_HARMONIC_CUT
    channel_per_string: bool = False      # one MIDI channel per string (per-string pitch bend)
    mpe: bool = False                     # per-string channels as an MPE lower zone
    open_timbre: int = DEFAULT_OPEN_TIMBRE            # CC74 for notes not palm muted (--mpe)
    palm_mute_timbre: int = DEFAULT_PALM_MUTE_TIMBRE  # CC74 for palm-muted notes (--mpe)
    humanize: bool = DEFAULT_HUMANIZE     # random / timing variations (docs/humanize.md)
    seed: int = DEFAULT_SEED              # seeds each track's random generator
    velocity_spread: int = DEFAULT_VELOCITY_SPREAD  # ± random velocity per onset (humanize)
    strum_time: float = DEFAULT_STRUM_TIME          # ms per string of a picked chord (humanize)
    brush_time: float = DEFAULT_BRUSH_TIME          # ms per string of a brush (humanize)
    arpeggio_time: float = DEFAULT_ARPEGGIO_TIME    # ms per string of an arpeggio (humanize)


DEFAULT_OPTIONS = MidiOptions()

# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def bpm_to_tempo_us(bpm: float) -> int:
    """Beats per minute → microseconds per beat."""
    return int(round(60_000_000 / bpm))


def bend_value(semitones: float, bend_range: int) -> int:
    """Semitones → MIDI pitchwheel value (-8192..8191) for the given range."""
    return max(-8192, min(8191, int(round(semitones / bend_range * 8192))))


def bend_curve_at(points: list[tuple[float, float]], x: float) -> float:
    """Piecewise-linear bend value (semitones) at position x (0.0–1.0)."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, v0), (x1, v1) in zip(points, points[1:]):
        if x0 <= x < x1:
            return v0 + (v1 - v0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def curve_events(
    start: int,
    duration: int,
    curve: Callable[[float], float],
    breakpoints: list[float],
    step: int,
    bend_range: int,
    channel: int,
) -> list[tuple[int, int, Message]]:
    """
    Pitchwheel events tracing curve(ticks since note start) → semitones over
    [start, start + duration).

    Samples every `step` ticks plus each breakpoint (ticks since start). Events
    are kept strictly before the note's end tick so they can't override the
    next note's reset at the same tick; the last sample uses the curve's value
    at the full duration. Consecutive duplicates are removed later.
    """
    last = start + max(duration - 1, 0)
    ticks = set(range(start, last + 1, max(1, step)))
    ticks.update(min(start + int(round(b)), last) for b in breakpoints)
    events = []
    for tick in sorted(ticks):
        offset = duration if tick == last else tick - start
        value = bend_value(curve(offset), bend_range)
        events.append((tick, SK_BEND, Message('pitchwheel', channel=channel, pitch=value, time=0)))
    return events


def bend_events(
    start: int,
    duration: int,
    points: list[tuple[float, float]],
    bend_range: int,
    channel: int,
) -> list[tuple[int, int, Message]]:
    """Pitchwheel events tracing a bend curve over [start, start + duration)."""
    return curve_events(
        start, duration,
        lambda t: bend_curve_at(points, t / duration if duration else 0.0),
        [x * duration for x, _ in points],
        BEND_STEP_TICKS, bend_range, channel,
    )


def ramp(t: float, start: float, length: float) -> float:
    """0 before start, rising linearly to 1 at start + length, 1 after."""
    if length <= 0:
        return 0.0 if t < start else 1.0
    return min(1.0, max(0.0, (t - start) / length))


def note_pitch_curve(
    note: Note,
    duration: int,
    bpm: float,
    glide_to: int | None = None,
    options: MidiOptions = DEFAULT_OPTIONS,
) -> tuple[Callable[[float], float], list[float], int] | None:
    """
    Combined pitch offset for one note: bend + vibrato + slides, added together.

    glide_to is the semitone interval to the next note on the string for a
    shift / legato slide (None if there's no such note). Returns
    (curve(ticks since start) → semitones, breakpoints, sample step), or None
    if the note has no pitch effect.
    """
    parts: list[Callable[[float], float]] = []
    breakpoints: list[float] = []
    step = BEND_STEP_TICKS

    if note.bend:
        points = note.bend
        parts.append(lambda t: bend_curve_at(points, t / duration if duration else 0.0))
        breakpoints += [x * duration for x, _ in points]

    if note.vibrato and options.vibrato_depth > 0 and options.vibrato_rate > 0:
        depth = options.vibrato_depth * VIBRATO_WIDTH[note.vibrato]
        cycles_per_tick = options.vibrato_rate * 60 / (bpm * TICKS_PER_BEAT)
        # Sharp-only wave: 0 → depth → 0 each cycle
        parts.append(lambda t: depth * (1 - math.cos(2 * math.pi * cycles_per_tick * t)) / 2)
        step = max(1, min(step, int(1 / (cycles_per_tick * 12))))   # ≥ 12 samples per cycle

    slide_distance = options.slide_distance
    if options.slide_time > 0:
        length = min(options.slide_time, duration)
        if note.slide_in and slide_distance > 0:
            # Start off-pitch and glide onto the note
            sign = -1 if note.slide_in == 'below' else 1
            parts.append(lambda t: sign * slide_distance * (1 - ramp(t, 0, length)))
            breakpoints += [0, length]

        out_interval = None
        if note.slide_out in ('shift', 'legato'):
            out_interval = glide_to
        elif note.slide_out in ('down', 'up') and slide_distance > 0:
            out_interval = -slide_distance if note.slide_out == 'down' else slide_distance
        if out_interval:
            # Glide away over the end of the note
            out_start = duration - length
            parts.append(lambda t: out_interval * ramp(t, out_start, length))
            breakpoints += [out_start, duration]

    if not parts:
        return None
    return (lambda t: sum(part(t) for part in parts)), breakpoints, step


def bend_range_rpn(channel: int, semitones: int) -> list[Message]:
    """Control changes that set the pitch-bend range (RPN 0), then null the RPN."""
    return [
        Message('control_change', channel=channel, control=101, value=0, time=0),
        Message('control_change', channel=channel, control=100, value=0, time=0),
        Message('control_change', channel=channel, control=6, value=semitones, time=0),
        Message('control_change', channel=channel, control=38, value=0, time=0),
        Message('control_change', channel=channel, control=101, value=127, time=0),
        Message('control_change', channel=channel, control=100, value=127, time=0),
    ]


def drop_redundant_bends(events: list[tuple[int, int, Message | MetaMessage]]) -> list:
    """
    Remove pitchwheel events that repeat their channel's current value
    (initially 0).
    """
    current: dict[int, int] = {}
    kept = []
    for event in events:
        msg = event[2]
        if msg.type == 'pitchwheel':
            if msg.pitch == current.get(msg.channel, 0):
                continue
            current[msg.channel] = msg.pitch
        kept.append(event)
    return kept


def drop_redundant_timbre(events: list[tuple[int, int, Message | MetaMessage]]) -> list:
    """
    Remove timbre (CC74) events that repeat their channel's current value.
    The first one on each channel is kept, as the synth's value is unknown.
    """
    current: dict[int, int] = {}
    kept = []
    for event in events:
        msg = event[2]
        if msg.type == 'control_change' and msg.control == TIMBRE_CC:
            if current.get(msg.channel) == msg.value:
                continue
            current[msg.channel] = msg.value
        kept.append(event)
    return kept


def string_channels(track: Track, options: MidiOptions = DEFAULT_OPTIONS) -> list[int] | None:
    """
    MIDI channel for each GPIF string (index 0 = lowest string) when the
    track gets one channel per string, or None for a single channel: when
    --channel-per-string and --mpe are off, on drum tracks, tracks without a
    tuning, tracks with more strings than there are channels, and tracks with
    more than one staff. The highest string gets the first channel
    (STRING_CHANNELS, or MPE_MEMBER_CHANNELS with --mpe), as in a guitar
    controller's mono mode.
    """
    tuning = track.tuning
    if not (options.channel_per_string or options.mpe) or track.is_drum or not tuning:
        return None
    if len(track.staves) > 1:
        return None
    channels = MPE_MEMBER_CHANNELS if options.mpe else STRING_CHANNELS
    if len(tuning) > len(channels):
        return None
    return channels[:len(tuning)][::-1]


def mpe_configuration(members: int) -> list[Message]:
    """
    The MPE Configuration Message for a lower zone with the given number of
    member channels (RPN 6 on the manager channel), then null the RPN.
    """
    ch = MPE_MANAGER_CHANNEL
    return [
        Message('control_change', channel=ch, control=101, value=0, time=0),
        Message('control_change', channel=ch, control=100, value=6, time=0),
        Message('control_change', channel=ch, control=6, value=members, time=0),
        Message('control_change', channel=ch, control=101, value=127, time=0),
        Message('control_change', channel=ch, control=100, value=127, time=0),
    ]


def parse_dynamic_velocity(text: str) -> dict[str, int]:
    """
    --dynamic-velocity: 'PPP:16,PP:32,...' → DYNAMIC_VELOCITY with those
    levels replaced (names are case-insensitive, velocities clamped to
    1-127). Levels not given keep their default.
    """
    levels = dict(DYNAMIC_VELOCITY)
    for pair in text.split(','):
        if not pair.strip():
            continue
        name, sep, value = pair.partition(':')
        name = name.strip().upper()
        if not sep or name not in DYNAMIC_VELOCITY:
            raise argparse.ArgumentTypeError(
                f"expected DYNAMIC:VELOCITY with DYNAMIC one of "
                f"{', '.join(DYNAMIC_VELOCITY)}, got {pair.strip()!r}")
        try:
            velocity = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"velocity for {name} is not a whole number: {value.strip()!r}") from None
        levels[name] = max(1, min(127, velocity))
    return levels


def note_velocity(
    dynamic: str | None,
    note: Note,
    options: MidiOptions = DEFAULT_OPTIONS,
    is_grace: bool = False,
    harmonic: str | None = None,
    offset: int = 0,
) -> int:
    """
    Velocity 1–127 from the beat's dynamic plus the note's accent, ghost,
    hammer-on / pull-off, palm-mute and dead-note marks, whether it's a grace
    note, and whether it sounds as a harmonic ('full', or 'semi' for the
    harmonic layer of a semi harmonic). offset (the humanize variation) is
    added to the dynamic's velocity, so the marks still apply on top.
    """
    levels = options.dynamic_velocity
    velocity = levels.get(dynamic or DEFAULT_DYNAMIC, levels[DEFAULT_DYNAMIC])
    velocity += offset
    velocity += ACCENT_BOOST.get(note.accent, 0)
    if note.ghost:
        velocity -= GHOST_CUT
    if note.hopo_dest:
        velocity -= options.hopo_cut
    if note.palm_muted:
        velocity -= options.palm_mute_cut
    if note.dead:
        velocity -= options.dead_note_cut
    if is_grace:
        velocity -= options.grace_cut
    if harmonic:
        velocity -= options.harmonic_cut
        if harmonic == 'semi':
            velocity -= SEMI_HARMONIC_CUT
    return max(1, min(127, velocity))


def sounding_ticks(
    duration: int,
    note: Note,
    options: MidiOptions = DEFAULT_OPTIONS,
) -> int:
    """
    How long a note actually sounds (≥ 1 tick): the written duration,
    shortened by staccato, palm muting or a dead note. The shortest wins.
    """
    sounding = duration
    if note.staccato:
        sounding = min(sounding, int(round(duration * STACCATO_FRACTION)))
    if note.palm_muted:
        sounding = min(sounding, int(round(duration * options.palm_mute_length)))
    if note.dead:
        sounding = min(sounding, options.dead_note_length)
    return max(1, sounding)

def ms_to_ticks(ms: float, bpm: float) -> float:
    """Milliseconds → ticks at the given tempo."""
    return ms * bpm * TICKS_PER_BEAT / 60_000


def beat_stroke(beat: Beat) -> tuple[str | None, str]:
    """
    The beat's stroke marked in the score and its kind (see STROKE_KINDS):
    (direction 'down' / 'up', or None if unmarked, kind). An arpeggio wins
    over a brush, and a brush over a pick stroke; unmarked is 'pick'.
    """
    for kind in reversed(STROKE_KINDS[1:]):
        direction = getattr(beat, kind)
        if direction:
            return direction, kind
    return beat.pick_stroke, 'pick'


def is_picked(i: int, occ: dict, unpicked: set[int] = frozenset()) -> bool:
    """
    Whether occurrence i (of track_to_midi's occurrences) is a note the pick
    strikes: not a tempo change, tied continuation, hammer-on / pull-off
    destination, grace note or one of the indexes in unpicked (legato-slide
    destinations).
    """
    if 'note' not in occ or i in unpicked or occ['grace']:
        return False
    return not occ['note'].is_tie_dest and not occ['note'].hopo_dest


def picked_onsets(occurrences: list[dict], unpicked: set[int] = frozenset()) -> dict[int, str | None]:
    """
    The onset ticks where the pick strikes, from track_to_midi's occurrences:
    tick → the stroke marked in the score ('down' / 'up', see beat_stroke),
    or None. Notes that aren't picked (see is_picked) are left out. When the
    notes at one tick disagree, the first marked stroke wins over unmarked
    ones.
    """
    onsets: dict[int, str | None] = {}
    for i, occ in enumerate(occurrences):
        if not is_picked(i, occ, unpicked):
            continue
        if onsets.get(occ['tick']) is None:
            onsets[occ['tick']] = occ['stroke']
    return onsets


def stroke_directions(
    onsets: dict[int, str | None],
    bar_starts: list[int] | None = None,
) -> dict[int, str]:
    """
    Pick direction ('down' / 'up') of each onset from picked_onsets: the
    stroke marked in the score, otherwise from its place in the beat (see
    EIGHTH_TICKS above), otherwise the opposite of the previous onset's when
    at most ALTERNATE_PICK_TICKS after it, otherwise a downstroke.
    bar_starts (ascending ticks, default [0]) places each onset in its bar,
    so beats are counted from the bar start even after an odd meter.
    """
    bar_starts = bar_starts or [0]

    def beat_position(tick: int) -> tuple[int, int, int]:
        """(bar start, beat in the bar, ticks into the beat)"""
        start = bar_starts[max(0, bisect_right(bar_starts, tick) - 1)]
        return (start, *divmod(tick - start, TICKS_PER_BEAT))

    # Beats with an onset on a sixteenth between the eighths
    sixteenth_beats = set()
    for tick in onsets:
        start, beat, offset = beat_position(tick)
        if offset % SIXTEENTH_TICKS == 0 and offset % EIGHTH_TICKS != 0:
            sixteenth_beats.add((start, beat))

    directions: dict[int, str] = {}
    prev_tick, prev_direction = None, None
    for tick in sorted(onsets):
        direction = onsets[tick]
        if direction is None:
            start, beat, offset = beat_position(tick)
            grid = SIXTEENTH_TICKS if (start, beat) in sixteenth_beats else EIGHTH_TICKS
            if offset % grid == 0:
                direction = 'down' if offset // grid % 2 == 0 else 'up'
            elif prev_tick is not None and tick - prev_tick <= ALTERNATE_PICK_TICKS:
                direction = 'up' if prev_direction == 'down' else 'down'
            else:
                direction = 'down'
        directions[tick] = direction
        prev_tick, prev_direction = tick, direction
    return directions


def palm_mute_chords(occurrences: list[dict]) -> set[int]:
    """
    Indexes of the struck notes to palm mute because another note struck at
    the same onset (tick and staff) is palm muted and they aren't. Tied
    continuations neither count nor change, and dead notes stay as they are.
    """
    muted = {(occ['tick'], occ['staff']) for occ in occurrences
             if 'note' in occ and occ['note'].palm_muted and not occ['note'].is_tie_dest}
    return {i for i, occ in enumerate(occurrences)
            if 'note' in occ and (occ['tick'], occ['staff']) in muted
            and not (occ['note'].palm_muted or occ['note'].is_tie_dest or occ['note'].dead)}


def strum_delays(
    occurrences: list[dict],
    directions: dict[int, str],
    unpicked: set[int] = frozenset(),
    options: MidiOptions = DEFAULT_OPTIONS,
) -> dict[int, int]:
    """
    Humanize: ticks each picked note of a chord sounds after the onset, as
    the pick crosses the strings in the onset's direction (directions, from
    stroke_directions): from the lowest struck string on a downstroke, the
    highest on an upstroke. Each string further on adds --strum-time ms at
    the note's tempo (--brush-time / --arpeggio-time for a chord marked as
    a brush / arpeggio; the slowest kind among its notes), skipped strings
    included. Chords are per (tick, staff), as each staff has its own
    strings. Keyed by occurrence index; notes without a delay are left out.
    """
    ms_per_string = {'pick': options.strum_time, 'brush': options.brush_time,
                     'arpeggio': options.arpeggio_time}
    chords: dict[tuple[int, int], list[int]] = {}
    for i, occ in enumerate(occurrences):
        if occ.get('tick') in directions and is_picked(i, occ, unpicked):
            chords.setdefault((occ['tick'], occ['staff']), []).append(i)

    delays: dict[int, int] = {}
    for (tick, _), indexes in chords.items():
        kind = max((occurrences[i]['stroke_kind'] for i in indexes), key=STROKE_KINDS.index)
        if ms_per_string[kind] <= 0:
            continue
        strings = [occurrences[i]['note'].string for i in indexes]
        first = min(strings) if directions[tick] == 'down' else max(strings)
        for i, string in zip(indexes, strings):
            if string != first:
                delays[i] = round(abs(string - first)
                                  * ms_to_ticks(ms_per_string[kind], occurrences[i]['bpm']))
    return delays


def track_rng(track: Track, options: MidiOptions = DEFAULT_OPTIONS) -> random.Random:
    """
    The track's random generator, seeded from --seed and the track id, so a
    track's output doesn't depend on which other tracks are converted. (A
    string seed, as hash() of a tuple with strings differs between runs.)
    Humanize code only calls its randint, in a fixed order, so tests can pass
    a scripted stand-in to track_to_midi instead.
    """
    return random.Random(f'{options.seed}:{track.id}')

# ---------------------------------------------------------------------------
# Track → MIDI
# ---------------------------------------------------------------------------

def track_to_midi(
    track: Track,
    score: Score,
    output_path: str,
    options: MidiOptions = DEFAULT_OPTIONS,
    rng: random.Random | None = None,
) -> None:
    """
    Write the track as a MIDI file. rng supplies the humanize random values
    (default: track_rng); tests pass a stand-in with scripted values.
    """
    master_bars, voices = score.master_bars, score.voices
    if rng is None:
        rng = track_rng(track, options)
    beats, notes, rhythms, tempos = score.beats, score.notes, score.rhythms, score.tempos

    midi = MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    midi_track = MidiTrack()
    midi.tracks.append(midi_track)

    channel = 9 if track.is_drum else track.channel
    per_string = string_channels(track, options)
    mpe = options.mpe and per_string is not None

    def note_channel(note: Note) -> int:
        """The note's string channel, or the track channel."""
        if per_string is None:
            return channel
        return per_string[max(0, min(len(per_string) - 1, note.string))]

    # --- Header meta messages ---
    midi_track.append(MetaMessage('track_name', name=track.name, time=0))
    midi_track.append(MetaMessage(
        'set_tempo', tempo=bpm_to_tempo_us(tempos[0].bpm), time=0
    ))
    if mpe:
        midi_track.extend(mpe_configuration(len(per_string)))
        program_channels = [MPE_MANAGER_CHANNEL]
    else:
        program_channels = sorted(per_string) if per_string else [channel]
    if not track.is_drum:
        for ch in program_channels:
            midi_track.append(Message(
                'program_change', channel=ch,
                program=track.program, time=0
            ))

    # Every staff (e.g. both hands of a piano) goes into the one MIDI track.
    # Strings and tuning are per staff, so string state is keyed by
    # (staff, string): see string_key.
    staves = track.staves
    staff_bars = [track_bars(score, track, staff) for staff in range(len(staves))]

    # --- Pass 1: walk the score into a list of note occurrences ---
    # Each entry is {'tempo': (tick, bpm)} or a note: {'tick', 'duration',
    # 'note', 'staff', 'pitch', 'dynamic', 'bpm', 'grace', 'harmonic',
    # 'stroke', 'stroke_kind'} (stroke: see beat_stroke), in the order the
    # score is walked (bar by bar; within a bar, staff by staff). Pass 2 needs
    # the whole list to look ahead for slides. A semi harmonic adds two
    # entries (fretted note + harmonic).
    #
    # Grace beats take no time in the bar. A before-beat grace note sounds
    # just before the main beat (from main - length to main); an on-beat one
    # sounds on the beat and delays the main note by its length.
    occurrences: list[dict] = []
    tempo_cursor = 0  # index into tempos list
    current_tick = 0
    bar_starts: list[int] = []

    for bar_idx, mb in enumerate(master_bars):
        # Advance tempo automations
        while (
            tempo_cursor + 1 < len(tempos)
            and tempos[tempo_cursor + 1].bar <= bar_idx
            and tempos[tempo_cursor + 1].position == 0.0
        ):
            tempo_cursor += 1
            occurrences.append({'tempo': (current_tick, tempos[tempo_cursor].bpm)})

        # Bar length always comes from the time signature, not voice content,
        # to stay aligned even if voices have rests/partial fills
        bar_ticks = int(round(mb.numerator * (4 / mb.denominator) * TICKS_PER_BEAT))

        bpm = tempos[tempo_cursor].bpm
        bar_starts.append(current_tick)

        # Each staff's bar (None: no bar there), and all its voices, in
        # parallel from the same start tick
        for staff, staff_bar_list in enumerate(staff_bars):
            bar = staff_bar_list[bar_idx]
            tuning = staves[staff].tuning
            for voice_id in bar.voice_ids if bar else []:
                if voice_id not in voices:
                    continue
                beat_tick = current_tick
                main_delay = 0      # set by an on-beat grace note for the next beat
                for beat_id in voices[voice_id].beat_ids:
                    if beat_id not in beats:
                        continue
                    beat = beats[beat_id]
                    rhythm = rhythms.get(beat.rhythm_id)
                    written_ticks = rhythm.ticks if rhythm else TICKS_PER_BEAT

                    if beat.grace:
                        length = options.grace_length or written_ticks
                        if beat.grace == 'before' and beat_tick - length >= 0:
                            start = beat_tick - length
                        else:
                            # On the beat (also a before-beat grace at the very start)
                            start = beat_tick
                            main_delay = length
                        start_tick, duration_ticks = start, length
                    else:
                        # The main note after an on-beat grace starts late and is shorter
                        delay = min(main_delay, written_ticks - 1)
                        start_tick, duration_ticks = beat_tick + delay, written_ticks - delay
                        main_delay = 0

                    if not beat.is_rest:
                        stroke, stroke_kind = beat_stroke(beat)
                        for note_id in beat.note_ids:
                            if note_id not in notes:
                                continue
                            note = notes[note_id]
                            fretted = note.midi
                            if fretted is None:
                                fretted = midi_pitch(tuning, note.string, note.fret)
                            if fretted is None:
                                continue

                            # Sounding pitch(es). GP8's Midi value is the fretted
                            # pitch even for harmonics, so work the harmonic out.
                            layers: list[tuple[int, str | None]] = [(fretted, None)]
                            h_pitch = harmonic_pitch(tuning, note, fretted) if options.harmonics else None
                            if h_pitch is not None:
                                if note.harmonic.type == 'semi':
                                    layers.append((h_pitch, 'semi'))
                                else:
                                    layers = [(h_pitch, 'full')]

                            for pitch, harmonic in layers:
                                occurrences.append({
                                    'tick': start_tick, 'duration': duration_ticks, 'note': note,
                                    'staff': staff, 'pitch': pitch, 'dynamic': note.dynamic or beat.dynamic,
                                    'bpm': bpm, 'grace': bool(beat.grace), 'harmonic': harmonic,
                                    'stroke': stroke, 'stroke_kind': stroke_kind,
                                })

                    if not beat.grace:
                        beat_tick += written_ticks

        current_tick += bar_ticks

    def string_key(occ: dict) -> tuple[int, int]:
        """The occurrence's string: (staff, string), as each staff has its own."""
        return occ['staff'], occ['note'].string

    # A string sounds one note at a time: cut the previous note on a grace
    # note's string short so it ends where the grace note starts. Done before
    # emitting so its pitch curve, tie extension and slide target all follow.
    # Only for fretted staves: drum notes have no real string (all read as 0).
    last_on_string_idx: dict[tuple[int, int], int] = {}
    for i, occ in enumerate(occurrences):
        if 'note' not in occ or not staves[occ['staff']].tuning or track.is_drum:
            continue
        string = string_key(occ)
        prev = occurrences[last_on_string_idx[string]] if string in last_on_string_idx else None
        if occ['grace'] and prev and prev['tick'] < occ['tick'] < prev['tick'] + prev['duration']:
            prev['duration'] = occ['tick'] - prev['tick']
        last_on_string_idx[string] = i

    # Palm muting covers every note struck at a muted onset
    if options.palm_mute_chords:
        for i in palm_mute_chords(occurrences):
            occurrences[i]['note'] = replace(occurrences[i]['note'], palm_muted=True)

    # The note that starts on the same string exactly when each note ends:
    # the target of a shift / legato slide
    starting_at: dict[tuple[tuple[int, int], int], int] = {}
    for i, occ in enumerate(occurrences):
        if 'note' in occ:
            starting_at.setdefault((string_key(occ), occ['tick']), i)

    def slide_target(i: int) -> int | None:
        occ = occurrences[i]
        if occ['note'].slide_out not in ('shift', 'legato'):
            return None
        j = starting_at.get((string_key(occ), occ['tick'] + occ['duration']))
        if j is None or occurrences[j]['pitch'] == occ['pitch']:
            return None
        return j

    slide_targets = {i: slide_target(i) for i, occ in enumerate(occurrences) if 'note' in occ}
    # Legato slide destinations aren't picked: softer, like hammer-ons
    # (unless slides are off)
    legato_dests = {j for i, j in slide_targets.items()
                    if j is not None and options.slide_time > 0
                    and occurrences[i]['note'].slide_out == 'legato'}

    # Humanize: pick direction of each picked onset tick, on fretted tracks,
    # and from it each chord note's delay as the pick crosses the strings
    directions = (stroke_directions(picked_onsets(occurrences, legato_dests), bar_starts)
                  if options.humanize and track.is_fretted and not track.is_drum else {})
    strum = strum_delays(occurrences, directions, legato_dests, options)

    # --- Pass 2: emit MIDI events ---
    # We collect (absolute_tick, sort_key, msg) then convert to delta at the end.
    # sort_key: SK_OFF < SK_RESET < SK_BEND < SK_ON at the same tick.
    raw_events: list[tuple[int, int, Message | MetaMessage]] = []

    # Tracks active notes for tie extension:
    # (channel, pitch) → last note_off index in raw_events
    active_note_off: dict[tuple[int, int], int] = {}

    # Humanize: one random velocity offset per onset tick, drawn the first
    # time a struck note is seen at that tick (in occurrence order), so every
    # note of a chord, on any voice or staff, shares it
    vary_velocity = options.humanize and options.velocity_spread > 0 and options.velocity is None
    velocity_offsets: dict[int, int] = {}

    # Last note per string, for hammer-on / pull-off overlap:
    # (staff, string) → (note_off index in raw_events, pitch, is_hopo_origin)
    last_on_string: dict[tuple[int, int], tuple[int, int, bool]] = {}

    for i, occ in enumerate(occurrences):
        if 'tempo' in occ:
            tempo_tick, new_bpm = occ['tempo']
            raw_events.append((tempo_tick, SK_OFF,
                MetaMessage('set_tempo', tempo=bpm_to_tempo_us(new_bpm), time=0)))
            continue

        beat_tick, duration_ticks = occ['tick'], occ['duration']
        note, pitch = occ['note'], occ['pitch']
        ch = note_channel(note)
        sounding = sounding_ticks(duration_ticks, note, options)

        # Strummed chord note: starts late but ends as written (the delay
        # stays below its sounding length). Its pitch effects move with it
        # only on its own string's channel: on a shared channel, a later
        # note's reset would cut into another note's curve.
        strum_delay = min(strum.get(i, 0), sounding - 1)
        bend_delay = strum_delay if per_string is not None else 0

        # Pitch bend is channel-wide (the string's channel with
        # --channel-per-string): a note with a pitch effect (bend, vibrato,
        # slide) sets its own curve; a new plain note resets to 0; a tied
        # continuation without an effect keeps the pitch held.
        target = slide_targets[i]
        curve = note_pitch_curve(
            note, duration_ticks - bend_delay, occ['bpm'],
            glide_to=occurrences[target]['pitch'] - pitch if target is not None else None,
            options=options,
        )
        if curve:
            curve_fn, breakpoints, step = curve
            raw_events.extend(curve_events(
                beat_tick + bend_delay, duration_ticks - bend_delay,
                curve_fn, breakpoints, step, options.bend_range, ch))
        elif not note.is_tie_dest:
            raw_events.append((beat_tick + bend_delay, SK_RESET,
                Message('pitchwheel', channel=ch, pitch=0, time=0)))

        if note.is_tie_dest:
            # Extend the previous note_off for this pitch
            if (ch, pitch) in active_note_off:
                ev_idx = active_note_off[(ch, pitch)]
                old_tick, sk, old_msg = raw_events[ev_idx]
                new_tick = beat_tick + duration_ticks
                raw_events[ev_idx] = (new_tick, sk, old_msg)
                last_on_string[string_key(occ)] = (ev_idx, pitch, note.hopo_origin)
        else:
            # Fixed --velocity overrides every velocity adjustment
            if options.velocity is not None:
                note_vel = options.velocity
            else:
                offset = 0
                if vary_velocity:
                    if beat_tick not in velocity_offsets:
                        velocity_offsets[beat_tick] = rng.randint(
                            -options.velocity_spread, options.velocity_spread)
                    offset = velocity_offsets[beat_tick]
                note_vel = note_velocity(occ['dynamic'], note, options, occ['grace'],
                                         occ['harmonic'], offset)
                if i in legato_dests and not note.hopo_dest:
                    note_vel = max(1, note_vel - options.hopo_cut)
            if mpe:
                # MPE timbre: palm muted or open, set before the note-on
                timbre = options.palm_mute_timbre if note.palm_muted else options.open_timbre
                raw_events.append((beat_tick + strum_delay, SK_RESET,
                    Message('control_change', channel=ch, control=TIMBRE_CC,
                            value=timbre, time=0)))
            raw_events.append((beat_tick + strum_delay, SK_ON,
                Message('note_on', channel=ch,
                        note=pitch, velocity=note_vel, time=0)))
            off_idx = len(raw_events)
            raw_events.append((beat_tick + sounding, SK_OFF,
                Message('note_off', channel=ch,
                        note=pitch, velocity=0, time=0)))
            active_note_off[(ch, pitch)] = off_idx

            # Legato: hold the origin note into this one if it
            # ended exactly here (not cut short by staccato or a rest)
            prev = last_on_string.get(string_key(occ))
            if options.hopo_overlap > 0 and note.hopo_dest and prev:
                prev_off_idx, prev_pitch, prev_is_origin = prev
                prev_tick, prev_sk, prev_msg = raw_events[prev_off_idx]
                if prev_is_origin and prev_pitch != pitch and prev_tick == beat_tick:
                    raw_events[prev_off_idx] = (
                        beat_tick + min(options.hopo_overlap, sounding), prev_sk, prev_msg)
            last_on_string[string_key(occ)] = (off_idx, pitch, note.hopo_origin)

    # --- Sort and write delta-time events ---
    raw_events.sort(key=lambda e: (e[0], e[1]))
    raw_events = drop_redundant_bends(raw_events)
    raw_events = drop_redundant_timbre(raw_events)

    # Set the bend range on each channel that bends (on every member channel
    # with --mpe, as the MPE Configuration Message resets it to 48), and
    # leave it unbent at the end of the track
    last_bend: dict[int, int] = {}
    for _, _, msg in raw_events:
        if msg.type == 'pitchwheel':
            last_bend[msg.channel] = msg.pitch
    for ch in sorted(per_string) if mpe else sorted(last_bend):
        midi_track.extend(bend_range_rpn(ch, options.bend_range))
    if last_bend:
        end_tick = max(t for t, _, _ in raw_events)
        for ch in sorted(last_bend):
            if last_bend[ch] != 0:
                raw_events.append((end_tick, SK_OFF,
                                   Message('pitchwheel', channel=ch, pitch=0, time=0)))

    prev_tick = 0
    for abs_tick, _, msg in raw_events:
        delta = abs_tick - prev_tick
        if isinstance(msg, MetaMessage):
            midi_track.append(msg.copy(time=delta))
        else:
            midi_track.append(msg.copy(time=delta))
        prev_tick = abs_tick

    midi_track.append(MetaMessage('end_of_track', time=0))
    midi.save(output_path)
    print(f"    -> {output_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def safe_filename(name: str) -> str:
    """Strip characters unsafe for filenames."""
    return "".join(c if c.isalnum() or c in ' -_.' else '_' for c in name).strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Convert Guitar Pro tab tracks to MIDI files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('input',
                        help='Input .gp, .gpx, .gpif, .xml, .gp3, .gp4 or .gp5 file')
    parser.add_argument('-o', '--output-dir', default=None,
                        help='Output directory (default: same directory as input)')
    parser.add_argument('--all-tracks', action='store_true',
                        help='Convert all tracks, not just fretted tab tracks')
    parser.add_argument('--bend-range', type=int, default=DEFAULT_BEND_RANGE,
                        metavar='N',
                        help='Pitch-bend range in semitones, 1-24, sent via RPN 0 on tracks '
                             f'with bends (default: {DEFAULT_BEND_RANGE}). Use 2 for synths '
                             'that ignore RPN; bends wider than the range are clamped.')
    parser.add_argument('--hopo-cut', type=int, default=DEFAULT_HOPO_CUT,
                        metavar='N',
                        help='Velocity reduction for hammer-on / pull-off destination notes, '
                             f'which are not picked (default: {DEFAULT_HOPO_CUT}; 0 = same as picked)')
    parser.add_argument('--hopo-overlap', type=int, default=DEFAULT_HOPO_OVERLAP,
                        metavar='TICKS',
                        help='Hold a hammer-on / pull-off origin note this many ticks into the '
                             f'destination ({TICKS_PER_BEAT} per beat) so legato / mono synth '
                             f'patches slur between them (default: {DEFAULT_HOPO_OVERLAP} = off; '
                             'try 10-30)')
    parser.add_argument('--palm-mute-chords', action=argparse.BooleanOptionalAction,
                        default=DEFAULT_PALM_MUTE_CHORDS,
                        help='Palm mute every note struck at an onset when any of them is '
                             'palm muted, as the hand mutes all the strings it strikes '
                             '(default: on; --no-palm-mute-chords keeps the marks per note)')
    parser.add_argument('--palm-mute-length', type=float, default=DEFAULT_PALM_MUTE_LENGTH,
                        metavar='FRACTION',
                        help='Palm-muted notes sound for this fraction 0-1 of their written '
                             f'length (default: {DEFAULT_PALM_MUTE_LENGTH}; 1 = full length)')
    parser.add_argument('--palm-mute-cut', type=int, default=DEFAULT_PALM_MUTE_CUT,
                        metavar='N',
                        help=f'Velocity reduction for palm-muted notes (default: {DEFAULT_PALM_MUTE_CUT})')
    parser.add_argument('--dead-note-length', type=int, default=DEFAULT_DEAD_NOTE_LENGTH,
                        metavar='TICKS',
                        help='Dead (x) notes sound for at most this many ticks '
                             f'({TICKS_PER_BEAT} per beat; default: {DEFAULT_DEAD_NOTE_LENGTH})')
    parser.add_argument('--dead-note-cut', type=int, default=DEFAULT_DEAD_NOTE_CUT,
                        metavar='N',
                        help=f'Velocity reduction for dead (x) notes (default: {DEFAULT_DEAD_NOTE_CUT})')
    parser.add_argument('--vibrato-depth', type=float, default=DEFAULT_VIBRATO_DEPTH,
                        metavar='SEMITONES',
                        help='Peak pitch rise of slight vibrato; wide vibrato is double '
                             f'(default: {DEFAULT_VIBRATO_DEPTH}; 0 = off)')
    parser.add_argument('--vibrato-rate', type=float, default=DEFAULT_VIBRATO_RATE,
                        metavar='HZ',
                        help=f'Vibrato speed in cycles per second (default: {DEFAULT_VIBRATO_RATE})')
    parser.add_argument('--slide-time', type=int, default=DEFAULT_SLIDE_TIME,
                        metavar='TICKS',
                        help='Length of slide glides into, out of and between notes, capped at '
                             f'the note length ({TICKS_PER_BEAT} per beat; default: '
                             f'{DEFAULT_SLIDE_TIME}; 0 = off)')
    parser.add_argument('--slide-distance', type=int, default=DEFAULT_SLIDE_DISTANCE,
                        metavar='SEMITONES',
                        help='How far slide-in and slide-out notes travel '
                             f'(default: {DEFAULT_SLIDE_DISTANCE})')
    parser.add_argument('--grace-length', type=int, default=DEFAULT_GRACE_LENGTH,
                        metavar='TICKS',
                        help='How long grace notes sound before (or on) the main beat '
                             f'({TICKS_PER_BEAT} per beat; default: {DEFAULT_GRACE_LENGTH} = '
                             'their written length, usually a 32nd = 60)')
    parser.add_argument('--grace-cut', type=int, default=DEFAULT_GRACE_CUT,
                        metavar='N',
                        help=f'Velocity reduction for grace notes (default: {DEFAULT_GRACE_CUT})')
    parser.add_argument('--no-harmonics', action='store_true',
                        help='Play harmonics at their fretted pitch (for synths with their '
                             'own harmonics sound) instead of the harmonic pitch')
    parser.add_argument('--harmonic-cut', type=int, default=DEFAULT_HARMONIC_CUT,
                        metavar='N',
                        help=f'Velocity reduction for harmonics (default: {DEFAULT_HARMONIC_CUT})')
    parser.add_argument('--channel-per-string', action='store_true',
                        help='Put each string on its own MIDI channel (highest string on '
                             'channel 1, skipping drum channel 10) so bends, vibrato and '
                             'slides only move the notes on their string. Needs a synth in '
                             'multitimbral or guitar (mono) mode with the same patch on each '
                             'channel. Drum and non-fretted tracks keep one channel.')
    parser.add_argument('--mpe', action='store_true',
                        help='MIDI Polyphonic Expression: one channel per string as an MPE '
                             'lower zone (MPE Configuration Message and program change on '
                             'manager channel 1, highest string on channel 2, the next on 3, '
                             '...; bend range on every string channel). For MPE synths. '
                             'Tracks that keep one channel (drums, multi-staff, no tuning) '
                             'are written as plain MIDI. Palm muting goes to MPE timbre '
                             '(CC74) on each note.')
    parser.add_argument('--open-timbre', type=int, default=DEFAULT_OPEN_TIMBRE, metavar='N',
                        help='With --mpe: timbre (CC74) for notes that are not palm muted '
                             f'(default: {DEFAULT_OPEN_TIMBRE})')
    parser.add_argument('--palm-mute-timbre', type=int, default=DEFAULT_PALM_MUTE_TIMBRE,
                        metavar='N',
                        help='With --mpe: timbre (CC74) for palm-muted notes '
                             f'(default: {DEFAULT_PALM_MUTE_TIMBRE})')
    parser.add_argument('--humanize', action=argparse.BooleanOptionalAction,
                        default=DEFAULT_HUMANIZE,
                        help='Small random and timing variations for a played feel '
                             '(default: on; --no-humanize plays the score exactly)')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED,
                        metavar='N',
                        help='Random seed for --humanize; the same seed gives the same '
                             f'output (default: {DEFAULT_SEED})')
    parser.add_argument('--velocity-spread', type=int, default=DEFAULT_VELOCITY_SPREAD,
                        metavar='N',
                        help='Humanize: vary each onset\'s velocity randomly by up to ±N; '
                             'all notes struck together vary alike, and accents / ghost '
                             f'notes still apply on top (default: {DEFAULT_VELOCITY_SPREAD}; 0 = off)')
    parser.add_argument('--strum-time', type=float, default=DEFAULT_STRUM_TIME,
                        metavar='MS',
                        help='Humanize: delay per string as the pick crosses a chord, low to '
                             'high on a downstroke and high to low on an upstroke '
                             f'(default: {DEFAULT_STRUM_TIME:g}; 0 = off)')
    parser.add_argument('--brush-time', type=float, default=DEFAULT_BRUSH_TIME,
                        metavar='MS',
                        help='Humanize: delay per string for a chord marked as a brush (strum) '
                             f'(default: {DEFAULT_BRUSH_TIME:g}; 0 = off)')
    parser.add_argument('--arpeggio-time', type=float, default=DEFAULT_ARPEGGIO_TIME,
                        metavar='MS',
                        help='Humanize: delay per string for a chord marked as an arpeggio '
                             f'(default: {DEFAULT_ARPEGGIO_TIME:g}; 0 = off)')
    parser.add_argument('--dynamic-velocity', type=parse_dynamic_velocity,
                        default=dict(DYNAMIC_VELOCITY), metavar='DYN:VEL,...',
                        help='Velocity for each dynamic marking, as comma-separated '
                             'DYNAMIC:VELOCITY pairs; levels not given keep their default '
                             '(default: ' + ','.join(f'{k}:{v}' for k, v in DYNAMIC_VELOCITY.items())
                             + ')')
    parser.add_argument('--velocity', type=int, default=None,
                        metavar='N',
                        help='Fixed note-on velocity 1-127 for every note, ignoring '
                             'dynamics, accents, ghost notes and the --*-cut options '
                             '(default: from the score)')
    args = parser.parse_args()

    # Clamp switch values into their valid ranges
    options = MidiOptions(
        velocity=max(1, min(127, args.velocity)) if args.velocity is not None else None,
        dynamic_velocity=args.dynamic_velocity,
        bend_range=max(1, min(24, args.bend_range)),
        hopo_cut=max(0, min(127, args.hopo_cut)),
        hopo_overlap=max(0, args.hopo_overlap),
        palm_mute_length=max(0.0, min(1.0, args.palm_mute_length)),
        palm_mute_cut=max(0, min(127, args.palm_mute_cut)),
        palm_mute_chords=args.palm_mute_chords,
        dead_note_length=max(1, args.dead_note_length),
        dead_note_cut=max(0, min(127, args.dead_note_cut)),
        vibrato_depth=max(0.0, args.vibrato_depth),
        vibrato_rate=max(0.0, args.vibrato_rate),
        slide_time=max(0, args.slide_time),
        slide_distance=max(0, args.slide_distance),
        grace_length=max(0, args.grace_length),
        grace_cut=max(0, min(127, args.grace_cut)),
        harmonics=not args.no_harmonics,
        harmonic_cut=max(0, min(127, args.harmonic_cut)),
        channel_per_string=args.channel_per_string,
        mpe=args.mpe,
        open_timbre=max(0, min(127, args.open_timbre)),
        palm_mute_timbre=max(0, min(127, args.palm_mute_timbre)),
        humanize=args.humanize,
        seed=args.seed,
        velocity_spread=max(0, min(127, args.velocity_spread)),
        strum_time=max(0.0, args.strum_time),
        brush_time=max(0.0, args.brush_time),
        arpeggio_time=max(0.0, args.arpeggio_time),
    )

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {input_path.name} ...")
    score = load_score(input_path)

    print(f"  {len(score.tracks)} track(s), {len(score.master_bars)} bar(s), "
          f"initial tempo {score.tempos[0].bpm:.1f} BPM")

    stem = input_path.stem
    converted = 0

    for track in score.tracks:
        label = f"[{track.id}] {track.name}"
        if not args.all_tracks and not track.is_tab:
            print(f"  Skip {label}  (not a tab track; use --all-tracks to include)")
            continue

        print(f"  Converting {label} ...")
        safe = safe_filename(track.name) or f"track{track.id}"
        out_file = output_dir / f"{stem}_track{track.id}_{safe}.mid"

        track_to_midi(track, score, str(out_file), options)
        converted += 1

    if converted == 0:
        print("\nNo tab tracks converted. "
              "(Use --all-tracks to include drums / non-fretted tracks.)")
    else:
        print(f"\nDone — {converted} MIDI file(s) written to {output_dir}/")


if __name__ == '__main__':
    main()
