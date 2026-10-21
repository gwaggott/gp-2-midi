"""
GPIF XML (Guitar Pro 6/7/8) into the gpif.model dataclasses, and the GPIF
readers.

GpifContentMixin parses an XML root: each parse_* method flattens one
top-level GPIF section into a dict of objects keyed by id (or an ordered
list), leaving the caller to walk the reference chain: MasterBar → Bar →
Voice → Beat → Rhythm / Note. parse_score runs them all. Logic that isn't
GPIF-specific comes from the shared mixins (mixins.py).

Each reader combines a container mixin (containers.py), which gets the XML
out of the file, with GpifContentMixin. The parse_* methods are also
module-level functions (bound to one stateless parser), the public API the
fragment tests use.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from ..model import (
    Bar, Beat, MasterBar, Note, Rhythm, ScoreInfo, Staff, Tempo, Track, Voice,
)
from ..score import Score
from .base import ScoreReader
from .containers import BcfsContainerMixin, RawXmlContainerMixin, ZipContainerMixin
from .mixins import PitchEffectsMixin, RhythmMixin, TrackClassificationMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# GPIF NoteValue → beats (quarter note = 1 beat)
NOTE_VALUE_BEATS = {
    'Whole':   4.0,
    'Half':    2.0,
    'Quarter': 1.0,
    'Eighth':  0.5,
    '16th':    0.25,
    '32nd':    0.125,
    '64th':    0.0625,
    '128th':   0.03125,
}

SCORE_FIELDS = ('Title', 'SubTitle', 'Artist', 'Album', 'Words', 'Music',
                'Copyright', 'Tabber', 'Instructions', 'Notices')

# <Slide><Flags> on a Note is a bit field. "Out" slides end the note; "to
# next" slides glide into the following note on the same string (shift: the
# next note is picked; legato: it isn't).
SLIDE_SHIFT = 0x01
SLIDE_LEGATO = 0x02
SLIDE_OUT_DOWN = 0x04
SLIDE_OUT_UP = 0x08
SLIDE_IN_BELOW = 0x10
SLIDE_IN_ABOVE = 0x20

# <Accent> on a Note is a bit field
ACCENT_STACCATO = 0x01
ACCENT_HEAVY = 0x04       # marcato
ACCENT_NORMAL = 0x08


def _find_first(el: ET.Element, *paths: str) -> ET.Element | None:
    """First element found at any of `paths` (e.g. the GP8 path, then GP6/7)."""
    for path in paths:
        found = el.find(path)
        if found is not None:
            return found
    return None


def _direction(beat_el: ET.Element, name: str) -> str | None:
    """
    'down' / 'up' from a Beat property such as
    <Property name="PickStroke"><Direction>Up</Direction></Property>;
    None if absent or another value.
    """
    for prop_el in beat_el.findall('./Properties/Property'):
        if prop_el.get('name') == name:
            return _direction_text(prop_el.findtext('Direction'))
    return None


def _direction_text(text: str | None) -> str | None:
    """'Down' / 'Up' (any case, spaces) → 'down' / 'up'; None otherwise."""
    text = (text or '').strip().lower()
    return text if text in ('down', 'up') else None


# ---------------------------------------------------------------------------
# Content mixin
# ---------------------------------------------------------------------------

class GpifContentMixin(TrackClassificationMixin, RhythmMixin, PitchEffectsMixin):
    """GPIF XML root → Score. A reader adds load_xml (a container mixin)."""

    def read(self, filepath: str | Path) -> Score:
        return self.parse_score(self.load_xml(filepath))

    def parse_score(self, root: ET.Element) -> Score:
        """Parse every section of a GPIF XML root into a Score."""
        return Score(
            tracks=self.parse_tracks(root),
            master_bars=self.parse_master_bars(root),
            bars=self.parse_bars(root),
            voices=self.parse_voices(root),
            beats=self.parse_beats(root),
            notes=self.parse_notes(root),
            rhythms=self.parse_rhythms(root),
            tempos=self.parse_tempos(root),
            info=self.parse_score_info(root),
            root=root,
        )

    def parse_score_info(self, root: ET.Element) -> ScoreInfo:
        """The <Score> header text ('' when absent)."""
        return ScoreInfo(**{field.lower(): (root.findtext(f'./Score/{field}') or '').strip()
                            for field in SCORE_FIELDS},
                         element=root.find('./Score'))

    def parse_staff(self, staff_el: ET.Element | None,
                    fallback_el: ET.Element | None = None) -> Staff:
        """
        One staff's tuning (MIDI pitches, lowest string first; [] if none) and
        capo fret (0 if none) from the GP8 <Staff>'s <Properties>, else from
        `fallback_el` (the track's <Properties>; all there is in GP6/7).
        """
        props_el = staff_el.find('./Properties') if staff_el is not None else None

        def prop(prop_name: str, child: str) -> ET.Element | None:
            for el in (props_el, fallback_el):
                found = el.find(f'./Property[@name="{prop_name}"]/{child}') if el is not None else None
                if found is not None:
                    return found
            return None

        tuning_el = prop('Tuning', 'Pitches')
        tuning = [int(p) for p in tuning_el.text.split()] if tuning_el is not None and tuning_el.text else []
        capo_el = prop('CapoFret', 'Fret')
        capo = int(capo_el.text) if capo_el is not None and (capo_el.text or '').strip().isdigit() else 0
        return Staff(tuning=tuning, capo=capo, element=staff_el)

    def parse_tracks(self, root: ET.Element) -> list[Track]:
        """Return the tracks sorted by track id."""
        tracks = []
        # MasterBar/Bars holds one bar id per staff, tracks in document order, so
        # a track's bars start after all the staves of the tracks before it
        bar_index = 0
        for track_el in root.findall('./Tracks/Track'):
            track_id = int(track_el.get('id', 0))
            name = track_el.findtext('Name', f'Track {track_id}')

            # Staves: GP8 lists them under ./Staves/Staff (a piano track has two),
            # each with its own Properties; GP6/7 tracks have one staff, with its
            # Properties on the track (also the fallback for a GP8 staff)
            track_props = track_el.find('./Properties')
            staves = [self.parse_staff(staff_el, track_props)
                      for staff_el in track_el.findall('./Staves/Staff')]
            if not staves:
                staves = [self.parse_staff(None, track_props)]

            # MIDI program (instrument)
            # GP8: ./Sounds/Sound/MIDI/Program   GP6/7: ./GeneralMidi/Program
            program = 25  # acoustic guitar fallback
            program_el = _find_first(track_el, './Sounds/Sound/MIDI/Program', './GeneralMidi/Program')
            if program_el is not None and program_el.text:
                program = int(program_el.text)

            # MIDI channel
            # GP8: ./MidiConnection/PrimaryChannel   GP6/7: ./GeneralMidi/Channel
            channel_el = _find_first(track_el, './MidiConnection/PrimaryChannel', './GeneralMidi/Channel')
            channel = int(channel_el.text) if channel_el is not None and channel_el.text else (track_id % 16)

            # Instrument id: GP8 <InstrumentSet><Type>electricGuitar</Type>,
            # GP6 <Instrument ref="e-gtr6"/>; None if neither is present
            instrument = (track_el.findtext('./InstrumentSet/Type') or '').strip() or None
            if instrument is None:
                instrument_el = track_el.find('./Instrument')
                if instrument_el is not None:
                    instrument = instrument_el.get('ref') or None

            is_drum, is_tab, is_fretted = self.classify_track(staves[0].tuning, channel, instrument)

            tracks.append(Track(
                id=track_id,
                name=name,
                program=program,
                channel=channel,
                instrument=instrument,
                is_drum=is_drum,
                is_tab=is_tab,
                is_fretted=is_fretted,
                staves=staves,
                bar_index=bar_index,
                element=track_el,
            ))
            bar_index += len(staves)

        tracks.sort(key=lambda t: t.id)
        return tracks

    def parse_master_bars(self, root: ET.Element) -> list[MasterBar]:
        """Return the master bars in order."""
        master_bars = []
        for mb_el in root.findall('./MasterBars/MasterBar'):
            bars_text = mb_el.findtext('Bars', '').strip()
            bar_ids = [int(x) for x in bars_text.split()] if bars_text else []

            time_text = mb_el.findtext('Time', '4/4')
            num, den = map(int, time_text.split('/'))

            master_bars.append(MasterBar(bar_ids=bar_ids, numerator=num, denominator=den,
                                         element=mb_el))
        return master_bars

    def parse_bars(self, root: ET.Element) -> dict[int, Bar]:
        bars = {}
        for bar_el in root.findall('./Bars/Bar'):
            bar_id = int(bar_el.get('id'))
            voices_text = bar_el.findtext('Voices', '').strip()
            voice_ids = [int(x) for x in voices_text.split()] if voices_text else []
            bars[bar_id] = Bar(voice_ids=voice_ids, element=bar_el)
        return bars

    def parse_voices(self, root: ET.Element) -> dict[int, Voice]:
        voices = {}
        for voice_el in root.findall('./Voices/Voice'):
            voice_id = int(voice_el.get('id'))
            beats_text = voice_el.findtext('Beats', '').strip()
            beat_ids = [int(x) for x in beats_text.split()] if beats_text else []
            voices[voice_id] = Voice(beat_ids=beat_ids, element=voice_el)
        return voices

    def parse_beats(self, root: ET.Element) -> dict[int, Beat]:
        beats = {}
        for beat_el in root.findall('./Beats/Beat'):
            beat_id = int(beat_el.get('id'))

            rhythm_ref = beat_el.find('./Rhythm')
            rhythm_id = int(rhythm_ref.get('ref')) if rhythm_ref is not None else 0

            notes_text = beat_el.findtext('Notes', '').strip()
            note_ids = [int(x) for x in notes_text.split()] if notes_text else []

            is_rest = beat_el.find('./Rest') is not None

            # Dynamic marking in force for this beat: PPP, PP, P, MP, MF, F, FF, FFF.
            # Guitar Pro writes it on every beat; None if absent.
            dynamic = beat_el.findtext('Dynamic')
            dynamic = dynamic.strip().upper() if dynamic and dynamic.strip() else None

            # Grace-note beat: <GraceNotes>BeforeBeat</GraceNotes> or OnBeat. It
            # takes no time in the bar; the following beat is the main note.
            grace_text = (beat_el.findtext('GraceNotes') or '').strip()
            grace = {'BeforeBeat': 'before', 'OnBeat': 'on'}.get(grace_text)

            beats[beat_id] = Beat(
                rhythm_id=rhythm_id,
                note_ids=note_ids,
                is_rest=is_rest,
                dynamic=dynamic,
                grace=grace,
                pick_stroke=_direction(beat_el, 'PickStroke'),
                brush=_direction(beat_el, 'Brush'),
                arpeggio=_direction_text(beat_el.findtext('Arpeggio')),
                element=beat_el,
            )
        return beats

    def bend_points(self, props: dict[str, float]) -> list[tuple[float, float]] | None:
        """
        Build a bend curve from a note's Bend* property values.

        GPIF bend values are in 1/100 of a whole tone (100 = full bend = 2
        semitones); offsets are 0–100 percent of the note's duration. A bend has
        an origin and a destination point plus an optional middle value that sits
        at one or two offsets (e.g. bend-and-release, or bend-and-hold). GP8
        writes all seven properties; GP6 omits defaults.

        Returns [(fraction 0.0–1.0, semitones), ...] sorted by position, or None
        if no bend values are present.
        """
        if not any(k in props for k in ('BendOriginValue', 'BendMiddleValue', 'BendDestinationValue')):
            return None

        origin_off = props.get('BendOriginOffset', 0.0)
        dest_off = props.get('BendDestinationOffset', 100.0)
        points = [(origin_off, props.get('BendOriginValue', 0.0))]

        if 'BendMiddleValue' in props:
            middle_offs = [props[k] for k in ('BendMiddleOffset1', 'BendMiddleOffset2') if k in props]
            # Middle points beyond the destination are unused leftovers (GP8
            # writes them even for a plain bend), so keep only those in range.
            for off in middle_offs or [50.0]:
                if origin_off <= off <= dest_off:
                    points.append((off, props['BendMiddleValue']))

        points.append((dest_off, props.get('BendDestinationValue', 0.0)))
        # Stable sort: equal offsets keep origin → middle → destination order
        return self.bend_curve(points, position_scale=100.0, semitone_scale=50.0)

    def parse_notes(self, root: ET.Element) -> dict[int, Note]:
        notes = {}
        for note_el in root.findall('./Notes/Note'):
            note_id = int(note_el.get('id'))

            string_num = 0
            fret_num = 0
            midi_num: int | None = None
            is_tie_dest = False
            is_bended = False
            # Hammer-on / pull-off: the origin is picked, the destination is
            # sounded by the fretting hand (direction tells hammer from pull)
            is_hopo_origin = False
            is_hopo_dest = False
            is_palm_muted = False
            is_dead = False         # 'Muted': dead / muted note (x in tab)
            slide_flags = 0
            harmonic_type: str | None = None
            harmonic_fret: float | None = None
            bend_props: dict[str, float] = {}

            for prop_el in note_el.findall('./Properties/Property'):
                prop_name = prop_el.get('name', '')
                # Value is in a child named after the property (<String>, <Fret>);
                # older files may use <Number>
                if prop_name == 'String':
                    num_el = prop_el.find('String')
                    if num_el is None:
                        num_el = prop_el.find('Number')
                    if num_el is not None:
                        string_num = int(num_el.text)
                elif prop_name == 'Fret':
                    num_el = prop_el.find('Fret')
                    if num_el is None:
                        num_el = prop_el.find('Number')
                    if num_el is not None:
                        fret_num = int(num_el.text)
                elif prop_name == 'Midi':
                    num_el = prop_el.find('Number')
                    if num_el is not None:
                        midi_num = int(num_el.text)
                elif prop_name == 'Bended':
                    is_bended = True
                elif prop_name == 'HopoOrigin':
                    is_hopo_origin = True
                elif prop_name == 'HopoDestination':
                    is_hopo_dest = True
                elif prop_name == 'PalmMuted':
                    is_palm_muted = True
                elif prop_name == 'Muted':
                    is_dead = True
                elif prop_name == 'HarmonicType':
                    harmonic_type = (prop_el.findtext('HType') or '').strip().lower() or None
                elif prop_name == 'HarmonicFret':
                    try:
                        harmonic_fret = float((prop_el.findtext('HFret') or '').strip())
                    except ValueError:
                        harmonic_fret = None
                elif prop_name == 'Slide':
                    flags_text = (prop_el.findtext('Flags') or '').strip()
                    slide_flags = int(flags_text) if flags_text.isdigit() else 0
                elif prop_name.startswith('Bend'):
                    float_el = prop_el.find('Float')
                    if float_el is not None and float_el.text:
                        bend_props[prop_name] = float(float_el.text)

            # Tie destination: this note is tied FROM the previous one
            tie_el = note_el.find('Tie')
            if tie_el is not None and tie_el.get('destination', '').lower() == 'true':
                is_tie_dest = True

            accent_text = (note_el.findtext('Accent') or '').strip()
            accent_flags = int(accent_text) if accent_text.isdigit() else 0
            if accent_flags & ACCENT_HEAVY:
                accent = 'heavy'
            elif accent_flags & ACCENT_NORMAL:
                accent = 'normal'
            else:
                accent = None

            # <AntiAccent>Normal</AntiAccent> marks a ghost note
            is_ghost = note_el.find('AntiAccent') is not None

            # <Vibrato>Slight</Vibrato> or Wide
            vibrato_text = (note_el.findtext('Vibrato') or '').strip().lower()
            vibrato = vibrato_text if vibrato_text in ('slight', 'wide') else None

            # One slide out of the note (first matching flag wins) and one into it
            slide_out = next((name for flag, name in (
                (SLIDE_SHIFT, 'shift'), (SLIDE_LEGATO, 'legato'),
                (SLIDE_OUT_DOWN, 'down'), (SLIDE_OUT_UP, 'up'),
            ) if slide_flags & flag), None)
            slide_in = ('below' if slide_flags & SLIDE_IN_BELOW
                        else 'above' if slide_flags & SLIDE_IN_ABOVE else None)

            notes[note_id] = Note(
                string=string_num,
                fret=fret_num,
                midi=midi_num,
                is_tie_dest=is_tie_dest,
                bend=self.bend_points(bend_props) if is_bended else None,
                accent=accent,
                staccato=bool(accent_flags & ACCENT_STACCATO),
                ghost=is_ghost,
                hopo_origin=is_hopo_origin,
                hopo_dest=is_hopo_dest,
                palm_muted=is_palm_muted,
                dead=is_dead,
                vibrato=vibrato,
                slide_in=slide_in,
                slide_out=slide_out,
                harmonic=self.harmonic(harmonic_type, harmonic_fret),
                element=note_el,
            )
        return notes

    def parse_rhythms(self, root: ET.Element) -> dict[int, Rhythm]:
        rhythms = {}
        for rhythm_el in root.findall('./Rhythms/Rhythm'):
            rhythm_id = int(rhythm_el.get('id'))
            note_value = rhythm_el.findtext('NoteValue', 'Quarter')

            # Dots: <AugmentationDot count="1"/> in every GP6-8 file seen;
            # <AugmentationDot><Enable>true</Enable> also accepted as one dot
            dots = 0
            dot_el = rhythm_el.find('./AugmentationDot')
            if dot_el is not None:
                count = (dot_el.get('count') or '').strip()
                if count.isdigit():
                    dots = int(count)
                elif (dot_el.findtext('Enable') or '').strip().lower() == 'true':
                    dots = 1

            # Tuplet (triplet, etc.): <PrimaryTuplet num="3" den="2"/> in every
            # GP6-8 file seen (<Num> / <Den> children also accepted), and a
            # nested <SecondaryTuplet> multiplied in
            tuplet = None
            for name in ('PrimaryTuplet', 'SecondaryTuplet'):
                tuplet_el = rhythm_el.find(f'./{name}')
                if tuplet_el is None:
                    continue
                num = tuplet_el.get('num') or tuplet_el.findtext('Num')
                den = tuplet_el.get('den') or tuplet_el.findtext('Den')
                if num and den:
                    num, den = int(num), int(den)
                    tuplet = (num, den) if tuplet is None else (tuplet[0] * num, tuplet[1] * den)

            rhythms[rhythm_id] = self.rhythm(NOTE_VALUE_BEATS.get(note_value, 1.0),
                                             dots, tuplet, element=rhythm_el)
        return rhythms

    def parse_tempos(self, root: ET.Element) -> list[Tempo]:
        """Return the tempo events, sorted by bar and position."""
        tempos = []
        for auto_el in root.findall('./MasterTrack/Automations/Automation'):
            if auto_el.findtext('Type', '') == 'Tempo':
                bar = int(auto_el.findtext('Bar', '0'))
                position = float(auto_el.findtext('Position', '0'))
                value_text = auto_el.findtext('Value', '120').split()
                bpm = float(value_text[0]) if value_text else 120.0
                tempos.append(Tempo(bar=bar, position=position, bpm=bpm, element=auto_el))

        if not tempos:
            # Fall back to Score-level tempo
            score_tempo = root.findtext('./Score/Tempo/Value')
            bpm = float(score_tempo) if score_tempo else 120.0
            tempos.append(Tempo(bar=0, position=0.0, bpm=bpm))

        return sorted(tempos, key=lambda t: (t.bar, t.position))


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

class Gp7Reader(ZipContainerMixin, GpifContentMixin, ScoreReader):
    name = 'GP7/8'
    extensions = ('.gp',)


class Gp6Reader(BcfsContainerMixin, GpifContentMixin, ScoreReader):
    name = 'GP6'
    extensions = ('.gpx',)


class GpifXmlReader(RawXmlContainerMixin, GpifContentMixin, ScoreReader):
    name = 'GPIF XML'
    extensions = ('.gpif', '.xml')


# ---------------------------------------------------------------------------
# The parse_* methods as functions
# ---------------------------------------------------------------------------

_PARSER = GpifContentMixin()
parse_score = _PARSER.parse_score
parse_score_info = _PARSER.parse_score_info
parse_tracks = _PARSER.parse_tracks
parse_master_bars = _PARSER.parse_master_bars
parse_bars = _PARSER.parse_bars
parse_voices = _PARSER.parse_voices
parse_beats = _PARSER.parse_beats
parse_notes = _PARSER.parse_notes
parse_rhythms = _PARSER.parse_rhythms
parse_tempos = _PARSER.parse_tempos
bend_points = _PARSER.bend_points
