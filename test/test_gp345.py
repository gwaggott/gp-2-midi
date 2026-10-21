"""
Tests for the GP3 / GP4 / GP5 readers (gpif/readers/gp345.py).

Songs are built in code with PyGuitarPro and written to tmp_path in each
version, then read back through load_score. The GP3-5 files in in/ are for
end-to-end checks only and aren't read here (docs/formats.md).
"""

import sys

import guitarpro as gp
import pytest

from gp2midi import MidiOptions, track_to_midi
from gpif import (
    Gp3Reader,
    Gp4Reader,
    Gp5Reader,
    Score,
    TICKS_PER_BEAT,
    Harmonic,
    gm_instrument,
    load_gpif_xml,
    load_score,
    midi_pitch,
    reader_for,
    track_bars,
)

VERSIONS = ['gp3', 'gp4', 'gp5']
STANDARD = [40, 45, 50, 55, 59, 64]


def add_beat(voice, notes=(), value=4, dotted=False, tuplet=None, status=None):
    """
    Append a beat: notes are (GP string number 1 = highest, fret, extra Note
    fields such as velocity or type).
    """
    beat = gp.Beat(voice, duration=gp.Duration(value=value, isDotted=dotted),
                   status=status or (gp.BeatStatus.normal if notes else gp.BeatStatus.rest))
    if tuplet:
        beat.duration.tuplet = gp.Tuplet(enters=tuplet[0], times=tuplet[1])
    for string, fret, fields in notes:
        beat.notes.append(gp.Note(beat, value=fret, string=string,
                                  **{'type': gp.NoteType.normal, **fields}))
    voice.beats.append(beat)
    return beat


def new_song(bars=1, **fields):
    song = gp.Song(**fields)
    for _ in range(bars - 1):
        song.newMeasure()
    return song


def voice(song, bar=0, track=0, index=0):
    return song.tracks[track].measures[bar].voices[index]


def write_read(tmp_path, song, ext) -> Score:
    path = tmp_path / f'song.{ext}'
    gp.write(song, str(path))
    return load_score(path)


def one_bar(tmp_path, ext, notes, **beat_fields) -> Score:
    """A song with one beat (then a rest to fill the bar)."""
    song = new_song()
    add_beat(voice(song), notes, **beat_fields)
    return write_read(tmp_path, song, ext)


def beats_of(score, track=0, bar=0, voice_index=0):
    bar_obj = track_bars(score, score.tracks[track])[bar]
    return [score.beats[b] for b in score.voices[bar_obj.voice_ids[voice_index]].beat_ids]

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ext, reader_class', [
    ('gp3', Gp3Reader), ('gp4', Gp4Reader), ('gp5', Gp5Reader)])
def test_reader_for_detects_version(tmp_path, ext, reader_class):
    path = tmp_path / f'song.{ext}'
    gp.write(new_song(), str(path))
    assert type(reader_for(path)) is reader_class
    renamed = path.rename(tmp_path / 'song.bin')         # content, not suffix
    assert type(reader_for(renamed)) is reader_class


def test_load_gpif_xml_refuses_gp5(tmp_path):
    path = tmp_path / 'song.gp5'
    gp.write(new_song(), str(path))
    with pytest.raises(ValueError, match='GP5 file has no GPIF XML'):
        load_gpif_xml(path)


def test_missing_pyguitarpro(tmp_path, monkeypatch):
    path = tmp_path / 'song.gp5'
    gp.write(new_song(), str(path))
    monkeypatch.setitem(sys.modules, 'guitarpro', None)     # import fails
    with pytest.raises(ImportError, match='pip install pyguitarpro'):
        load_score(path)

# ---------------------------------------------------------------------------
# Song, tracks and bars
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ext', VERSIONS)
def test_info(tmp_path, ext):
    song = new_song(title='Title', artist='Artist', album='Album', tab='Tabber',
                    notice=['line 1', 'line 2'])
    score = write_read(tmp_path, song, ext)
    assert (score.info.title, score.info.artist, score.info.album, score.info.tabber) == (
        'Title', 'Artist', 'Album', 'Tabber')
    assert score.info.notices == 'line 1\nline 2'
    assert isinstance(score.source, gp.Song) and score.root is None


@pytest.mark.parametrize('ext', VERSIONS)
def test_tracks(tmp_path, ext):
    song = new_song()
    guitar = song.tracks[0]
    guitar.name, guitar.offset = 'Guitar', 2
    guitar.channel = gp.MidiChannel(channel=0, effectChannel=1, instrument=30)
    guitar.strings = [gp.GuitarString(n, v) for n, v in enumerate([62, 57, 53, 48, 43, 38], 1)]
    bass = gp.Track(song, number=2, name='Bass',
                    channel=gp.MidiChannel(channel=2, effectChannel=3, instrument=33),
                    strings=[gp.GuitarString(n, v) for n, v in enumerate([43, 38, 33, 28], 1)])
    vocal = gp.Track(song, number=3, name='Vocal',
                     channel=gp.MidiChannel(channel=4, effectChannel=5, instrument=53))
    drums = gp.Track(song, number=4, name='Drums', isPercussionTrack=True,
                     channel=gp.MidiChannel(channel=9, effectChannel=9, instrument=0))
    song.tracks += [bass, vocal, drums]
    score = write_read(tmp_path, song, ext)

    t = score.tracks
    assert [x.id for x in t] == [0, 1, 2, 3]
    assert [x.bar_index for x in t] == [0, 1, 2, 3]
    assert (t[0].name, t[0].tuning, t[0].capo, t[0].program, t[0].channel) == (
        'Guitar', [38, 43, 48, 53, 57, 62], 2, 30, 0)
    assert t[1].tuning == [28, 33, 38, 43]
    assert [x.instrument for x in t] == ['Distortion Guitar', 'Electric Bass (finger)',
                                         'Ensemble', 'Piano']
    assert [(x.is_drum, x.is_tab, x.is_fretted) for x in t] == [
        (False, True, True), (False, True, True), (False, True, False), (True, False, False)]
    assert t[3].channel == 9


@pytest.mark.parametrize('ext', VERSIONS)
def test_master_bars(tmp_path, ext):
    song = new_song(bars=2)
    song.measureHeaders[1].timeSignature.numerator = 3
    song.tracks.append(gp.Track(song, number=2))
    score = write_read(tmp_path, song, ext)
    assert [(mb.numerator, mb.denominator) for mb in score.master_bars] == [(4, 4), (3, 4)]
    assert all(len(mb.bar_ids) == 2 for mb in score.master_bars)
    assert len({b for mb in score.master_bars for b in mb.bar_ids}) == 4


def test_gm_instrument():
    assert gm_instrument(25) == 'Acoustic Guitar (steel)'
    assert gm_instrument(105) == 'Banjo'
    assert gm_instrument(0) == 'Piano'
    assert gm_instrument(81) == 'Synth Lead'

# ---------------------------------------------------------------------------
# Voices, beats and rhythm
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ext', VERSIONS)
def test_rhythms(tmp_path, ext):
    song = new_song()
    v = voice(song)
    add_beat(v, [(1, 0, {})], value=4)
    add_beat(v, [(1, 0, {})], value=8, dotted=True)
    add_beat(v, [(1, 0, {})], value=16)
    for _ in range(3):
        add_beat(v, [(1, 0, {})], value=8, tuplet=(3, 2))
    add_beat(v, value=4)                                    # rest
    score = write_read(tmp_path, song, ext)
    beats = beats_of(score)
    ticks = [score.rhythms[b.rhythm_id].ticks for b in beats]
    assert ticks == [480, 360, 120, 160, 160, 160, 480]
    assert [b.is_rest for b in beats] == [False] * 6 + [True]
    assert beats[-1].note_ids == [] and beats[-1].dynamic is None
    assert len({b.rhythm_id for b in beats[3:6]}) == 1     # equal rhythms share an id


def test_gp5_second_voice(tmp_path):
    song = new_song(bars=2)
    add_beat(voice(song, bar=0), [(1, 0, {})], value=1)
    add_beat(voice(song, bar=1), [(1, 0, {})], value=1)
    add_beat(voice(song, bar=1, index=1), [(6, 0, {})], value=1)
    score = write_read(tmp_path, song, 'gp5')
    bars = track_bars(score, score.tracks[0])
    assert [len(b.voice_ids) for b in bars] == [1, 2]      # empty voice 2 left out


@pytest.mark.parametrize('ext', VERSIONS)
def test_empty_bar_has_no_voices(tmp_path, ext):
    score = write_read(tmp_path, new_song(bars=2), ext)
    assert [len(b.voice_ids) for b in track_bars(score, score.tracks[0])] == [0, 0]

# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ext', VERSIONS)
def test_strings_and_pitch(tmp_path, ext):
    score = one_bar(tmp_path, ext, [(1, 3, {}), (6, 5, {}), (3, 0, {})])
    notes = [score.notes[n] for n in beats_of(score)[0].note_ids]
    by_string = {n.string: n.fret for n in notes}
    assert by_string == {5: 3, 0: 5, 3: 0}                 # GP string 1 = model string 5
    assert sorted(midi_pitch(STANDARD, n.string, n.fret) for n in notes) == [45, 55, 67]
    assert sorted(n.midi for n in notes) == [45, 55, 67]      # the sounding pitch


@pytest.mark.parametrize('ext', VERSIONS)
def test_capo_raises_the_pitch(tmp_path, ext):
    # GP3-5 frets count from the capo (checked on the files in in/: capo
    # tracks only fit the other tracks' pitches with the capo added)
    song = new_song()
    song.tracks[0].offset = 2
    beat = add_beat(voice(song), [(3, 5, {})])
    beat.notes[0].effect.grace = gp.GraceEffect(fret=3, duration=32)
    score = write_read(tmp_path, song, ext)
    grace_beat, main_beat = beats_of(score)[:2]
    assert score.tracks[0].capo == 2
    assert notes_of(score, main_beat)[0].midi == 55 + 2 + 5
    assert notes_of(score, grace_beat)[0].midi == 55 + 2 + 3


def test_capo_natural_harmonic_through_gp2midi(tmp_path):
    # A natural harmonic at the 12th fret above a capo at 2 sounds an octave
    # above the capoed open string
    import mido
    song = new_song()
    song.tracks[0].offset = 2
    add_beat(voice(song), [(1, 12, {})]).notes[0].effect.harmonic = gp.NaturalHarmonic()
    score = write_read(tmp_path, song, 'gp5')
    out = tmp_path / 'out.mid'
    track_to_midi(score.tracks[0], score, str(out), MidiOptions(humanize=False))
    notes = [m.note for m in mido.MidiFile(out).tracks[0] if m.type == 'note_on' and m.velocity]
    assert notes == [64 + 2 + 12]


@pytest.mark.parametrize('ext', VERSIONS)
def test_tie_and_dead(tmp_path, ext):
    song = new_song()
    v = voice(song)
    add_beat(v, [(2, 7, {})])
    add_beat(v, [(2, 0, {'type': gp.NoteType.tie})])
    add_beat(v, [(2, 0, {'type': gp.NoteType.dead})])
    score = write_read(tmp_path, song, ext)
    notes = [score.notes[b.note_ids[0]] for b in beats_of(score)[:3]]
    assert [(n.is_tie_dest, n.dead, n.fret) for n in notes] == [
        (False, False, 7), (True, False, 7), (False, True, 0)]   # a tie keeps its fret


@pytest.mark.parametrize('ext', VERSIONS)
def test_dynamics(tmp_path, ext):
    score = one_bar(tmp_path, ext, [(1, 0, {'velocity': 95}), (2, 0, {'velocity': 47}),
                                    (3, 0, {'velocity': 95})])
    beat = beats_of(score)[0]
    assert [score.notes[n].dynamic for n in beat.note_ids] == ['F', 'P', 'F']
    assert beat.dynamic == 'F'                              # the most common

# ---------------------------------------------------------------------------
# Tempo
# ---------------------------------------------------------------------------

def tempo_change(beat, bpm):
    beat.effect.mixTableChange = gp.MixTableChange(tempo=gp.MixTableItem(value=bpm))


@pytest.mark.parametrize('ext', VERSIONS)
def test_tempos(tmp_path, ext):
    song = new_song(bars=2, tempo=90)
    add_beat(voice(song, bar=0), [(1, 0, {})], value=1)
    v = voice(song, bar=1)
    tempo_change(add_beat(v, [(1, 0, {})], value=2), 120)
    tempo_change(add_beat(v, [(1, 0, {})], value=2), 100)
    score = write_read(tmp_path, song, ext)
    assert [(t.bar, t.position, t.bpm) for t in score.tempos] == [
        (0, 0.0, 90.0), (1, 0.0, 120.0), (1, 0.5, 100.0)]


def test_tempo_change_at_start_replaces_song_tempo(tmp_path):
    song = new_song(tempo=90)
    tempo_change(add_beat(voice(song), [(1, 0, {})], value=1), 140)
    score = write_read(tmp_path, song, 'gp5')
    assert [(t.bar, t.position, t.bpm) for t in score.tempos] == [(0, 0.0, 140.0)]

# ---------------------------------------------------------------------------
# Through gp2midi
# ---------------------------------------------------------------------------

def test_gp5_to_midi(tmp_path):
    import mido
    song = new_song(tempo=120)
    v = voice(song)
    add_beat(v, [(6, 0, {'velocity': 95}), (5, 2, {'velocity': 47})])
    add_beat(v, [(1, 0, {'velocity': 127})], value=2)
    add_beat(v, [(1, 0, {'type': gp.NoteType.tie})])
    score = write_read(tmp_path, song, 'gp5')
    out = tmp_path / 'out.mid'
    track_to_midi(score.tracks[0], score, str(out), MidiOptions(humanize=False))
    tick, events = 0, []
    for msg in mido.MidiFile(out).tracks[0]:
        tick += msg.time
        if msg.type in ('note_on', 'note_off'):
            events.append((tick, msg.type, msg.note, msg.velocity))
    ons = [e for e in events if e[1] == 'note_on']
    # Each note keeps its own dynamic: F 96, P 48, FFF 127 (gp2midi's velocities)
    assert sorted(ons) == [(0, 'note_on', 40, 96), (0, 'note_on', 47, 48),
                           (TICKS_PER_BEAT, 'note_on', 64, 127)]
    # The tied quarter extends the half note to the end of the bar
    assert (4 * TICKS_PER_BEAT, 'note_off', 64, 0) in events

# ---------------------------------------------------------------------------
# Articulations (step 4). What each version can store: GP3 has ghost notes,
# vibrato and shift slides (any slide reads back as one); GP4 adds accents
# (not heavy), staccato, palm muting and all slides, one per note; GP5 has
# everything, including a slide in and a slide out on one note.
# ---------------------------------------------------------------------------

NOTE_FLAGS = [
    # (PyGuitarPro NoteEffect field, model field, model value, versions that store it)
    ('accentuatedNote', 'accent', 'normal', ['gp4', 'gp5']),
    ('heavyAccentuatedNote', 'accent', 'heavy', ['gp5']),
    ('ghostNote', 'ghost', True, VERSIONS),
    ('staccato', 'staccato', True, ['gp4', 'gp5']),
    ('palmMute', 'palm_muted', True, ['gp4', 'gp5']),
    ('vibrato', 'vibrato', 'slight', VERSIONS),
]


def note_with_effect(tmp_path, ext, beat_effect=None, **effect):
    """The model Note of a one-note song whose note has these effect fields."""
    song = new_song()
    beat = add_beat(voice(song), [(2, 5, {})])
    for field, value in effect.items():
        setattr(beat.notes[0].effect, field, value)
    for field, value in (beat_effect or {}).items():
        setattr(beat.effect, field, value)
    score = write_read(tmp_path, song, ext)
    return score.notes[beats_of(score)[0].note_ids[0]]


@pytest.mark.parametrize('ext', VERSIONS)
@pytest.mark.parametrize('gp_field, field, value, versions', NOTE_FLAGS,
                         ids=[f[0] for f in NOTE_FLAGS])
def test_note_flags(tmp_path, ext, gp_field, field, value, versions):
    if ext not in versions:
        pytest.skip(f'{ext} has no {gp_field}')
    note = note_with_effect(tmp_path, ext, **{gp_field: True})
    assert getattr(note, field) == value
    plain = note_with_effect(tmp_path, ext)
    assert getattr(plain, field) in (None, False)


@pytest.mark.parametrize('ext', VERSIONS)
def test_beat_vibrato_is_wide(tmp_path, ext):
    # GP's beat-level flag is "wide vibrato"; it wins over the note's own
    note = note_with_effect(tmp_path, ext, beat_effect={'vibrato': True}, vibrato=True)
    assert note.vibrato == 'wide'


@pytest.mark.parametrize('ext', ['gp4', 'gp5'])
@pytest.mark.parametrize('slide, slide_in, slide_out', [
    ('shiftSlideTo', None, 'shift'),
    ('legatoSlideTo', None, 'legato'),
    ('outDownwards', None, 'down'),
    ('outUpwards', None, 'up'),
    ('intoFromBelow', 'below', None),
    ('intoFromAbove', 'above', None),
])
def test_slides(tmp_path, ext, slide, slide_in, slide_out):
    note = note_with_effect(tmp_path, ext, slides=[gp.SlideType[slide]])
    assert (note.slide_in, note.slide_out) == (slide_in, slide_out)


def test_gp3_slide_is_a_shift_slide(tmp_path):
    note = note_with_effect(tmp_path, 'gp3', slides=[gp.SlideType.legatoSlideTo])
    assert (note.slide_in, note.slide_out) == (None, 'shift')


def test_gp5_slide_in_and_out(tmp_path):
    note = note_with_effect(tmp_path, 'gp5',
                            slides=[gp.SlideType.intoFromBelow, gp.SlideType.outDownwards])
    assert (note.slide_in, note.slide_out) == ('below', 'down')


def test_gp5_articulations_through_gp2midi(tmp_path):
    # Palm mute: half length and softer; accent: louder; staccato: half length
    import mido
    song = new_song(tempo=120)
    v = voice(song)
    for field in ('palmMute', 'accentuatedNote', 'staccato', None):
        beat = add_beat(v, [(2, 5, {'velocity': 95})])
        if field:
            setattr(beat.notes[0].effect, field, True)
    score = write_read(tmp_path, song, 'gp5')
    out = tmp_path / 'out.mid'
    track_to_midi(score.tracks[0], score, str(out), MidiOptions(humanize=False))
    tick, on, notes = 0, {}, []
    for msg in mido.MidiFile(out).tracks[0]:
        tick += msg.time
        if msg.type == 'note_on' and msg.velocity:
            on[msg.note] = (tick, msg.velocity)
        elif msg.type in ('note_off', 'note_on'):
            start, velocity = on.pop(msg.note)
            notes.append((start, tick - start, velocity))
    quarter = TICKS_PER_BEAT
    assert notes == [(0, quarter // 2, 96 - 8), (quarter, quarter, 96 + 16),
                     (2 * quarter, quarter // 2, 96), (3 * quarter, quarter, 96)]

# ---------------------------------------------------------------------------
# Step 5: hammer-ons / pull-offs, bends, harmonics, grace notes, strokes.
# What each version stores: GP3 has no tapped, pinch or semi harmonics, no
# artificial harmonic pitch, no on-beat graces and no pick strokes; GP4 has
# no on-beat graces.
# ---------------------------------------------------------------------------

def notes_of(score, beat):
    return [score.notes[n] for n in beat.note_ids]


@pytest.mark.parametrize('ext', VERSIONS)
def test_hammer_on_origin_and_destination(tmp_path, ext):
    # GP flags the origin; the destination is the next beat's note on its string
    song = new_song(bars=2)
    v = voice(song)
    add_beat(v, [(3, 5, {}), (1, 0, {})])
    v.beats[-1].notes[0].effect.hammer = True
    add_beat(v, [(3, 7, {}), (1, 0, {})])                   # string 3: destination
    add_beat(v, [(3, 5, {})])
    v.beats[-1].notes[0].effect.hammer = True
    add_beat(voice(song, bar=1), [(3, 7, {})])              # across the bar line
    score = write_read(tmp_path, song, ext)
    first = beats_of(score)
    flags = [sorted((n.string, n.hopo_origin, n.hopo_dest) for n in notes_of(score, b))
             for b in first[:3]]
    assert flags == [[(3, True, False), (5, False, False)],
                     [(3, False, True), (5, False, False)],
                     [(3, True, False)]]       # model strings: GP 3 → 3, GP 1 → 5
    assert notes_of(score, beats_of(score, bar=1)[0])[0].hopo_dest


@pytest.mark.parametrize('ext', VERSIONS)
def test_hammer_on_broken_by_rest_or_tie(tmp_path, ext):
    song = new_song()
    v = voice(song)
    add_beat(v, [(3, 5, {})], value=8)
    v.beats[-1].notes[0].effect.hammer = True
    add_beat(v, value=8)                                    # rest
    add_beat(v, [(3, 7, {})], value=8)
    v.beats[-1].notes[0].effect.hammer = True
    add_beat(v, [(3, 0, {'type': gp.NoteType.tie})], value=8)
    score = write_read(tmp_path, song, ext)
    beats = beats_of(score)
    assert not notes_of(score, beats[2])[0].hopo_dest
    assert not notes_of(score, beats[3])[0].hopo_dest


@pytest.mark.parametrize('ext', VERSIONS)
def test_bend(tmp_path, ext):
    # Positions 0-12, values in quarter tones: 4 = a full (2 semitone) bend
    points = [gp.BendPoint(0, 0), gp.BendPoint(6, 4), gp.BendPoint(12, 4)]
    note = note_with_effect(tmp_path, ext, bend=gp.BendEffect(type=gp.BendType.bend, value=50,
                                                              points=points))
    assert note.bend == [(0.0, 0.0), (0.5, 2.0), (1.0, 2.0)]
    assert note_with_effect(tmp_path, ext).bend is None


@pytest.mark.parametrize('ext', VERSIONS)
def test_natural_harmonic(tmp_path, ext):
    note = note_with_effect(tmp_path, ext, harmonic=gp.NaturalHarmonic())
    assert note.harmonic == Harmonic(type='natural', fret=5.0)   # the note's fret is the node


@pytest.mark.parametrize('ext', ['gp4', 'gp5'])
@pytest.mark.parametrize('harmonic, expected', [
    (gp.TappedHarmonic(17), Harmonic(type='tap', fret=12.0)),    # tapped fret 17 − fret 5
    (gp.PinchHarmonic(), Harmonic(type='pinch', fret=7.0)),
    (gp.SemiHarmonic(), Harmonic(type='semi', fret=12.0)),
])
def test_other_harmonics(tmp_path, ext, harmonic, expected):
    assert note_with_effect(tmp_path, ext, harmonic=harmonic).harmonic == expected


@pytest.mark.parametrize('pitch, octave, node', [
    # The note is fret 5 on GP string 2 (B, 59): 64 = E
    (4, gp.Octave.ottava, 12.0),            # E, an octave up: +12
    (11, gp.Octave.ottava, 7.0),            # B, octave + fifth: +19
    (4, gp.Octave.quindicesima, 5.0),       # E, two octaves: +24
    (8, gp.Octave.quindicesima, 4.0),       # G#, two octaves + third: +28
    (6, gp.Octave.ottava, None),            # +14: no harmonic there
    (4, gp.Octave.ottavaBassa, None),
])
def test_gp5_artificial_harmonic(tmp_path, pitch, octave, node):
    note = note_with_effect(tmp_path, 'gp5',
                            harmonic=gp.ArtificialHarmonic(gp.PitchClass(pitch), octave))
    assert note.harmonic == (Harmonic(type='artificial', fret=node) if node else None)


def test_gp3_artificial_harmonic_has_no_pitch(tmp_path):
    note = note_with_effect(tmp_path, 'gp3',
                            harmonic=gp.ArtificialHarmonic(gp.PitchClass(4), gp.Octave.ottava))
    assert note.harmonic is None


def test_harmonic_nodes_sound_their_interval():
    from gpif import harmonic_interval
    from gpif.readers.gp345 import ARTIFICIAL_HARMONIC_NODES
    for interval, node in ARTIFICIAL_HARMONIC_NODES.items():
        assert harmonic_interval(node) == interval


def grace_song(tmp_path, ext, **grace):
    """Main note fret 7 on GP string 3 (model string 3) with a grace note."""
    song = new_song()
    beat = add_beat(voice(song), [(3, 7, {'velocity': 95})])
    beat.notes[0].effect.grace = gp.GraceEffect(**{'fret': 5, 'duration': 32, **grace})
    return write_read(tmp_path, song, ext)


@pytest.mark.parametrize('ext', VERSIONS)
def test_grace_note_becomes_a_beat(tmp_path, ext):
    score = grace_song(tmp_path, ext, velocity=63)
    grace_beat, main_beat = beats_of(score)[:2]
    assert (grace_beat.grace, main_beat.grace) == ('before', None)
    assert score.rhythms[grace_beat.rhythm_id].beats == 0.125
    [grace], [main] = notes_of(score, grace_beat), notes_of(score, main_beat)
    assert (grace.string, grace.fret, grace.dynamic) == (3, 5, 'MP')
    assert (main.string, main.fret) == (3, 7)


def test_gp5_on_beat_grace(tmp_path):
    score = grace_song(tmp_path, 'gp5', isOnBeat=True)
    assert beats_of(score)[0].grace == 'on'


@pytest.mark.parametrize('ext', VERSIONS)
@pytest.mark.parametrize('transition', ['hammer', 'slide', 'bend', 'none'])
def test_grace_transitions(tmp_path, ext, transition):
    score = grace_song(tmp_path, ext, transition=gp.GraceEffectTransition[transition])
    grace_beat, main_beat = beats_of(score)[:2]
    [grace], [main] = notes_of(score, grace_beat), notes_of(score, main_beat)
    assert (grace.hopo_origin, main.hopo_dest) == ((True, True) if transition == 'hammer'
                                                   else (False, False))
    assert grace.slide_out == ('legato' if transition == 'slide' else None)
    assert grace.bend == ([(0.0, 0.0), (1.0, 2.0)] if transition == 'bend' else None)


@pytest.mark.parametrize('ext', VERSIONS)
def test_dead_grace(tmp_path, ext):
    # GP3/4 store a dead grace as fret -1, GP5 as a flag
    fret = 0 if ext == 'gp5' else -1
    score = grace_song(tmp_path, ext, fret=fret, isDead=True)
    grace = notes_of(score, beats_of(score)[0])[0]
    assert (grace.dead, grace.fret) == (True, 0)


@pytest.mark.parametrize('ext', VERSIONS)
def test_brush_stroke(tmp_path, ext):
    song = new_song()
    add_beat(voice(song), [(1, 0, {}), (6, 0, {})]).effect.stroke = gp.BeatStroke(
        gp.BeatStrokeDirection.up, 8)
    add_beat(voice(song), [(1, 0, {}), (6, 0, {})]).effect.stroke = gp.BeatStroke(
        gp.BeatStrokeDirection.down, 8)
    score = write_read(tmp_path, song, ext)
    assert [b.brush for b in beats_of(score)[:2]] == ['up', 'down']


@pytest.mark.parametrize('ext', ['gp4', 'gp5'])
def test_pick_stroke(tmp_path, ext):
    song = new_song()
    add_beat(voice(song), [(1, 0, {})]).effect.pickStroke = gp.BeatStrokeDirection.up
    add_beat(voice(song), [(1, 0, {})])
    score = write_read(tmp_path, song, ext)
    assert [b.pick_stroke for b in beats_of(score)[:2]] == ['up', None]


def test_gp5_step5_through_gp2midi(tmp_path):
    # A full bend becomes pitch bend up to 2 semitones; a grace note sounds
    # before the beat; a hammer-on destination is softer
    import mido
    song = new_song(tempo=120)
    v = voice(song)
    beat = add_beat(v, [(3, 7, {'velocity': 95})])
    beat.notes[0].effect.bend = gp.BendEffect(type=gp.BendType.bend, value=50, points=[
        gp.BendPoint(0, 0), gp.BendPoint(12, 4)])
    add_beat(v, [(3, 5, {'velocity': 95})]).notes[0].effect.hammer = True
    add_beat(v, [(3, 7, {'velocity': 95})])
    add_beat(v, [(3, 9, {'velocity': 95})]).notes[0].effect.grace = gp.GraceEffect(fret=7, duration=32)
    score = write_read(tmp_path, song, 'gp5')
    out = tmp_path / 'out.mid'
    track_to_midi(score.tracks[0], score, str(out), MidiOptions(humanize=False))
    tick, ons, bends = 0, [], []
    for msg in mido.MidiFile(out).tracks[0]:
        tick += msg.time
        if msg.type == 'note_on' and msg.velocity:
            ons.append((tick, msg.note, msg.velocity))
        elif msg.type == 'pitchwheel':
            bends.append(msg.pitch)
    q = TICKS_PER_BEAT
    assert max(bends) == round(2 / 12 * 8192)                 # bend range 12
    assert [(t, n) for t, n, _ in ons][:3] == [(0, 62), (q, 60), (2 * q, 62)]
    assert ons[2][2] < ons[1][2]                              # hammer-on destination softer
    grace, main = ons[3], ons[4]
    assert (grace[1], main) == (62, (3 * q, 64, 96)) and grace[0] < 3 * q
