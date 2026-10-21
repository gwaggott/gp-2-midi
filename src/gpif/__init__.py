"""
Read Guitar Pro files into frozen dataclasses: GP6/7/8 (GPIF XML in a .gp /
.gpx container, or raw .gpif / .xml) and GP3/4/5 (.gp3 / .gp4 / .gp5,
through PyGuitarPro, needed only for those). Each file format has a reader class
(gpif.readers); load_score picks one by the file's content.

    from gpif import load_score
    score = load_score('song.gp')        # every section, parsed
    for track in score.tracks: ...

Modules:
  readers    a ScoreReader class per file format, built from container,
             content and shared mixins; load_score, reader_for, load_gpif_xml
             (the GPIF XML root of a GP6/7/8 file); readers.gpif_xml has the
             parse_* functions (one GPIF section each, as model objects)
  model      the data types: Track, Staff, MasterBar, Bar, Voice, Beat,
             Note, Harmonic, Rhythm, Tempo, ScoreInfo (frozen dataclasses);
             each keeps its source XML in .element, and Note / Beat have
             .properties (raw <Property> values) for what isn't parsed
  score      Score, track_bars
  theory     pitch, tuning and harmonic helpers (midi_pitch, pitch_name,
             tuning_label, harmonic_pitch, ...)

Everything listed in __all__ can be imported from the package directly.
"""

from .model import (
    Bar,
    Beat,
    Harmonic,
    MasterBar,
    Note,
    Rhythm,
    ScoreInfo,
    Staff,
    Tempo,
    Track,
    Voice,
    property_value,
)
from .readers import (
    DynamicsMixin,
    Gp3Reader,
    Gp4Reader,
    Gp5Reader,
    Gp6Reader,
    Gp7Reader,
    GpifContentMixin,
    GpifXmlReader,
    PitchEffectsMixin,
    PyGuitarProMixin,
    RhythmMixin,
    ScoreBuilder,
    ScoreReader,
    TrackClassificationMixin,
    load_gpif_xml,
    load_score,
    reader_for,
)
from .readers.gpif_xml import (
    ACCENT_HEAVY,
    ACCENT_NORMAL,
    ACCENT_STACCATO,
    NOTE_VALUE_BEATS,
    SLIDE_IN_ABOVE,
    SLIDE_IN_BELOW,
    SLIDE_LEGATO,
    SLIDE_OUT_DOWN,
    SLIDE_OUT_UP,
    SLIDE_SHIFT,
    bend_points,
    parse_bars,
    parse_beats,
    parse_master_bars,
    parse_notes,
    parse_rhythms,
    parse_score,
    parse_score_info,
    parse_tempos,
    parse_tracks,
    parse_voices,
)
from .readers.gp345 import gm_instrument
from .readers.mixins import DYNAMICS, HARMONIC_TYPES, TICKS_PER_BEAT, is_fretted_instrument
from .score import Score, track_bars
from .theory import (
    harmonic_interval,
    harmonic_pitch,
    midi_pitch,
    pitch_name,
    tuning_label,
)

__all__ = [
    # model
    'Bar', 'Beat', 'Harmonic', 'MasterBar', 'Note', 'Rhythm', 'ScoreInfo', 'Staff',
    'Tempo', 'Track', 'Voice', 'property_value',
    # readers
    'DynamicsMixin', 'Gp3Reader', 'Gp4Reader', 'Gp5Reader', 'Gp6Reader', 'Gp7Reader',
    'GpifContentMixin', 'GpifXmlReader', 'PitchEffectsMixin', 'PyGuitarProMixin',
    'RhythmMixin', 'ScoreBuilder', 'ScoreReader', 'TrackClassificationMixin',
    'load_gpif_xml', 'load_score', 'reader_for',
    # readers.gp345
    'gm_instrument',
    # readers.gpif_xml: GPIF constants and the parse_* functions
    'ACCENT_HEAVY', 'ACCENT_NORMAL', 'ACCENT_STACCATO', 'NOTE_VALUE_BEATS',
    'SLIDE_IN_ABOVE', 'SLIDE_IN_BELOW', 'SLIDE_LEGATO', 'SLIDE_OUT_DOWN', 'SLIDE_OUT_UP',
    'SLIDE_SHIFT', 'bend_points', 'parse_bars', 'parse_beats', 'parse_master_bars',
    'parse_notes', 'parse_rhythms', 'parse_score', 'parse_score_info', 'parse_tempos',
    'parse_tracks', 'parse_voices',
    # readers.mixins
    'DYNAMICS', 'HARMONIC_TYPES', 'TICKS_PER_BEAT', 'is_fretted_instrument',
    # score
    'Score', 'track_bars',
    # theory
    'harmonic_interval', 'harmonic_pitch', 'midi_pitch', 'pitch_name', 'tuning_label',
]
