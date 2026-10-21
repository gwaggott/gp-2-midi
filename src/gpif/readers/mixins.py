"""
Mixins shared by the content mixins of different file formats (GPIF in
gpif_xml.py; GP3-5 later): logic that turns format-neutral values into the
model's, so every format classifies tracks, measures rhythms and builds
pitch effects the same way.

  TrackClassificationMixin  is_drum / is_tab / is_fretted of a track
  RhythmMixin               note value, dots and tuplet → Rhythm
  PitchEffectsMixin         bend curves and harmonics
  DynamicsMixin             MIDI-style velocity → dynamic name (PPP … FFF)

ScoreBuilder isn't a mixin: it collects one file's objects under new ids, for
formats without ids of their own. Readers are shared and hold no state, so a
reader makes a new builder for each file it reads.
"""

import re
import xml.etree.ElementTree as ET

from ..model import Bar, Beat, Harmonic, MasterBar, Note, Rhythm, ScoreInfo, Tempo, Track, Voice
from ..score import Score

# Ticks per quarter note in Rhythm.ticks (and in gp2midi's output)
TICKS_PER_BEAT = 480

# Harmonic types (Harmonic.type). Natural harmonics are measured from the
# open string; the others from the fretted note.
HARMONIC_TYPES = ('natural', 'artificial', 'pinch', 'tap', 'semi', 'feedback')

# Instrument ids that name a fretted instrument: GP8 InstrumentSet/Type
# (electricGuitar, steelGuitar, nylonGuitar, electricBass, acousticBass, ...)
# and GP6 Instrument refs (e-gtr6, s-gtr6, n-gtr6, e-bass4, ...).
FRETTED_INSTRUMENT_RE = re.compile(r'guitar|gtr|bass|banjo|bnj|ukulele|ukl|mandolin|mdl', re.I)
NOT_FRETTED_INSTRUMENT_RE = re.compile(r'bassoon|contrabass|synth', re.I)


def is_fretted_instrument(instrument: str) -> bool:
    """True if an instrument id (e.g. GP8 type or GP6 ref) is fretted."""
    return (bool(FRETTED_INSTRUMENT_RE.search(instrument))
            and not NOT_FRETTED_INSTRUMENT_RE.search(instrument))


class TrackClassificationMixin:
    """What kind of track a tuning, MIDI channel and instrument id make."""

    @staticmethod
    def classify_track(tuning: list[int], channel: int,
                       instrument: str | None) -> tuple[bool, bool, bool]:
        """
        (is_drum, is_tab, is_fretted). A drum track is on MIDI channel 9
        (10 counting from 1). A tab track has a string tuning and isn't a drum
        track. GP8 gives vocal, keyboard and orchestral tracks a tuning too, so
        a fretted track is a tab track whose instrument is a guitar, bass, ...
        (any tab track when the file names no instrument).
        """
        is_drum = (channel == 9)
        is_tab = len(tuning) > 0 and not is_drum
        is_fretted = is_tab and (instrument is None or is_fretted_instrument(instrument))
        return is_drum, is_tab, is_fretted


class RhythmMixin:
    """Durations as Rhythm objects (quarter note = 1 beat)."""

    @staticmethod
    def rhythm(beats: float, dots: int = 0, tuplet: tuple[int, int] | None = None,
               element: ET.Element | None = None) -> Rhythm:
        """
        The Rhythm of a note value of `beats` (whole note 4.0, quarter 1.0,
        ...) with `dots` augmentation dots (× 1.5, × 1.75, ...; True counts as
        one) and in a tuplet (num, den): num notes in the time of den, so
        × den / num (a triplet is (3, 2); nested tuplets multiply out).
        """
        if dots:
            beats *= 2 - 0.5 ** dots
        if tuplet is not None:
            num, den = tuplet
            if den > 0 and num != den:
                beats = beats * den / num
        return Rhythm(beats=beats, ticks=int(round(beats * TICKS_PER_BEAT)), element=element)


class PitchEffectsMixin:
    """Bends and harmonics in the model's units."""

    @staticmethod
    def bend_curve(points: list[tuple[float, float]], position_scale: float,
                   semitone_scale: float) -> list[tuple[float, float]]:
        """
        A bend as [(fraction of the note 0-1, semitones), ...] from
        (position, value) points in a file's own units: position_scale is the
        position of the note's end, semitone_scale the value of a semitone.
        Sorted by position; points at the same position keep their order.
        """
        return [(position / position_scale, value / semitone_scale)
                for position, value in sorted(points, key=lambda p: p[0])]

    @staticmethod
    def harmonic(harmonic_type: str | None, fret: float | None) -> Harmonic | None:
        """A Harmonic, or None unless the type is known and the fret is set."""
        if harmonic_type in HARMONIC_TYPES and fret:
            return Harmonic(type=harmonic_type, fret=fret)
        return None


# Dynamic names, softest first (Beat.dynamic / Note.dynamic)
DYNAMICS = ('PPP', 'PP', 'P', 'MP', 'MF', 'F', 'FF', 'FFF')


class DynamicsMixin:
    """Dynamics from formats that store a velocity instead of a name."""

    # Guitar Pro 3-5 velocity for each dynamic: 15, 31, ... 127
    DYNAMIC_VELOCITIES = {name: 15 + 16 * i for i, name in enumerate(DYNAMICS)}

    @classmethod
    def dynamic_for_velocity(cls, velocity: int) -> str:
        """The dynamic whose velocity is nearest (the softer one on a tie)."""
        return min(DYNAMICS, key=lambda name: abs(cls.DYNAMIC_VELOCITIES[name] - velocity))


class ScoreBuilder:
    """
    Collects bars, voices, beats, notes and rhythms under ids handed out in
    order (from 0 per kind), then makes the Score. Equal rhythms share an id.
    """

    def __init__(self) -> None:
        self.bars: dict[int, Bar] = {}
        self.voices: dict[int, Voice] = {}
        self.beats: dict[int, Beat] = {}
        self.notes: dict[int, Note] = {}
        self.rhythms: dict[int, Rhythm] = {}
        self._rhythm_ids: dict[tuple[float, int], int] = {}

    @staticmethod
    def _add(table: dict, item) -> int:
        item_id = len(table)
        table[item_id] = item
        return item_id

    def add_bar(self, bar: Bar) -> int:
        return self._add(self.bars, bar)

    def add_voice(self, voice: Voice) -> int:
        return self._add(self.voices, voice)

    def add_beat(self, beat: Beat) -> int:
        return self._add(self.beats, beat)

    def add_note(self, note: Note) -> int:
        return self._add(self.notes, note)

    def rhythm_id(self, rhythm: Rhythm) -> int:
        """The id of an equal rhythm already added, else of this one."""
        key = (rhythm.beats, rhythm.ticks)
        if key not in self._rhythm_ids:
            self._rhythm_ids[key] = self._add(self.rhythms, rhythm)
        return self._rhythm_ids[key]

    def score(self, tracks: list[Track], master_bars: list[MasterBar], tempos: list[Tempo],
              info: ScoreInfo, source: object = None) -> Score:
        return Score(tracks=tracks, master_bars=master_bars, bars=self.bars,
                     voices=self.voices, beats=self.beats, notes=self.notes,
                     rhythms=self.rhythms, tempos=tempos, info=info, source=source)
