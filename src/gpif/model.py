"""
The parsed score's data types: one frozen dataclass per GPIF element.

The parse_* functions build them; ids refer between them as in the XML
(MasterBar.bar_ids → Bar.voice_ids → Voice.beat_ids → Beat.note_ids /
Beat.rhythm_id). Every field except ids (and Rhythm's) has a default, so tests can build
a Note(fret=5) or Track(id=0, staves=[...]) with just the fields they need.
Lists are left as lists: frozen stops reassigning a field, not mutating it.

Raw XML, for anything the parser doesn't interpret (let ring, brush
strokes, whammy bar, lyrics, ...): every object built from an XML element
keeps it in `element` (left out of == and repr, so equality means "same
parsed meaning"), and Note and Beat also have `properties`, every
<Property> name mapped to its value text, worked out from `element` on
first use.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import cached_property


def _element() -> ET.Element | None:
    """The source XML element: None for objects built by hand (e.g. in tests)."""
    return field(default=None, compare=False, repr=False)


def property_value(prop_el: ET.Element) -> str:
    """
    A GPIF <Property>'s value as text: its first child's text, or '' for a
    flag such as <Enable/> and for a structured value such as a <Pitch>
    (read those from the element itself).
    """
    for value_el in prop_el:
        text = value_el.text
        return text.strip() if text and not len(value_el) else ''
    return ''


class _RawProperties:
    """Adds `properties` to a dataclass with an `element` field."""
    element: ET.Element | None

    @cached_property
    def properties(self) -> dict[str, str]:
        """
        Every <Properties>/<Property> of `element` by name → property_value
        (e.g. {'Brush': 'Down'}, {'Muted': ''}); {} without an element.
        Computed on first use. cached_property writes the instance __dict__
        directly, so it works on these frozen dataclasses.
        """
        if self.element is None:
            return {}
        return {prop_el.get('name', ''): property_value(prop_el)
                for prop_el in self.element.findall('./Properties/Property')}


@dataclass(frozen=True)
class ScoreInfo:
    """The <Score> header text; '' when absent."""
    title:        str = ''
    subtitle:     str = ''
    artist:       str = ''
    album:        str = ''
    words:        str = ''
    music:        str = ''
    copyright:    str = ''
    tabber:       str = ''
    instructions: str = ''
    notices:      str = ''
    element:      ET.Element | None = _element()       # <Score>


@dataclass(frozen=True)
class Staff:
    # MIDI pitches, lowest string first (GPIF string 0); [] if none
    tuning: list[int] = field(default_factory=list)
    capo:   int = 0
    # GP8 <Staff>; None in GP6/7 files, whose single staff's properties are
    # on the track (Track.element)
    element: ET.Element | None = _element()


@dataclass(frozen=True)
class Track:
    id:         int
    name:       str = ''
    program:    int = 25           # MIDI program; acoustic guitar fallback
    channel:    int = 0            # MIDI channel 0-15
    # GP8 InstrumentSet/Type (e.g. electricGuitar) or GP6 Instrument ref
    # (e.g. e-gtr6); None if neither is present
    instrument: str | None = None
    is_drum:    bool = False       # channel 9
    is_tab:     bool = False       # has a tuning and isn't a drum track
    is_fretted: bool = False       # tab track on a guitar / bass / ... instrument
    # One per staff (a GP8 piano track has two); never empty
    staves:     list[Staff] = field(default_factory=lambda: [Staff()])
    # Position of the track's first staff in MasterBar.bar_ids
    bar_index:  int = 0
    element:    ET.Element | None = _element()

    @property
    def tuning(self) -> list[int]:
        """The first staff's tuning."""
        return self.staves[0].tuning

    @property
    def capo(self) -> int:
        """The first staff's capo fret."""
        return self.staves[0].capo


@dataclass(frozen=True)
class MasterBar:
    # One bar id per staff, tracks in document order (see Track.bar_index)
    bar_ids:     list[int] = field(default_factory=list)
    numerator:   int = 4
    denominator: int = 4
    element:     ET.Element | None = _element()


@dataclass(frozen=True)
class Bar:
    voice_ids: list[int] = field(default_factory=list)    # played in parallel
    element:   ET.Element | None = _element()


@dataclass(frozen=True)
class Voice:
    beat_ids: list[int] = field(default_factory=list)     # played in sequence
    element:  ET.Element | None = _element()


@dataclass(frozen=True)
class Beat(_RawProperties):
    rhythm_id: int = 0
    note_ids:  list[int] = field(default_factory=list)    # a chord
    is_rest:   bool = False
    # Dynamic in force: PPP, PP, P, MP, MF, F, FF, FFF; None if absent
    dynamic:   str | None = None
    # Grace-note beat: 'before' / 'on' the main beat; takes no bar time
    grace:     str | None = None
    # Strokes marked in the score: 'down' / 'up'; None if not marked. Down
    # is a downstroke (low string to high). Pick stroke (GP7/8 PickStroke
    # property; no sample file has one yet), brush (strum) and arpeggio
    # (a slow roll across the strings).
    pick_stroke: str | None = None
    brush:       str | None = None
    arpeggio:    str | None = None
    element:   ET.Element | None = _element()


@dataclass(frozen=True)
class Harmonic:
    # 'natural' | 'artificial' | 'pinch' | 'tap' | 'semi' | 'feedback'
    type: str
    fret: float        # where the string is touched (the node)


@dataclass(frozen=True)
class Note(_RawProperties):
    string:      int = 0               # GPIF string, 0 = lowest
    fret:        int = 0
    midi:        int | None = None     # GP8's pitch; None in GP6 files
    is_tie_dest: bool = False          # tied from the previous note
    # [(fraction of the note 0-1, semitones), ...] or None
    bend:        list[tuple[float, float]] | None = None
    accent:      str | None = None     # 'normal' | 'heavy'
    staccato:    bool = False
    ghost:       bool = False
    hopo_origin: bool = False          # hammer-on / pull-off: picked note
    hopo_dest:   bool = False          # sounded by the fretting hand
    palm_muted:  bool = False
    dead:        bool = False          # muted 'x' note
    vibrato:     str | None = None     # 'slight' | 'wide'
    slide_in:    str | None = None     # 'below' | 'above'
    slide_out:   str | None = None     # 'shift' | 'legato' | 'down' | 'up'
    harmonic:    Harmonic | None = None
    # The note's own dynamic (PPP … FFF) where the format has one per note
    # (GP3-5 velocities); None = the beat's (always None from GPIF)
    dynamic:     str | None = None
    element:     ET.Element | None = _element()


@dataclass(frozen=True)
class Rhythm:
    beats: float            # quarter note = 1, after dots and tuplets
    ticks: int              # beats * TICKS_PER_BEAT, rounded
    element: ET.Element | None = _element()


@dataclass(frozen=True)
class Tempo:
    bar:      int = 0       # master bar index
    position: float = 0.0   # position within the bar (0 = start)
    bpm:      float = 120.0
    # The tempo <Automation>; None for the <Score> tempo fallback
    element:  ET.Element | None = _element()
