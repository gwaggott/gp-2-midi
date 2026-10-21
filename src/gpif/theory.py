"""Pitch, tuning and harmonic helpers for fretted instruments."""

import math

from .model import Note


NOTE_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def pitch_name(pitch: int) -> str:
    """Scientific pitch name of a MIDI pitch: 60 → 'C4', 40 → 'E2'."""
    return f'{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}'


# Standard tunings by string count, lowest string first
STANDARD_GUITAR = {
    6: [40, 45, 50, 55, 59, 64],            # E2 A2 D3 G3 B3 E4
    7: [35, 40, 45, 50, 55, 59, 64],        # B1 + 6-string
    8: [30, 35, 40, 45, 50, 55, 59, 64],    # F#1 + 7-string
}
STANDARD_BASS = {
    4: [28, 33, 38, 43],                    # E1 A1 D2 G2
    5: [23, 28, 33, 38, 43],                # B0 + 4-string
    6: [23, 28, 33, 38, 43, 48],            # + C3
}

# Tuning names use flats, as in "Eb Standard"
FLAT_NAMES = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B')


def tuning_label(tuning: list[int], instrument: str | None) -> str | None:
    """
    Name a standard-based tuning: 'Standard', 'Eb Standard' (every string
    shifted alike), 'Drop D' (lowest string a further tone down). Returns
    None for other tunings or string counts without a known standard.
    """
    is_bass = instrument is not None and 'bass' in instrument.lower()
    standard = (STANDARD_BASS if is_bass else STANDARD_GUITAR).get(len(tuning))
    if standard is None:
        return None
    diffs = [t - s for t, s in zip(tuning, standard)]
    shift = diffs[-1]
    root = FLAT_NAMES[tuning[0] % 12]
    if any(d != shift for d in diffs[1:]):
        return None
    if diffs[0] == shift:
        return 'Standard' if shift == 0 else f'{root} Standard'
    if diffs[0] == shift - 2:
        return f'Drop {root}'
    return None


def midi_pitch(tuning: list[int], string_idx: int, fret: int) -> int | None:
    """
    Calculate MIDI pitch number.

    In GPIF, string 0 is the *lowest*-pitched string, matching the tuning
    list order (standard guitar: [40, 45, 50, 55, 59, 64]).
    """
    if 0 <= string_idx < len(tuning):
        pitch = tuning[string_idx] + fret
        if 0 <= pitch <= 127:
            return pitch
    return None


# A harmonic node must lie within this fraction of the string length of k/n
# (≈ 8 mm on a 650 mm scale), and only partials up to this n are considered.
HARMONIC_NODE_TOLERANCE = 0.012
HARMONIC_MAX_PARTIAL = 12


def harmonic_interval(fret: float) -> int:
    """
    Semitones a harmonic touched at `fret` sounds above the open (or fretted)
    string, or 0 if there's no harmonic node there.

    Fret f is a fraction d = 1 - 2^(-f/12) of the string from the nut. A
    harmonic sounds where d ≈ k/n, giving the n-th partial, 12·log2(n)
    semitones up (rounded): 12 → +12, 7 / 19 → +19, 5 / 24 → +24,
    4 / 9 / 16 → +28, 3.2 → +31. The smallest matching n wins.
    """
    if fret <= 0:
        return 0
    d = 1 - 2 ** (-fret / 12)
    for n in range(2, HARMONIC_MAX_PARTIAL + 1):
        k = round(d * n)
        if 1 <= k < n and abs(d - k / n) < HARMONIC_NODE_TOLERANCE:
            return round(12 * math.log2(n))
    return 0


def harmonic_pitch(tuning: list[int], note: Note, fretted: int) -> int | None:
    """
    MIDI pitch a harmonic note sounds at, or None if it has no harmonic (or
    no node at its harmonic fret, or the result is outside 0–127).

    Natural harmonics count from the open string (with any capo: `fretted`
    minus the fret); artificial, pinch, tap, semi and feedback harmonics
    from the fretted pitch.
    """
    harmonic = note.harmonic
    if not harmonic:
        return None
    interval = harmonic_interval(harmonic.fret)
    if not interval:
        return None
    if harmonic.type == 'natural':
        base = fretted - note.fret
    else:
        base = fretted
    pitch = base + interval
    return pitch if 0 <= pitch <= 127 else None
