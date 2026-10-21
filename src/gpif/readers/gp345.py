"""
Readers for Guitar Pro 3, 4 and 5 files (.gp3 / .gp4 / .gp5), through the
PyGuitarPro library (`pip install pyguitarpro`; imported only when such a
file is read, so the gpif package still needs nothing for GPIF files).

PyGuitarProMixin turns a guitarpro.Song into a Score, using the shared
mixins (mixins.py) and a ScoreBuilder for the ids GP3-5 files don't have.
PyGuitarPro handles the differences between the versions, so the three
readers only differ in the file header they recognise.

Not converted (as for GPIF): let ring, tremolo picking, trills, the whammy
bar and rasgueado.
"""

from dataclasses import replace
from pathlib import Path

from ..model import Bar, Beat, Harmonic, MasterBar, Note, ScoreInfo, Staff, Tempo, Track, Voice
from ..score import Score
from .base import ScoreReader
from .mixins import (
    DynamicsMixin,
    PitchEffectsMixin,
    RhythmMixin,
    ScoreBuilder,
    TrackClassificationMixin,
)

# General MIDI program → instrument name (Track.instrument; GP3-5 tracks name
# no instrument): each guitar, bass and banjo program by name, other programs
# by their family, so is_fretted_instrument can classify them
GM_FRETTED = {
    24: 'Acoustic Guitar (nylon)', 25: 'Acoustic Guitar (steel)',
    26: 'Electric Guitar (jazz)', 27: 'Electric Guitar (clean)',
    28: 'Electric Guitar (muted)', 29: 'Overdriven Guitar', 30: 'Distortion Guitar',
    31: 'Guitar Harmonics', 32: 'Acoustic Bass', 33: 'Electric Bass (finger)',
    34: 'Electric Bass (pick)', 35: 'Fretless Bass', 36: 'Slap Bass 1', 37: 'Slap Bass 2',
    38: 'Synth Bass 1', 39: 'Synth Bass 2', 105: 'Banjo',
}
GM_FAMILIES = (
    'Piano', 'Chromatic Percussion', 'Organ', 'Guitar', 'Bass', 'Strings', 'Ensemble',
    'Brass', 'Reed', 'Pipe', 'Synth Lead', 'Synth Pad', 'Synth Effects', 'Ethnic',
    'Percussive', 'Sound Effects',
)


# Slide types (guitarpro.SlideType names) → Note.slide_out, in the order
# GPIF's flags are checked (the first wins), and → Note.slide_in
SLIDES_OUT = (('shiftSlideTo', 'shift'), ('legatoSlideTo', 'legato'),
              ('outDownwards', 'down'), ('outUpwards', 'up'))
SLIDES_IN = (('intoFromBelow', 'below'), ('intoFromAbove', 'above'))


# Artificial harmonics: semitones above the fretted note → the node (fret
# offset) that sounds them (gpif.harmonic_interval inverted)
ARTIFICIAL_HARMONIC_NODES = {12: 12.0, 19: 7.0, 24: 5.0, 28: 4.0, 31: 3.2}
# guitarpro.Octave names of an artificial harmonic → octaves up
HARMONIC_OCTAVES = {'none': 0, 'ottava': 1, 'quindicesima': 2}
# Pinch and semi harmonics name no node in GP3-5: assumed octave + fifth
# for a pinch harmonic, an octave for a semi harmonic; a tapped harmonic
# without a fret (GP3/4) 12 frets above the note
PINCH_HARMONIC_NODE = 7.0
SEMI_HARMONIC_NODE = 12.0
TAPPED_HARMONIC_NODE = 12.0


def gm_instrument(program: int) -> str:
    """A General MIDI program's name (fretted instruments) or family."""
    return GM_FRETTED.get(program) or GM_FAMILIES[max(0, min(127, program)) // 8]


def _guitarpro():
    """The guitarpro module, or an ImportError saying how to get it."""
    try:
        import guitarpro
    except ImportError as exc:
        raise ImportError("Reading Guitar Pro 3-5 files needs PyGuitarPro: "
                          "pip install pyguitarpro") from exc
    return guitarpro


class PyGuitarProMixin(TrackClassificationMixin, RhythmMixin, PitchEffectsMixin, DynamicsMixin):
    """A GP3 / GP4 / GP5 file → Score, via guitarpro.parse."""

    def read(self, filepath: str | Path) -> Score:
        return self.convert_song(_guitarpro().parse(str(filepath)))

    def convert_song(self, song) -> Score:
        """A guitarpro.Song → Score."""
        builder = ScoreBuilder()
        tracks = [self.convert_track(index, track) for index, track in enumerate(song.tracks)]
        master_bars = []
        # Strings with a hammer-on / pull-off origin in each voice's last
        # beat: {track index: {voice index: set of model strings}}
        hammers: dict[int, dict[int, set[int]]] = {}
        for bar_index, header in enumerate(song.measureHeaders):
            bar_ids = [self.convert_measure(builder, track.measures[bar_index],
                                            hammers.setdefault(track_index, {}))
                       for track_index, track in enumerate(song.tracks)]
            master_bars.append(MasterBar(
                bar_ids=bar_ids,
                numerator=header.timeSignature.numerator,
                denominator=header.timeSignature.denominator.value,
            ))
        return builder.score(tracks, master_bars, self.convert_tempos(song),
                             self.convert_info(song), source=song)

    def convert_info(self, song) -> ScoreInfo:
        return ScoreInfo(
            title=song.title, subtitle=song.subtitle, artist=song.artist,
            album=song.album, words=song.words, music=song.music,
            copyright=song.copyright, tabber=song.tab, instructions=song.instructions,
            notices='\n'.join(song.notice),
        )

    def convert_track(self, index: int, track) -> Track:
        """One staff; channel 9 for a percussion track."""
        # GuitarString number 1 is the highest string; the model's tuning
        # starts with the lowest
        tuning = [s.value for s in sorted(track.strings, key=lambda s: s.number, reverse=True)]
        program = track.channel.instrument
        channel = 9 if track.isPercussionTrack else track.channel.channel
        instrument = gm_instrument(program)
        is_drum, is_tab, is_fretted = self.classify_track(tuning, channel, instrument)
        return Track(
            id=index,
            name=track.name,
            program=program,
            channel=channel,
            instrument=instrument,
            is_drum=is_drum,
            is_tab=is_tab,
            is_fretted=is_fretted,
            staves=[Staff(tuning=tuning, capo=track.offset)],
            bar_index=index,
        )

    def convert_measure(self, builder: ScoreBuilder, measure,
                        hammers: dict[int, set[int]] | None = None) -> int:
        """
        The bar id of one track's measure. Voices with only empty beats are
        left out. hammers carries each voice's pending hammer-on / pull-off
        origins from one measure to the next (see convert_beat).
        """
        hammers = {} if hammers is None else hammers
        voice_ids = []
        for voice_index, voice in enumerate(measure.voices):
            pending = hammers.setdefault(voice_index, set())
            if all(beat.status.name == 'empty' for beat in voice.beats):
                pending.clear()
                continue
            string_count = len(measure.track.strings)
            capo = measure.track.offset
            beat_ids = []
            for beat in voice.beats:
                beat_ids += self.convert_beat(builder, beat, string_count, pending, capo)
            voice_ids.append(builder.add_voice(Voice(beat_ids=beat_ids)))
        return builder.add_bar(Bar(voice_ids=voice_ids))

    def convert_beat(self, builder: ScoreBuilder, beat, string_count: int,
                     hammer_from: set[int] | None = None, capo: int = 0) -> list[int]:
        """
        The ids of a beat with its notes, after a grace-note beat if its notes
        have grace notes (GP3-5 keep them as a note effect; the model as a
        beat before the main one, 'on' the beat if any is, else 'before').

        An empty beat in a voice that has others is a rest. The beat's dynamic
        is its notes' most common one (the earliest on a tie); each note also
        keeps its own.

        GP3-5 frets are relative to the track's capo, so each note's sounding
        pitch (string tuning + capo + fret) goes in Note.midi, which gp2midi
        uses before tuning + fret.

        Hammer-on / pull-off: GP3-5 flag the note the slur starts from (the
        origin). hammer_from holds the strings with an origin in the voice's
        previous beat; a note on one of them here (not a tie) is the
        destination. It's updated for the next beat, and a rest clears it.
        """
        hammer_from = set() if hammer_from is None else hammer_from
        duration = beat.duration
        tuplet = duration.tuplet
        rhythm = self.rhythm(4.0 / duration.value, int(duration.isDotted),
                             (tuplet.enters, tuplet.times) if tuplet.enters != 1 else None)
        notes, graces = [], []
        for gp_note in beat.notes:
            note = self.convert_note(gp_note, string_count, beat)
            note = replace(note, midi=self._pitch(gp_note, capo))
            if note.string in hammer_from and not note.is_tie_dest:
                note = replace(note, hopo_dest=True)
            if gp_note.effect.grace is not None:
                grace, note = self.convert_grace(gp_note.effect.grace, note)
                grace = replace(grace, midi=self._pitch(gp_note, capo, grace.fret))
                graces.append((grace, gp_note.effect.grace))
            notes.append(note)
        is_rest = beat.status.name != 'normal' or not notes

        hammer_from.clear()
        hammer_from.update(note.string for note in notes if note.hopo_origin)

        beat_ids = []
        if graces:
            grace_notes = [grace for grace, _ in graces]
            longest = min(effect.duration for _, effect in graces)
            beat_ids.append(builder.add_beat(Beat(
                rhythm_id=builder.rhythm_id(self.rhythm(4.0 / longest)),
                note_ids=[builder.add_note(note) for note in grace_notes],
                dynamic=self._most_common_dynamic(grace_notes),
                grace='on' if any(effect.isOnBeat for _, effect in graces) else 'before',
            )))
        beat_ids.append(builder.add_beat(Beat(
            rhythm_id=builder.rhythm_id(rhythm),
            note_ids=[builder.add_note(note) for note in notes],
            is_rest=is_rest,
            dynamic=self._most_common_dynamic(notes),
            pick_stroke=self._direction(beat.effect.pickStroke),
            brush=self._direction(beat.effect.stroke.direction),
        )))
        return beat_ids

    @staticmethod
    def _pitch(gp_note, capo: int, fret: int | None = None) -> int | None:
        """The sounding MIDI pitch of a fret (default: the note's) on the note's string."""
        string = gp_note.beat.voice.measure.track.strings[gp_note.string - 1]
        pitch = string.value + capo + (gp_note.value if fret is None else fret)
        return pitch if 0 <= pitch <= 127 else None

    @staticmethod
    def _most_common_dynamic(notes: list[Note]) -> str | None:
        dynamics = [note.dynamic for note in notes]
        return max(dynamics, key=dynamics.count) if dynamics else None

    @staticmethod
    def _direction(direction) -> str | None:
        """A guitarpro.BeatStrokeDirection → 'down' / 'up' / None."""
        return direction.name if direction.name in ('down', 'up') else None

    def convert_grace(self, grace, main: Note) -> tuple[Note, Note]:
        """
        The grace note for a main note's GraceEffect (on the main note's
        string), and the main note, changed by the transition: hammer → the
        grace is a hammer-on / pull-off origin and the main note its
        destination; slide → the grace slides legato into the main note;
        bend → the grace bends up to the main note's fret.
        """
        grace_note = Note(
            string=main.string,
            fret=max(0, grace.fret),
            dead=grace.isDead,
            dynamic=self.dynamic_for_velocity(grace.velocity),
        )
        transition = grace.transition.name
        if transition == 'hammer':
            grace_note = replace(grace_note, hopo_origin=True)
            main = replace(main, hopo_dest=True)
        elif transition == 'slide':
            grace_note = replace(grace_note, slide_out='legato')
        elif transition == 'bend' and main.fret > grace_note.fret:
            grace_note = replace(grace_note, bend=self.bend_curve(
                [(0, 0), (1, main.fret - grace_note.fret)], position_scale=1, semitone_scale=1))
        return grace_note, main

    def convert_note(self, note, string_count: int, beat=None) -> Note:
        """
        GP string 1 is the highest; model string 0 the lowest. A note's own
        vibrato is slight; the beat's (GP's "wide vibrato") makes all its
        notes wide.
        """
        effect = note.effect
        slide_names = {slide.name for slide in effect.slides}
        if effect.heavyAccentuatedNote:
            accent = 'heavy'
        elif effect.accentuatedNote:
            accent = 'normal'
        else:
            accent = None
        if beat is not None and beat.effect.vibrato:
            vibrato = 'wide'
        elif effect.vibrato:
            vibrato = 'slight'
        else:
            vibrato = None
        bend = None
        if effect.bend is not None and effect.bend.points:
            # Positions 0-12 along the note; values in quarter tones
            bend = self.bend_curve([(point.position, point.value) for point in effect.bend.points],
                                   position_scale=12, semitone_scale=2)
        return Note(
            string=string_count - note.string,
            fret=note.value,
            is_tie_dest=note.type.name == 'tie',
            bend=bend,
            hopo_origin=effect.hammer,
            harmonic=self.convert_harmonic(effect.harmonic, note),
            accent=accent,
            staccato=effect.staccato,
            ghost=effect.ghostNote,
            palm_muted=effect.palmMute,
            dead=note.type.name == 'dead',
            vibrato=vibrato,
            slide_in=next((name for gp_name, name in SLIDES_IN if gp_name in slide_names), None),
            slide_out=next((name for gp_name, name in SLIDES_OUT if gp_name in slide_names), None),
            dynamic=self.dynamic_for_velocity(note.velocity),
        )

    def convert_harmonic(self, harmonic, note) -> Harmonic | None:
        """
        A guitarpro HarmonicEffect → Harmonic with its node (fret offset; for
        a natural harmonic, the fret itself). Artificial: the node that sounds
        the harmonic's pitch class and octave above the fretted note.
        """
        if harmonic is None:
            return None
        kind = type(harmonic).__name__
        if kind == 'NaturalHarmonic':
            return self.harmonic('natural', float(note.value))
        if kind == 'TappedHarmonic':
            node = (harmonic.fret - note.value) if harmonic.fret else TAPPED_HARMONIC_NODE
            return self.harmonic('tap', float(node))
        if kind == 'PinchHarmonic':
            return self.harmonic('pinch', PINCH_HARMONIC_NODE)
        if kind == 'SemiHarmonic':
            return self.harmonic('semi', SEMI_HARMONIC_NODE)
        if kind == 'ArtificialHarmonic' and harmonic.pitch is not None:
            octaves = HARMONIC_OCTAVES.get(harmonic.octave.name if harmonic.octave else 'none')
            if octaves is None:
                return None
            interval = (harmonic.pitch.value - note.realValue) % 12 + 12 * octaves
            return self.harmonic('artificial', ARTIFICIAL_HARMONIC_NODES.get(interval))
        return None

    def convert_tempos(self, song) -> list[Tempo]:
        """
        The song's tempo at the start, then each mix-table tempo change at its
        bar and position (fraction of the bar). Tempo is global: a change on
        any track counts, the first track's wins at the same place.
        """
        tempos = {(0, 0.0): Tempo(bar=0, position=0.0, bpm=float(song.tempo))}
        changes: dict[tuple[int, float], Tempo] = {}
        for track in song.tracks:
            for bar_index, measure in enumerate(track.measures):
                header = measure.header
                for voice in measure.voices:
                    for beat in voice.beats:
                        change = beat.effect.mixTableChange
                        if change is None or change.tempo is None:
                            continue
                        position = (beat.start - header.start) / header.length if header.length else 0.0
                        key = (bar_index, position)
                        changes.setdefault(key, Tempo(bar=bar_index, position=position,
                                                      bpm=float(change.tempo.value)))
        tempos.update(changes)
        return sorted(tempos.values(), key=lambda t: (t.bar, t.position))


class _GpHeaderSniffMixin:
    """
    GP3-5 files start with a length byte and 'FICHIER GUITAR PRO v<n>.<nn>';
    a reader sets HEADER to the part naming its major version.
    """
    HEADER = b''

    @classmethod
    def sniff(cls, head: bytes) -> bool:
        return len(head) > 1 and head[1:1 + head[0]].startswith(cls.HEADER)


class Gp3Reader(_GpHeaderSniffMixin, PyGuitarProMixin, ScoreReader):
    """Guitar Pro 3. No palm mute; one voice."""
    name = 'GP3'
    extensions = ('.gp3',)
    HEADER = b'FICHIER GUITAR PRO v3'


class Gp4Reader(_GpHeaderSniffMixin, PyGuitarProMixin, ScoreReader):
    """Guitar Pro 4. One voice."""
    name = 'GP4'
    extensions = ('.gp4',)
    HEADER = b'FICHIER GUITAR PRO v4'


class Gp5Reader(_GpHeaderSniffMixin, PyGuitarProMixin, ScoreReader):
    """Guitar Pro 5 (v5.00, v5.10). Two voices."""
    name = 'GP5'
    extensions = ('.gp5',)
    HEADER = b'FICHIER GUITAR PRO v5'
