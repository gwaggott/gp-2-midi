"""Tests for the mixins shared by the readers' content mixins (gpif/readers/mixins.py)."""

import pytest

from conftest import gpif
from gpif import (
    DYNAMICS,
    DynamicsMixin,
    GpifContentMixin,
    Harmonic,
    PitchEffectsMixin,
    PyGuitarProMixin,
    Rhythm,
    RhythmMixin,
    ScoreBuilder,
    TICKS_PER_BEAT,
    TrackClassificationMixin,
    is_fretted_instrument,
)
from gpif import Bar, Beat, MasterBar, Note, ScoreInfo, Tempo, Track, Voice

GUITAR = [40, 45, 50, 55, 59, 64]

# ---------------------------------------------------------------------------
# TrackClassificationMixin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('tuning, channel, instrument, expected', [
    (GUITAR, 0, 'electricGuitar', (False, True, True)),
    (GUITAR, 0, None, (False, True, True)),            # no instrument named: fretted
    (GUITAR, 0, 'voice', (False, True, False)),         # GP8 vocal track with a tuning
    (GUITAR, 9, 'electricGuitar', (True, False, False)),
    ([], 0, 'electricGuitar', (False, False, False)),   # no tuning: not a tab track
])
def test_classify_track(tuning, channel, instrument, expected):
    assert TrackClassificationMixin.classify_track(tuning, channel, instrument) == expected


def test_is_fretted_instrument():
    assert is_fretted_instrument('e-bass4')
    assert not is_fretted_instrument('bassoon')
    assert not is_fretted_instrument('synthBass')

# ---------------------------------------------------------------------------
# RhythmMixin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('beats, dotted, tuplet, expected', [
    (1.0, False, None, 1.0),
    (1.0, True, None, 1.5),
    (0.5, False, (3, 2), 1 / 3),
    (0.5, True, (3, 2), 0.5),
    (1.0, False, (2, 2), 1.0),        # num == den: no change
    (1.0, False, (3, 0), 1.0),        # bad tuplet ignored
])
def test_rhythm(beats, dotted, tuplet, expected):
    rhythm = RhythmMixin.rhythm(beats, dotted, tuplet)
    assert rhythm == Rhythm(beats=pytest.approx(expected), ticks=round(expected * TICKS_PER_BEAT))

# ---------------------------------------------------------------------------
# PitchEffectsMixin
# ---------------------------------------------------------------------------

def test_bend_curve_scales_and_sorts_stably():
    points = [(100, 100), (0, 0), (50, 100), (50, 50)]
    assert PitchEffectsMixin.bend_curve(points, position_scale=100, semitone_scale=50) == [
        (0.0, 0.0), (0.5, 2.0), (0.5, 1.0), (1.0, 2.0)]


def test_bend_curve_other_units():
    # GP3-5 style: positions 0-12, values in quarter tones
    assert PitchEffectsMixin.bend_curve([(0, 0), (6, 4), (12, 4)], 12, 2) == [
        (0.0, 0.0), (0.5, 2.0), (1.0, 2.0)]


def test_harmonic():
    assert PitchEffectsMixin.harmonic('natural', 12.0) == Harmonic(type='natural', fret=12.0)
    assert PitchEffectsMixin.harmonic('unknown', 12.0) is None
    assert PitchEffectsMixin.harmonic('natural', None) is None
    assert PitchEffectsMixin.harmonic(None, 12.0) is None

# ---------------------------------------------------------------------------
# DynamicsMixin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('velocity, expected', [
    (15, 'PPP'), (95, 'F'), (127, 'FFF'), (0, 'PPP'), (100, 'F'), (104, 'FF'),
    (87, 'MF'),            # halfway between MF (79) and F (95): the softer
])
def test_dynamic_for_velocity(velocity, expected):
    assert DynamicsMixin.dynamic_for_velocity(velocity) == expected


def test_dynamic_velocities_cover_every_dynamic():
    assert list(DynamicsMixin.DYNAMIC_VELOCITIES) == list(DYNAMICS)

# ---------------------------------------------------------------------------
# ScoreBuilder
# ---------------------------------------------------------------------------

def test_score_builder_ids_and_shared_rhythms():
    builder = ScoreBuilder()
    quarter = RhythmMixin.rhythm(1.0)
    rhythm_ids = [builder.rhythm_id(quarter), builder.rhythm_id(RhythmMixin.rhythm(0.5)),
                  builder.rhythm_id(RhythmMixin.rhythm(1.0))]
    assert rhythm_ids == [0, 1, 0]
    note_ids = [builder.add_note(Note(fret=f)) for f in (1, 2)]
    beat_id = builder.add_beat(Beat(rhythm_id=0, note_ids=note_ids))
    voice_id = builder.add_voice(Voice(beat_ids=[beat_id]))
    bar_id = builder.add_bar(Bar(voice_ids=[voice_id]))
    assert (note_ids, beat_id, voice_id, bar_id) == ([0, 1], 0, 0, 0)

    track = Track(id=0)
    score = builder.score([track], [MasterBar(bar_ids=[bar_id])], [Tempo()],
                          ScoreInfo(title='T'), source='raw')
    assert score.notes[1].fret == 2 and score.rhythms[0] == quarter
    assert score.info.title == 'T' and score.source == 'raw' and score.root is None


def test_scores_differing_only_in_source_are_equal():
    a = ScoreBuilder().score([], [], [], ScoreInfo(), source='a')
    b = ScoreBuilder().score([], [], [], ScoreInfo(), source='b')
    assert a == b

# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------

def test_content_mixins_use_the_shared_mixins():
    for mixin in (TrackClassificationMixin, RhythmMixin, PitchEffectsMixin):
        assert issubclass(GpifContentMixin, mixin)
        assert issubclass(PyGuitarProMixin, mixin)
    assert issubclass(PyGuitarProMixin, DynamicsMixin)


def test_shared_mixins_overridable_per_format():
    # A format can change a shared rule by overriding its method
    class NoFrettedParser(GpifContentMixin):
        @staticmethod
        def classify_track(tuning, channel, instrument):
            return False, True, False

    root = gpif('<Tracks><Track id="0"><Properties><Property name="Tuning">'
                '<Pitches>40 45 50 55 59 64</Pitches></Property></Properties></Track></Tracks>')
    assert GpifContentMixin().parse_tracks(root)[0].is_fretted
    assert not NoFrettedParser().parse_tracks(root)[0].is_fretted
