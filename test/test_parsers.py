"""Unit tests for the parse_* functions in gpif/parse.py."""

import pytest

from conftest import gpif
from gpif import (
    TICKS_PER_BEAT,
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
    bend_points,
    is_fretted_instrument,
    parse_bars,
    parse_beats,
    parse_master_bars,
    parse_notes,
    parse_rhythms,
    parse_score_info,
    parse_tempos,
    parse_tracks,
    parse_voices,
)

# ---------------------------------------------------------------------------
# parse_tracks
# ---------------------------------------------------------------------------

GP8_TRACK = '''
<Track id="{id}">
  <Name>{name}</Name>
  <InstrumentSet><Name>Electric Guitar</Name><Type>electricGuitar</Type></InstrumentSet>
  <Staves><Staff><Properties>
    <Property name="CapoFret"><Fret>2</Fret></Property>
    <Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property>
  </Properties></Staff></Staves>
  <Sounds><Sound><MIDI><Program>29</Program></MIDI></Sound></Sounds>
  <MidiConnection><PrimaryChannel>{channel}</PrimaryChannel></MidiConnection>
</Track>
'''

GP6_TRACK = '''
<Track id="0">
  <Name>Bass</Name>
  <Instrument ref="e-bass4"/>
  <Properties>
    <Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property>
  </Properties>
  <GeneralMidi><Program>33</Program><Channel>2</Channel></GeneralMidi>
</Track>
'''


def test_parse_tracks_gp8_paths():
    root = gpif('<Tracks>' + GP8_TRACK.format(id=0, name='Lead', channel=3) + '</Tracks>')
    [track] = parse_tracks(root)
    assert track == Track(
        id=0,
        name='Lead',
        program=29,
        channel=3,
        instrument='electricGuitar',
        is_drum=False,
        is_tab=True,
        is_fretted=True,
        staves=[Staff(tuning=[40, 45, 50, 55, 59, 64], capo=2)],
        bar_index=0,
    )
    # tuning and capo are the first staff's
    assert track.tuning == [40, 45, 50, 55, 59, 64]
    assert track.capo == 2


def test_parse_tracks_gp6_fallback_paths():
    [track] = parse_tracks(gpif('<Tracks>' + GP6_TRACK + '</Tracks>'))
    assert track.tuning == [28, 33, 38, 43]
    assert track.program == 33
    assert track.channel == 2
    assert track.instrument == 'e-bass4'
    assert track.capo == 0
    assert track.is_tab is True
    assert track.is_fretted is True


def test_parse_tracks_tuned_non_fretted_instrument_is_not_fretted():
    # GP8 gives vocal and orchestral tracks a guitar tuning too
    xml = GP8_TRACK.format(id=0, name='Vox', channel=0).replace('electricGuitar', 'voice')
    [track] = parse_tracks(gpif('<Tracks>' + xml + '</Tracks>'))
    assert track.is_tab is True
    assert track.is_fretted is False


def test_parse_tracks_without_instrument_falls_back_to_is_tab():
    [track] = parse_tracks(gpif('<Tracks>' + GP6_TRACK.replace('<Instrument ref="e-bass4"/>', '')
                                + '</Tracks>'))
    assert track.instrument is None
    assert track.is_fretted is True


@pytest.mark.parametrize('instrument, expected', [
    ('electricGuitar', True), ('steelGuitar', True), ('nylonGuitar', True),
    ('electricBass', True), ('acousticBass', True),
    ('e-gtr6', True), ('s-gtr12', True), ('n-gtr6', True), ('e-bass4', True),
    ('voice', False), ('violin', False), ('flute', False), ('leadSynthesizer', False),
    ('brassSynthesizer', False), ('synthBass', False), ('bassoon', False),
    ('acousticPiano', False), ('drumKit', False), ('drmkt', False),
])
def test_is_fretted_instrument(instrument, expected):
    assert is_fretted_instrument(instrument) is expected


def test_parse_tracks_drum_channel_is_not_tab():
    root = gpif('<Tracks>' + GP8_TRACK.format(id=0, name='Drums', channel=9) + '</Tracks>')
    [track] = parse_tracks(root)
    assert track.is_drum is True
    assert track.is_tab is False


def test_parse_tracks_without_tuning_is_not_tab():
    [track] = parse_tracks(gpif('<Tracks><Track id="0"><Name>Keys</Name></Track></Tracks>'))
    assert track.tuning == []
    assert track.is_tab is False


def test_parse_tracks_defaults():
    [track] = parse_tracks(gpif('<Tracks><Track id="5"/></Tracks>'))
    assert track.name == 'Track 5'
    assert track.program == 25      # acoustic guitar fallback
    assert track.channel == 5       # track id % 16
    assert track.capo == 0
    assert track.instrument is None
    assert track.is_fretted is False


def test_parse_tracks_default_channel_wraps_at_16():
    [track] = parse_tracks(gpif('<Tracks><Track id="17"/></Tracks>'))
    assert track.channel == 1


def test_parse_tracks_sorted_by_id():
    root = gpif('<Tracks>'
                + GP8_TRACK.format(id=2, name='C', channel=2)
                + GP8_TRACK.format(id=0, name='A', channel=0)
                + GP8_TRACK.format(id=1, name='B', channel=1)
                + '</Tracks>')
    assert [t.name for t in parse_tracks(root)] == ['A', 'B', 'C']


def test_parse_tracks_bar_index_counts_staves_in_document_order():
    piano = '<Track id="1"><Name>Piano</Name><Staves><Staff/><Staff/></Staves></Track>'
    root = gpif('<Tracks>'
                + GP8_TRACK.format(id=0, name='Gtr', channel=0)
                + piano
                + GP6_TRACK.replace('id="0"', 'id="2"')       # GP6: no <Staves>, one staff
                + GP8_TRACK.format(id=3, name='Gtr 2', channel=3)
                + '</Tracks>')
    assert [(t.bar_index, len(t.staves)) for t in parse_tracks(root)] == [
        (0, 1), (1, 2), (3, 1), (4, 1)]


def test_parse_tracks_staves_have_their_own_tuning_and_capo():
    xml = '''<Track id="0"><Name>Two staves</Name><Staves>
      <Staff><Properties>
        <Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property>
      </Properties></Staff>
      <Staff><Properties>
        <Property name="CapoFret"><Fret>3</Fret></Property>
        <Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property>
      </Properties></Staff>
    </Staves></Track>'''
    [track] = parse_tracks(gpif('<Tracks>' + xml + '</Tracks>'))
    assert track.staves == [Staff(tuning=[40, 45, 50, 55, 59, 64], capo=0),
                            Staff(tuning=[28, 33, 38, 43], capo=3)]
    # The track-level fields are the first staff's
    assert track.tuning == [40, 45, 50, 55, 59, 64]
    assert track.capo == 0


def test_parse_tracks_gp8_staff_falls_back_to_track_properties():
    xml = '''<Track id="0"><Staves><Staff><Properties/></Staff></Staves>
      <Properties><Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property></Properties>
    </Track>'''
    [track] = parse_tracks(gpif('<Tracks>' + xml + '</Tracks>'))
    assert track.staves == [Staff(tuning=[28, 33, 38, 43], capo=0)]

# ---------------------------------------------------------------------------
# parse_score_info
# ---------------------------------------------------------------------------

def test_parse_score_info():
    info = parse_score_info(gpif(
        '<Score><Title>Song</Title><Artist> Band </Artist><Album/><Tabber>me</Tabber></Score>'))
    assert info.title == 'Song'
    assert info.artist == 'Band'
    assert info.album == ''
    assert info.tabber == 'me'
    assert info.notices == ''


def test_parse_score_info_without_score():
    assert parse_score_info(gpif('')) == ScoreInfo()

# ---------------------------------------------------------------------------
# parse_master_bars / parse_bars / parse_voices
# ---------------------------------------------------------------------------

def test_parse_master_bars_preserves_order():
    root = gpif('''
      <MasterBars>
        <MasterBar><Time>4/4</Time><Bars>0 1 2</Bars></MasterBar>
        <MasterBar><Time>6/8</Time><Bars>3 4 5</Bars></MasterBar>
      </MasterBars>''')
    assert parse_master_bars(root) == [
        MasterBar(bar_ids=[0, 1, 2], numerator=4, denominator=4),
        MasterBar(bar_ids=[3, 4, 5], numerator=6, denominator=8),
    ]


def test_parse_master_bars_defaults_to_4_4_and_no_bars():
    [mb] = parse_master_bars(gpif('<MasterBars><MasterBar/></MasterBars>'))
    assert mb == MasterBar(bar_ids=[], numerator=4, denominator=4)


def test_parse_bars():
    root = gpif('''
      <Bars>
        <Bar id="0"><Voices>0 -1 -1 -1</Voices></Bar>
        <Bar id="1"><Voices>  </Voices></Bar>
      </Bars>''')
    # -1 marks an unused voice slot; the parser keeps it for the caller to skip
    assert parse_bars(root) == {
        0: Bar(voice_ids=[0, -1, -1, -1]),
        1: Bar(voice_ids=[]),
    }


def test_parse_voices():
    root = gpif('''
      <Voices>
        <Voice id="7"><Beats>10 11 12</Beats></Voice>
        <Voice id="8"/>
      </Voices>''')
    assert parse_voices(root) == {
        7: Voice(beat_ids=[10, 11, 12]),
        8: Voice(beat_ids=[]),
    }

# ---------------------------------------------------------------------------
# parse_beats
# ---------------------------------------------------------------------------

def test_parse_beats_chord():
    root = gpif('<Beats><Beat id="3"><Rhythm ref="2"/><Notes>4 5 6</Notes></Beat></Beats>')
    assert parse_beats(root) == {
        3: Beat(rhythm_id=2, note_ids=[4, 5, 6]),
    }


def test_parse_beats_rest_and_missing_rhythm():
    root = gpif('<Beats><Beat id="0"><Rest/></Beat></Beats>')
    assert parse_beats(root) == {
        0: Beat(is_rest=True),
    }

@pytest.mark.parametrize('xml, expected', [
    ('<Dynamic>FF</Dynamic>', 'FF'),
    ('<Dynamic> mp </Dynamic>', 'MP'),
    ('<Dynamic></Dynamic>', None),
    ('', None),
])
def test_parse_beats_dynamic(xml, expected):
    root = gpif(f'<Beats><Beat id="0"><Rhythm ref="0"/>{xml}<Notes>0</Notes></Beat></Beats>')
    assert parse_beats(root)[0].dynamic == expected

@pytest.mark.parametrize('xml, expected', [
    ('<GraceNotes>BeforeBeat</GraceNotes>', 'before'),
    ('<GraceNotes>OnBeat</GraceNotes>', 'on'),
    ('<GraceNotes>Other</GraceNotes>', None),
    ('', None),
])
def test_parse_beats_grace(xml, expected):
    root = gpif(f'<Beats><Beat id="0"><Rhythm ref="0"/>{xml}<Notes>0</Notes></Beat></Beats>')
    assert parse_beats(root)[0].grace == expected

@pytest.mark.parametrize('xml, expected', [
    ('<Property name="PickStroke"><Direction>Down</Direction></Property>', 'down'),
    ('<Property name="PickStroke"><Direction>Up</Direction></Property>', 'up'),
    # GP6 files are whitespace-indented
    ('<Property name="PickStroke">\n\t<Direction> Up </Direction>\n</Property>', 'up'),
    ('<Property name="PickStroke"><Direction>Sideways</Direction></Property>', None),
    ('<Property name="PickStroke"/>', None),
    # Other direction properties aren't pick strokes
    ('<Property name="Brush"><Direction>Up</Direction></Property>', None),
    ('', None),
])
def test_parse_beats_pick_stroke(xml, expected):
    root = gpif(f'<Beats><Beat id="0"><Rhythm ref="0"/><Notes>0</Notes>'
                f'<Properties>{xml}</Properties></Beat></Beats>')
    assert parse_beats(root)[0].pick_stroke == expected


@pytest.mark.parametrize('xml, expected', [
    ('<Properties><Property name="Brush"><Direction>Down</Direction></Property></Properties>', 'down'),
    # GP6 files are whitespace-indented
    ('<Properties><Property name="Brush">\n\t<Direction>Up</Direction>\n</Property></Properties>', 'up'),
    ('<Properties><Property name="PickStroke"><Direction>Up</Direction></Property></Properties>', None),
    ('', None),
])
def test_parse_beats_brush(xml, expected):
    root = gpif(f'<Beats><Beat id="0"><Rhythm ref="0"/><Notes>0</Notes>{xml}</Beat></Beats>')
    assert parse_beats(root)[0].brush == expected


@pytest.mark.parametrize('xml, expected', [
    ('<Arpeggio>Down</Arpeggio>', 'down'),
    ('<Arpeggio> Up </Arpeggio>', 'up'),
    ('<Arpeggio>Other</Arpeggio>', None),
    ('<Arpeggio/>', None),
    ('', None),
])
def test_parse_beats_arpeggio(xml, expected):
    root = gpif(f'<Beats><Beat id="0"><Rhythm ref="0"/>{xml}<Notes>0</Notes></Beat></Beats>')
    assert parse_beats(root)[0].arpeggio == expected

# ---------------------------------------------------------------------------
# parse_notes
# ---------------------------------------------------------------------------

def note_xml(note_id: int, props: str, extra: str = '') -> str:
    return f'<Note id="{note_id}">{extra}<Properties>{props}</Properties></Note>'


def test_parse_notes_gp8_with_midi():
    root = gpif('<Notes>' + note_xml(0, '''
        <Property name="Fret"><Fret>7</Fret></Property>
        <Property name="Midi"><Number>57</Number></Property>
        <Property name="String"><String>2</String></Property>''') + '</Notes>')
    assert parse_notes(root) == {
        0: Note(string=2, fret=7, midi=57),
    }


def test_parse_notes_gp6_without_midi():
    root = gpif('<Notes>' + note_xml(0, '''
        <Property name="String"><String>4</String></Property>
        <Property name="Fret"><Fret>3</Fret></Property>''') + '</Notes>')
    assert parse_notes(root)[0] == Note(string=4, fret=3)


def test_parse_notes_number_fallback():
    root = gpif('<Notes>' + note_xml(0, '''
        <Property name="String"><Number>1</Number></Property>
        <Property name="Fret"><Number>12</Number></Property>''') + '</Notes>')
    note = parse_notes(root)[0]
    assert (note.string, note.fret) == (1, 12)


def test_parse_notes_ignores_unknown_properties():
    root = gpif('<Notes>' + note_xml(0, '''
        <Property name="PalmMuted"><Enable/></Property>
        <Property name="Fret"><Fret>5</Fret></Property>''') + '</Notes>')
    assert parse_notes(root)[0].fret == 5


@pytest.mark.parametrize('tie, expected', [
    ('<Tie origin="true" destination="false"/>', False),
    ('<Tie origin="false" destination="true"/>', True),
    ('<Tie origin="true" destination="True"/>', True),
    ('', False),
])
def test_parse_notes_tie_destination(tie, expected):
    root = gpif('<Notes>' + note_xml(0, '', extra=tie) + '</Notes>')
    assert parse_notes(root)[0].is_tie_dest is expected

@pytest.mark.parametrize('accent_xml, accent, staccato', [
    ('', None, False),
    ('<Accent>1</Accent>', None, True),
    ('<Accent>8</Accent>', 'normal', False),
    ('<Accent>4</Accent>', 'heavy', False),
    ('<Accent>9</Accent>', 'normal', True),
    ('<Accent>12</Accent>', 'heavy', False),    # heavy wins over normal
    ('<Accent>junk</Accent>', None, False),
])
def test_parse_notes_accent_flags(accent_xml, accent, staccato):
    note = parse_notes(gpif('<Notes>' + note_xml(0, '', extra=accent_xml) + '</Notes>'))[0]
    assert (note.accent, note.staccato) == (accent, staccato)


def test_parse_notes_ghost():
    root = gpif('<Notes>'
                + note_xml(0, '', extra='<AntiAccent>Normal</AntiAccent>')
                + note_xml(1, '')
                + '</Notes>')
    notes = parse_notes(root)
    assert notes[0].ghost is True
    assert notes[1].ghost is False

def test_parse_notes_hopo_flags():
    root = gpif('<Notes>'
                + note_xml(0, '<Property name="HopoOrigin"><Enable/></Property>')
                + note_xml(1, '<Property name="HopoDestination"><Enable/></Property>')
                + note_xml(2, '<Property name="HopoOrigin"><Enable/></Property>'
                              '<Property name="HopoDestination"><Enable/></Property>')
                + note_xml(3, '')
                + '</Notes>')
    notes = parse_notes(root)
    assert [(n.hopo_origin, n.hopo_dest) for n in notes.values()] == [
        (True, False), (False, True), (True, True), (False, False),
    ]

def test_parse_notes_palm_muted_and_dead():
    root = gpif('<Notes>'
                + note_xml(0, '<Property name="PalmMuted"><Enable/></Property>')
                + note_xml(1, '<Property name="Muted"><Enable/></Property>')
                + note_xml(2, '')
                + '</Notes>')
    notes = parse_notes(root)
    assert [(n.palm_muted, n.dead) for n in notes.values()] == [
        (True, False), (False, True), (False, False),
    ]

@pytest.mark.parametrize('xml, expected', [
    ('<Vibrato>Slight</Vibrato>', 'slight'),
    ('<Vibrato>Wide</Vibrato>', 'wide'),
    ('<Vibrato>Other</Vibrato>', None),
    ('', None),
])
def test_parse_notes_vibrato(xml, expected):
    assert parse_notes(gpif('<Notes>' + note_xml(0, '', extra=xml) + '</Notes>'))[0].vibrato == expected


@pytest.mark.parametrize('flags, slide_in, slide_out', [
    (1, None, 'shift'),
    (2, None, 'legato'),
    (4, None, 'down'),
    (8, None, 'up'),
    (16, 'below', None),
    (32, 'above', None),
    (18, 'below', 'legato'),
    (20, 'below', 'down'),
    (0, None, None),
])
def test_parse_notes_slide_flags(flags, slide_in, slide_out):
    prop = f'<Property name="Slide"><Flags>{flags}</Flags></Property>'
    note = parse_notes(gpif('<Notes>' + note_xml(0, prop) + '</Notes>'))[0]
    assert (note.slide_in, note.slide_out) == (slide_in, slide_out)

# ---------------------------------------------------------------------------
# Harmonics
# ---------------------------------------------------------------------------

def harmonic_props(htype: str, hfret: str, gp8: bool = True) -> str:
    enable = '<Property name="Harmonic"><Enable/></Property>' if gp8 else ''
    return (enable
            + f'<Property name="HarmonicType"><HType>{htype}</HType></Property>'
            + f'<Property name="HarmonicFret"><HFret>{hfret}</HFret></Property>')


@pytest.mark.parametrize('gp8', [True, False])
def test_parse_notes_harmonic(gp8):
    root = gpif('<Notes>' + note_xml(0, harmonic_props('Artificial', '12.000000', gp8)) + '</Notes>')
    assert parse_notes(root)[0].harmonic == Harmonic(type='artificial', fret=12.0)


@pytest.mark.parametrize('props', [
    harmonic_props('Unknown', '12'),
    harmonic_props('Natural', 'junk'),
    '<Property name="HarmonicType"><HType>Natural</HType></Property>',   # no fret
    '',
])
def test_parse_notes_no_harmonic(props):
    assert parse_notes(gpif('<Notes>' + note_xml(0, props) + '</Notes>'))[0].harmonic is None


# ---------------------------------------------------------------------------
# Bends (bend_points and parse_notes)
# ---------------------------------------------------------------------------

def bend_xml(**props: float) -> str:
    """GP8-style Bend* properties, e.g. bend_xml(OriginValue=0, DestinationValue=100)."""
    return ''.join(f'<Property name="Bend{k}"><Float>{v}</Float></Property>'
                   for k, v in props.items())


def bent_note(**props: float) -> Note:
    root = gpif('<Notes>' + note_xml(0, '<Property name="Bended"><Enable/></Property>'
                                        + bend_xml(**props)) + '</Notes>')
    return parse_notes(root)[0]


def test_bend_full_gp6_defaults():
    # GP6 omits offsets: origin at 0%, destination at 100%; 100 = 2 semitones
    assert bent_note(OriginValue=0, DestinationValue=100).bend == [(0.0, 0.0), (1.0, 2.0)]


def test_bend_gp8_plain_bend_with_middle():
    note = bent_note(OriginOffset=0, OriginValue=0, MiddleOffset1=12, MiddleOffset2=12,
                     MiddleValue=50, DestinationOffset=25, DestinationValue=100)
    assert note.bend == [(0.0, 0.0), (0.12, 1.0), (0.12, 1.0), (0.25, 2.0)]


def test_bend_middle_points_after_destination_are_dropped():
    # GP8 writes a middle point at 100% even for a plain bend that ends at 50%
    note = bent_note(OriginOffset=0, OriginValue=0, MiddleOffset1=50, MiddleOffset2=50,
                     MiddleValue=50, DestinationOffset=26, DestinationValue=100)
    assert note.bend == [(0.0, 0.0), (0.26, 2.0)]


def test_bend_and_release():
    note = bent_note(OriginOffset=0, OriginValue=0, MiddleOffset1=25, MiddleOffset2=50,
                     MiddleValue=100, DestinationOffset=75, DestinationValue=0)
    assert note.bend == [(0.0, 0.0), (0.25, 2.0), (0.5, 2.0), (0.75, 0.0)]


def test_bend_middle_without_offsets_sits_at_half():
    # GP6 pre-bend, bend further, release
    note = bent_note(OriginValue=50, MiddleValue=100, DestinationValue=0)
    assert note.bend == [(0.0, 1.0), (0.5, 2.0), (1.0, 0.0)]


def test_bend_wide_values():
    assert bent_note(OriginValue=250, DestinationValue=0).bend == [(0.0, 5.0), (1.0, 0.0)]


def test_bended_without_values_is_no_bend():
    assert bent_note().bend is None


def test_bend_values_without_bended_flag_are_ignored():
    root = gpif('<Notes>' + note_xml(0, bend_xml(OriginValue=0, DestinationValue=100)) + '</Notes>')
    assert parse_notes(root)[0].bend is None


def test_bend_points_direct():
    assert bend_points({}) is None
    assert bend_points({'BendDestinationValue': 50.0}) == [(0.0, 0.0), (1.0, 1.0)]

# ---------------------------------------------------------------------------
# parse_rhythms
# ---------------------------------------------------------------------------

def rhythm(value: str, inner: str = '') -> Rhythm:
    root = gpif(f'<Rhythms><Rhythm id="0"><NoteValue>{value}</NoteValue>{inner}</Rhythm></Rhythms>')
    return parse_rhythms(root)[0]


@pytest.mark.parametrize('value, beats', [
    ('Whole', 4.0), ('Half', 2.0), ('Quarter', 1.0), ('Eighth', 0.5),
    ('16th', 0.25), ('32nd', 0.125), ('64th', 0.0625), ('128th', 0.03125),
])
def test_parse_rhythms_note_values(value, beats):
    r = rhythm(value)
    assert r.beats == beats
    assert r.ticks == round(beats * TICKS_PER_BEAT)


def test_parse_rhythms_unknown_value_is_quarter():
    assert rhythm('256th').beats == 1.0


def test_parse_rhythms_missing_value_is_quarter():
    assert parse_rhythms(gpif('<Rhythms><Rhythm id="0"/></Rhythms>'))[0].beats == 1.0


def test_parse_rhythms_dotted():
    r = rhythm('Quarter', '<AugmentationDot><Enable>true</Enable></AugmentationDot>')
    assert r == Rhythm(beats=1.5, ticks=720)


def test_parse_rhythms_triplet():
    r = rhythm('Eighth', '<PrimaryTuplet><Num>3</Num><Den>2</Den></PrimaryTuplet>')
    assert r.beats == pytest.approx(1 / 3)
    assert r.ticks == 160


def test_parse_rhythms_dotted_triplet():
    r = rhythm('Quarter', '<AugmentationDot><Enable>true</Enable></AugmentationDot>'
                          '<PrimaryTuplet><Num>3</Num><Den>2</Den></PrimaryTuplet>')
    assert r.ticks == 480


def test_parse_rhythms_gp8_forms():
    # How GP6-8 files actually write dots and tuplets: attributes
    assert rhythm('Quarter', '<AugmentationDot count="1"/>').ticks == 720
    assert rhythm('Quarter', '<AugmentationDot count="2"/>').ticks == 840
    r = rhythm('Eighth', '<PrimaryTuplet num="3" den="2"/>')
    assert (r.beats, r.ticks) == (pytest.approx(1 / 3), 160)
    assert rhythm('Quarter', '<AugmentationDot count="1"/><PrimaryTuplet num="3" den="2"/>').ticks == 480


def test_parse_rhythms_secondary_tuplet():
    # A quintuplet inside a triplet: × 2/3 × 4/5
    r = rhythm('16th', '<PrimaryTuplet num="3" den="2"/><SecondaryTuplet num="5" den="4"/>')
    assert r.ticks == round(120 * 2 / 3 * 4 / 5)


def test_parse_rhythms_ignores_one_to_one_tuplet():
    assert rhythm('Quarter', '<PrimaryTuplet><Num>1</Num><Den>1</Den></PrimaryTuplet>').ticks == 480

# ---------------------------------------------------------------------------
# parse_tempos
# ---------------------------------------------------------------------------

def automation(bar: int, position: float, value: str, kind: str = 'Tempo') -> str:
    return (f'<Automation><Type>{kind}</Type><Bar>{bar}</Bar>'
            f'<Position>{position}</Position><Value>{value}</Value></Automation>')


def test_parse_tempos_sorted_and_first_value_token():
    root = gpif('<MasterTrack><Automations>'
                + automation(4, 0, '100 2')
                + automation(0, 0.5, '90 2')
                + automation(0, 0, '72 2')
                + automation(1, 0, '1', kind='SyncPoint')
                + '</Automations></MasterTrack>')
    assert parse_tempos(root) == [
        Tempo(bar=0, position=0.0, bpm=72.0),
        Tempo(bar=0, position=0.5, bpm=90.0),
        Tempo(bar=4, position=0.0, bpm=100.0),
    ]


def test_parse_tempos_falls_back_to_score_tempo():
    root = gpif('<Score><Tempo><Value>140</Value></Tempo></Score>')
    assert parse_tempos(root) == [Tempo(bar=0, position=0.0, bpm=140.0)]


def test_parse_tempos_defaults_to_120():
    assert parse_tempos(gpif('')) == [Tempo(bar=0, position=0.0, bpm=120.0)]

# ---------------------------------------------------------------------------
# Source elements (raw XML for what isn't parsed)
# ---------------------------------------------------------------------------

def test_parsers_keep_source_elements():
    root = gpif('<Score><Title>T</Title></Score>'
                '<MasterTrack><Automations>' + automation(0, 0, '90') + '</Automations></MasterTrack>'
                '<Tracks>' + GP8_TRACK.format(id=0, name='Gtr', channel=0) + GP6_TRACK.replace('id="0"', 'id="1"')
                + '</Tracks>'
                '<MasterBars><MasterBar><Bars>0 1</Bars></MasterBar></MasterBars>'
                '<Bars><Bar id="0"><Voices>0</Voices></Bar></Bars>'
                '<Voices><Voice id="0"><Beats>0</Beats></Voice></Voices>'
                '<Beats><Beat id="0"><Rhythm ref="0"/><Notes>0</Notes></Beat></Beats>'
                '<Notes>' + note_xml(0, '') + '</Notes>'
                '<Rhythms><Rhythm id="0"><NoteValue>Quarter</NoteValue></Rhythm></Rhythms>')
    gp8, gp6 = parse_tracks(root)
    assert gp8.element.tag == 'Track' and gp8.element.get('id') == '0'
    assert gp8.staves[0].element.tag == 'Staff'
    assert gp6.staves[0].element is None                    # GP6: no <Staff>
    assert parse_score_info(root).element.tag == 'Score'
    assert parse_master_bars(root)[0].element.tag == 'MasterBar'
    assert parse_bars(root)[0].element.tag == 'Bar'
    assert parse_voices(root)[0].element.tag == 'Voice'
    assert parse_beats(root)[0].element.tag == 'Beat'
    assert parse_notes(root)[0].element.tag == 'Note'
    assert parse_rhythms(root)[0].element.tag == 'Rhythm'
    assert parse_tempos(root)[0].element.tag == 'Automation'


def test_score_tempo_fallback_has_no_element():
    assert parse_tempos(gpif(''))[0].element is None


def test_beat_properties():
    root = gpif('<Beats><Beat id="0"><Properties>'
                '<Property name="Brush"><Direction>Up</Direction></Property>'
                '<Property name="Slapped"><Enable/></Property>'
                '</Properties></Beat></Beats>')
    assert parse_beats(root)[0].properties == {'Brush': 'Up', 'Slapped': ''}

