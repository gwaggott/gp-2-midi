"""Tests for gpif/theory.py: pitches, tuning names and harmonics."""

import pytest

from gpif import (
    Harmonic, Note, harmonic_interval, harmonic_pitch, midi_pitch, pitch_name, tuning_label,
)

# ---------------------------------------------------------------------------
# midi_pitch
# ---------------------------------------------------------------------------

STANDARD = [40, 45, 50, 55, 59, 64]


@pytest.mark.parametrize('string_idx, fret, expected', [
    (0, 0, 40),    # low E
    (5, 0, 64),    # high E
    (2, 7, 57),    # D string, 7th fret → A3
    (5, 24, 88),
])
def test_midi_pitch_string_zero_is_lowest(string_idx, fret, expected):
    assert midi_pitch(STANDARD, string_idx, fret) == expected


@pytest.mark.parametrize('string_idx', [-1, 6])
def test_midi_pitch_string_out_of_range(string_idx):
    assert midi_pitch(STANDARD, string_idx, 0) is None


def test_midi_pitch_above_midi_range():
    assert midi_pitch([120], 0, 8) is None
    assert midi_pitch([120], 0, 7) == 127


def test_midi_pitch_no_tuning():
    assert midi_pitch([], 0, 0) is None


@pytest.mark.parametrize('pitch, expected', [
    (60, 'C4'), (40, 'E2'), (23, 'B0'), (63, 'D#4'), (0, 'C-1'), (127, 'G9'),
])
def test_pitch_name(pitch, expected):
    assert pitch_name(pitch) == expected

# ---------------------------------------------------------------------------
# tuning_label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('tuning, instrument, expected', [
    ([40, 45, 50, 55, 59, 64], 'electricGuitar', 'Standard'),
    ([39, 44, 49, 54, 58, 63], 'electricGuitar', 'Eb Standard'),
    ([38, 43, 48, 53, 57, 62], 'electricGuitar', 'D Standard'),
    ([38, 45, 50, 55, 59, 64], 'electricGuitar', 'Drop D'),
    ([37, 44, 49, 54, 58, 63], 'electricGuitar', 'Drop Db'),
    ([35, 40, 45, 50, 55, 59, 64], 'electricGuitar', 'Standard'),
    ([28, 33, 38, 43], 'electricBass', 'Standard'),
    ([26, 33, 38, 43], 'e-bass4', 'Drop D'),
    ([23, 28, 33, 38, 43], 'electricBass', 'Standard'),
    ([38, 45, 50, 55, 57, 62], 'steelGuitar', None),       # DADGAD
    ([52, 57, 62, 67, 59, 64], 'steelGuitar', None),       # Nashville
    ([28, 33, 38, 43], 'electricGuitar', None),            # no 4-string guitar standard
    ([40, 45, 50, 55, 59, 64], None, 'Standard'),
])
def test_tuning_label(tuning, instrument, expected):
    assert tuning_label(tuning, instrument) == expected

# ---------------------------------------------------------------------------
# Harmonics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('fret, semitones', [
    (12, 12), (7, 19), (19, 19), (5, 24), (24, 24),
    (4, 28), (9, 28), (16, 28), (3.2, 31), (2.7, 34), (2.4, 36),
])
def test_harmonic_interval_nodes(fret, semitones):
    assert harmonic_interval(fret) == semitones


@pytest.mark.parametrize('fret', [0, -1, 1, 12.5])
def test_harmonic_interval_no_node(fret):
    assert harmonic_interval(fret) == 0


def h_note(htype: str, hfret: float, string: int, fret: int) -> Note:
    return Note(string=string, fret=fret, harmonic=Harmonic(type=htype, fret=hfret))


def test_natural_harmonic_counts_from_open_string():
    # D string (50), touched at the 7th fret: open + 19
    assert harmonic_pitch(STANDARD, h_note('natural', 7, 2, 7), fretted=57) == 69
    # At the 12th fret the harmonic equals the fretted pitch
    assert harmonic_pitch(STANDARD, h_note('natural', 12, 2, 12), fretted=62) == 62


def test_natural_harmonic_without_tuning_uses_fretted_minus_fret():
    assert harmonic_pitch([], h_note('natural', 7, 2, 7), fretted=57) == 69


@pytest.mark.parametrize('htype', ['artificial', 'pinch', 'tap', 'semi', 'feedback'])
def test_other_harmonics_count_from_fretted_pitch(htype):
    # High E string, 4th fret (68), harmonic 12 frets above
    assert harmonic_pitch(STANDARD, h_note(htype, 12, 5, 4), fretted=68) == 80


def test_harmonic_pitch_none_cases():
    assert harmonic_pitch(STANDARD, Note(), fretted=40) is None
    assert harmonic_pitch(STANDARD, h_note('artificial', 12.5, 0, 0), fretted=40) is None   # no node
    assert harmonic_pitch(STANDARD, h_note('artificial', 2.4, 5, 24), fretted=120) is None   # > 127
