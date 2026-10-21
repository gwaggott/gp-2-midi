"""Tests for the readers (gpif/readers/): load_gpif_xml, load_score, reader_for and the GP6 BCFZ/BCFS containers."""

import zipfile

import pytest

from gpif import (
    Gp6Reader,
    Gp7Reader,
    GpifXmlReader,
    Note,
    Score,
    ScoreReader,
    load_gpif_xml,
    load_score,
    parse_bars,
    parse_beats,
    parse_master_bars,
    parse_notes,
    parse_rhythms,
    parse_score_info,
    parse_tempos,
    parse_tracks,
    parse_voices,
    reader_for,
    track_bars,
)
from gpif.readers import registry
from gpif.readers.containers import _bcfs_files, _bcfz_decompress

SCORE_XML = b'<GPIF><Score><Title>Test</Title></Score></GPIF>'
SECTOR = 0x1000

# ---------------------------------------------------------------------------
# Test encoders for the GP6 formats
# ---------------------------------------------------------------------------

class BitWriter:
    """Write bits MSB-first within each byte, as the BCFZ reader expects."""

    def __init__(self) -> None:
        self.bits: list[int] = []

    def msb(self, value: int, count: int) -> None:
        self.bits += [(value >> i) & 1 for i in range(count - 1, -1, -1)]

    def lsb(self, value: int, count: int) -> None:
        self.bits += [(value >> i) & 1 for i in range(count)]

    def literal(self, chunk: bytes) -> None:
        assert 1 <= len(chunk) <= 3
        self.msb(0, 1)
        self.lsb(len(chunk), 2)
        for b in chunk:
            self.msb(b, 8)

    def backref(self, offset: int, length: int, word_size: int = 8) -> None:
        self.msb(1, 1)
        self.msb(word_size, 4)
        self.lsb(offset, word_size)
        self.lsb(length, word_size)

    def to_bytes(self) -> bytes:
        padded = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(
            int(''.join(map(str, padded[i:i + 8])), 2) for i in range(0, len(padded), 8)
        )


def bcfz_payload(writer: BitWriter, expected_len: int) -> bytes:
    """BCFZ payload (after the magic): int32 LE length + bit stream."""
    return expected_len.to_bytes(4, 'little') + writer.to_bytes()


def bcfz_literals(data: bytes) -> bytes:
    """Encode data as BCFZ using only literal chunks."""
    w = BitWriter()
    for i in range(0, len(data), 3):
        w.literal(data[i:i + 3])
    return bcfz_payload(w, len(data))


def bcfz_compress(data: bytes, min_match: int = 4, window: int = 4095) -> bytes:
    """
    Encode data as BCFZ with back-references, as Guitar Pro's compressor
    does: greedy longest match within `window` bytes back (the reader copies
    min(offset, length) bytes, so a match is at most its offset long), else
    literal chunks of up to 3 bytes.
    """
    w = BitWriter()
    starts: dict[bytes, list[int]] = {}       # 3-byte prefix → earlier positions
    literals = bytearray()
    i = 0

    def flush() -> None:
        for j in range(0, len(literals), 3):
            w.literal(bytes(literals[j:j + 3]))
        literals.clear()

    while i < len(data):
        best_len, best_off = 0, 0
        for start in reversed(starts.get(data[i:i + 3], [])[-16:]):
            offset = i - start
            if offset > window:
                break
            length = 0
            while (length < offset and i + length < len(data)
                   and data[start + length] == data[i + length]):
                length += 1
            if length > best_len:
                best_len, best_off = length, offset
        if best_len >= min_match:
            flush()
            w.backref(best_off, best_len, word_size=max(best_off.bit_length(), best_len.bit_length()))
            step = best_len
        else:
            literals.append(data[i])
            step = 1
        for k in range(i, i + step):
            starts.setdefault(data[k:k + 3], []).append(k)
        i += step
    flush()
    return bcfz_payload(w, len(data))


def bcfs_container(files: dict[str, bytes]) -> bytes:
    """
    Build a BCFS container (without the 'BCFS' magic): one entry sector per
    file followed by its data sectors.
    """
    sectors: list[bytes] = []
    for name, content in files.items():
        entry_idx = len(sectors)
        n_data = max(1, -(-len(content) // SECTOR))
        data_idxs = list(range(entry_idx + 1, entry_idx + 1 + n_data))

        entry = bytearray(SECTOR)
        entry[0:4] = (2).to_bytes(4, 'little')
        entry[0x04:0x04 + len(name)] = name.encode()
        entry[0x8C:0x90] = len(content).to_bytes(4, 'little')
        for i, idx in enumerate(data_idxs):
            entry[0x94 + 4 * i:0x98 + 4 * i] = idx.to_bytes(4, 'little')
        sectors.append(bytes(entry))

        for i in range(n_data):
            sectors.append(content[i * SECTOR:(i + 1) * SECTOR].ljust(SECTOR, b'\0'))
    return b''.join(sectors)

# ---------------------------------------------------------------------------
# _bcfz_decompress
# ---------------------------------------------------------------------------

def test_bcfz_literals_only():
    data = b'hello, world'
    assert _bcfz_decompress(bcfz_literals(data)) == data


def test_bcfz_back_reference():
    w = BitWriter()
    w.literal(b'abc')
    w.backref(offset=3, length=3)
    assert _bcfz_decompress(bcfz_payload(w, 6)) == b'abcabc'


def test_bcfz_back_reference_length_capped_at_offset():
    # Copies min(offset, length) bytes: a run is built from repeated chunks
    w = BitWriter()
    w.literal(b'ab')
    w.backref(offset=2, length=5)
    w.backref(offset=4, length=4)
    assert _bcfz_decompress(bcfz_payload(w, 6)) == b'ababab'


def test_bcfz_truncates_to_expected_length():
    w = BitWriter()
    w.literal(b'abc')
    assert _bcfz_decompress(bcfz_payload(w, 2)) == b'ab'


def test_bcfz_stops_when_bits_run_out():
    w = BitWriter()
    w.literal(b'ab')
    assert _bcfz_decompress(bcfz_payload(w, 100)) == b'ab'


def test_bcfz_back_reference_before_start_is_corrupt():
    w = BitWriter()
    w.literal(b'a')
    w.backref(offset=5, length=1)
    with pytest.raises(ValueError, match='Corrupt'):
        _bcfz_decompress(bcfz_payload(w, 2))

# ---------------------------------------------------------------------------
# _bcfs_files
# ---------------------------------------------------------------------------

def test_bcfs_single_file():
    assert _bcfs_files(bcfs_container({'score.gpif': SCORE_XML})) == {'score.gpif': SCORE_XML}


def test_bcfs_file_spanning_sectors_is_trimmed_to_size():
    content = bytes(range(256)) * 20      # 5120 bytes → 2 sectors
    files = _bcfs_files(bcfs_container({'big.bin': content, 'score.gpif': SCORE_XML}))
    assert files == {'big.bin': content, 'score.gpif': SCORE_XML}

# ---------------------------------------------------------------------------
# load_gpif_xml
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('member', ['Content/score.gpif', 'score.gpif'])
def test_load_zip(tmp_path, member):
    path = tmp_path / 'song.gp'
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('VERSION', '7.0')
        zf.writestr(member, SCORE_XML)
    assert load_gpif_xml(str(path)).findtext('./Score/Title') == 'Test'


def test_load_zip_without_score(tmp_path):
    path = tmp_path / 'song.gp'
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('other.txt', 'x')
    with pytest.raises(ValueError, match='score.gpif not found'):
        load_gpif_xml(str(path))


def test_load_bcfs(tmp_path):
    path = tmp_path / 'song.gpx'
    path.write_bytes(b'BCFS' + bcfs_container({'misc.xml': b'<x/>', 'score.gpif': SCORE_XML}))
    assert load_gpif_xml(str(path)).findtext('./Score/Title') == 'Test'


def test_load_bcfz(tmp_path):
    path = tmp_path / 'song.gpx'
    container = b'BCFS' + bcfs_container({'score.gpif': SCORE_XML})
    path.write_bytes(b'BCFZ' + bcfz_literals(container))
    assert load_gpif_xml(str(path)).findtext('./Score/Title') == 'Test'


def test_load_bcfz_not_bcfs(tmp_path):
    path = tmp_path / 'song.gpx'
    path.write_bytes(b'BCFZ' + bcfz_literals(b'NOPE' + bytes(16)))
    with pytest.raises(ValueError, match='BCFS'):
        load_gpif_xml(str(path))


def test_load_bcfs_without_score(tmp_path):
    path = tmp_path / 'song.gpx'
    path.write_bytes(b'BCFS' + bcfs_container({'misc.xml': b'<x/>'}))
    with pytest.raises(ValueError, match='score.gpif not found'):
        load_gpif_xml(str(path))


def test_load_raw_xml_ignores_extension(tmp_path):
    path = tmp_path / 'song.gp'      # format comes from content, not suffix
    path.write_bytes(SCORE_XML)
    assert load_gpif_xml(str(path)).findtext('./Score/Title') == 'Test'

# ---------------------------------------------------------------------------
# Readers and the registry
# ---------------------------------------------------------------------------

def write_formats(tmp_path) -> dict[type, object]:
    """One synthetic file per GPIF reader, each holding SCORE_XML."""
    paths = {Gp7Reader: tmp_path / 'song.gp', Gp6Reader: tmp_path / 'song.gpx',
             GpifXmlReader: tmp_path / 'song.gpif'}
    with zipfile.ZipFile(paths[Gp7Reader], 'w') as zf:
        zf.writestr('Content/score.gpif', SCORE_XML)
    container = b'BCFS' + bcfs_container({'score.gpif': SCORE_XML})
    paths[Gp6Reader].write_bytes(b'BCFZ' + bcfz_literals(container))
    paths[GpifXmlReader].write_bytes(SCORE_XML)
    return paths


def test_reader_for_detects_format_by_content(tmp_path):
    for reader_class, path in write_formats(tmp_path).items():
        assert type(reader_for(path)) is reader_class
        renamed = path.rename(path.with_suffix('.bin'))     # suffix doesn't matter
        assert type(reader_for(renamed)) is reader_class


def test_reader_for_plain_bcfs(tmp_path):
    path = tmp_path / 'song.gpx'
    path.write_bytes(b'BCFS' + bcfs_container({'score.gpif': SCORE_XML}))
    assert type(reader_for(path)) is Gp6Reader


def test_each_reader_reads_a_score(tmp_path):
    for reader_class, path in write_formats(tmp_path).items():
        score = reader_class().read(path)
        assert isinstance(score, Score)
        assert score.info.title == 'Test'
        assert score.root.tag == 'GPIF'


def test_reader_for_with_no_matching_reader(tmp_path, monkeypatch):
    path = tmp_path / 'song.gp'
    path.write_bytes(SCORE_XML)
    monkeypatch.setattr(registry, 'READERS', [])
    with pytest.raises(ValueError, match='not a Guitar Pro file'):
        reader_for(path)


class OtherFormatReader(ScoreReader):
    """A non-GPIF reader, as the GP3-5 readers will be."""
    name = 'Other'

    @classmethod
    def sniff(cls, head):
        return head.startswith(b'OTHER')

    def read(self, filepath):
        return Score([], [], {}, {}, {}, {}, {}, [])


def test_registry_with_a_non_gpif_reader(tmp_path, monkeypatch):
    path = tmp_path / 'song.oth'
    path.write_bytes(b'OTHER format')
    monkeypatch.setattr(registry, 'READERS', [OtherFormatReader(), *registry.READERS])
    assert load_score(path).tracks == []
    with pytest.raises(ValueError, match='Other file has no GPIF XML'):
        load_gpif_xml(path)


def test_score_reader_is_abstract(tmp_path):
    with pytest.raises(NotImplementedError):
        ScoreReader.sniff(b'')
    with pytest.raises(NotImplementedError):
        ScoreReader().read(tmp_path / 'x')

# ---------------------------------------------------------------------------
# A whole score, in every container
# ---------------------------------------------------------------------------

# A small but complete GPIF document: a GP8-style track with two staves
# (each with its tuning), a GP6-style track and a drum track, two bars, a
# tempo change, beats with a brush, a let-ring note and a whammy bar, and
# triplet and dotted rhythms, in the attribute forms Guitar Pro writes
FULL_SCORE_XML = b"""<GPIF>
<Score><Title>Synthetic</Title><Artist>Test</Artist></Score>
<MasterTrack><Automations>
  <Automation><Type>Tempo</Type><Bar>0</Bar><Position>0</Position><Value>90 2</Value></Automation>
  <Automation><Type>Tempo</Type><Bar>1</Bar><Position>0</Position><Value>120 2</Value></Automation>
</Automations></MasterTrack>
<Tracks>
  <Track id="0"><Name>Two staves</Name>
    <InstrumentSet><Type>electricGuitar</Type></InstrumentSet>
    <Staves>
      <Staff><Properties><Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property></Properties></Staff>
      <Staff><Properties><Property name="Tuning"><Pitches>38 45 50 55 59 64</Pitches></Property></Properties></Staff>
    </Staves>
    <MidiConnection><PrimaryChannel>0</PrimaryChannel></MidiConnection>
  </Track>
  <Track id="1"><Name>GP6 bass</Name><Instrument ref="e-bass4"/>
    <Properties><Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property></Properties>
    <GeneralMidi><Program>33</Program><Channel>2</Channel></GeneralMidi>
  </Track>
  <Track id="2"><Name>Drums</Name><MidiConnection><PrimaryChannel>9</PrimaryChannel></MidiConnection></Track>
</Tracks>
<MasterBars>
  <MasterBar><Time>4/4</Time><Bars>0 1 2 3</Bars></MasterBar>
  <MasterBar><Time>4/4</Time><Bars>4 5 6 7</Bars></MasterBar>
</MasterBars>
<Bars>
  <Bar id="0"><Voices>0</Voices></Bar><Bar id="1"><Voices>1</Voices></Bar>
  <Bar id="2"><Voices>2</Voices></Bar><Bar id="3"><Voices>3</Voices></Bar>
  <Bar id="4"><Voices>0</Voices></Bar><Bar id="5"><Voices>1</Voices></Bar>
  <Bar id="6"><Voices>2</Voices></Bar><Bar id="7"><Voices>3</Voices></Bar>
</Bars>
<Voices>
  <Voice id="0"><Beats>0 1 1 1 2</Beats></Voice>
  <Voice id="1"><Beats>3</Beats></Voice>
  <Voice id="2"><Beats>4</Beats></Voice>
  <Voice id="3"><Beats>5</Beats></Voice>
</Voices>
<Beats>
  <Beat id="0"><Rhythm ref="0"/><Notes>0 1</Notes><Dynamic>F</Dynamic>
    <Properties><Property name="Brush"><Direction>Down</Direction></Property></Properties></Beat>
  <Beat id="1"><Rhythm ref="1"/><Notes>2</Notes></Beat>
  <Beat id="2"><Rhythm ref="2"/><Notes>3</Notes><Whammy originValue="0" middleValue="0" destinationValue="-100"/></Beat>
  <Beat id="3"><Rhythm ref="3"/><Notes>4</Notes></Beat>
  <Beat id="4"><Rhythm ref="3"/><Rest/></Beat>
  <Beat id="5"><Rhythm ref="3"/><Notes>5</Notes></Beat>
</Beats>
<Notes>
  <Note id="0"><LetRing/><Properties><Property name="String"><String>0</String></Property>
    <Property name="Fret"><Fret>3</Fret></Property><Property name="Midi"><Number>43</Number></Property></Properties></Note>
  <Note id="1"><Properties><Property name="String"><String>1</String></Property>
    <Property name="Fret"><Fret>2</Fret></Property></Properties></Note>
  <Note id="2"><Properties><Property name="String"><String>2</String></Property>
    <Property name="Fret"><Fret>5</Fret></Property></Properties></Note>
  <Note id="3"><Properties><Property name="String"><String>3</String></Property>
    <Property name="Fret"><Fret>7</Fret></Property><Property name="PalmMuted"><Enable/></Property></Properties></Note>
  <Note id="4"><Properties><Property name="String"><String>0</String></Property>
    <Property name="Fret"><Fret>0</Fret></Property></Properties></Note>
  <Note id="5"><Properties><Property name="String"><String>0</String></Property>
    <Property name="Fret"><Fret>36</Fret></Property></Properties></Note>
</Notes>
<Rhythms>
  <Rhythm id="0"><NoteValue>Quarter</NoteValue></Rhythm>
  <Rhythm id="1"><NoteValue>Eighth</NoteValue><PrimaryTuplet num="3" den="2"/></Rhythm>
  <Rhythm id="2"><NoteValue>Quarter</NoteValue><AugmentationDot count="1"/></Rhythm>
  <Rhythm id="3"><NoteValue>Whole</NoteValue></Rhythm>
</Rhythms>
</GPIF>"""


def write_full_score(tmp_path) -> dict[type, object]:
    """FULL_SCORE_XML as a .gp zip, a compressed .gpx (with back-references) and raw XML."""
    paths = {Gp7Reader: tmp_path / 'full.gp', Gp6Reader: tmp_path / 'full.gpx',
             GpifXmlReader: tmp_path / 'full.gpif'}
    with zipfile.ZipFile(paths[Gp7Reader], 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('VERSION', '7.0')
        zf.writestr('Content/score.gpif', FULL_SCORE_XML)
    container = b'BCFS' + bcfs_container({'misc.xml': b'<x/>' * 300, 'score.gpif': FULL_SCORE_XML})
    paths[Gp6Reader].write_bytes(b'BCFZ' + bcfz_compress(container))
    paths[GpifXmlReader].write_bytes(FULL_SCORE_XML)
    return paths


def test_bcfz_compress_uses_back_references():
    container = b'BCFS' + bcfs_container({'score.gpif': FULL_SCORE_XML})
    compressed = bcfz_compress(container)
    assert len(compressed) < len(container) / 4            # zero-filled sectors, repeated XML
    assert _bcfz_decompress(compressed) == container


@pytest.mark.parametrize('reader_class', [Gp7Reader, Gp6Reader, GpifXmlReader])
def test_load_score_matches_parse_functions(tmp_path, reader_class):
    path = write_full_score(tmp_path)[reader_class]
    assert type(reader_for(path)) is reader_class
    score = load_score(path)                                 # a Path
    root = load_gpif_xml(str(path))                           # a str
    parsers = {'tracks': parse_tracks, 'master_bars': parse_master_bars, 'bars': parse_bars,
               'voices': parse_voices, 'beats': parse_beats, 'notes': parse_notes,
               'rhythms': parse_rhythms, 'tempos': parse_tempos, 'info': parse_score_info}
    for section, parse in parsers.items():
        assert getattr(score, section) == parse(root), section
    assert (score.info.title, score.info.artist) == ('Synthetic', 'Test')
    assert score.root.findtext('./Score/Title') == 'Synthetic'


@pytest.mark.parametrize('reader_class', [Gp7Reader, Gp6Reader, GpifXmlReader])
def test_full_score_contents(tmp_path, reader_class):
    score = load_score(write_full_score(tmp_path)[reader_class])
    two_staves, bass, drums = score.tracks
    assert [len(t.staves) for t in score.tracks] == [2, 1, 1]
    assert [t.bar_index for t in score.tracks] == [0, 2, 3]
    assert two_staves.staves[1].tuning == [38, 45, 50, 55, 59, 64]
    assert (bass.program, bass.channel, bass.is_fretted) == (33, 2, True)
    assert drums.is_drum and not drums.is_tab
    assert {len(mb.bar_ids) for mb in score.master_bars} == {4}
    assert track_bars(score, drums)[1] is score.bars[score.master_bars[1].bar_ids[3]]
    assert track_bars(score, two_staves, staff=1)[0] is score.bars[1]
    assert [t.bpm for t in score.tempos] == [90.0, 120.0]
    # Rhythms in the attribute forms: a triplet eighth and a dotted quarter
    assert [score.rhythms[i].ticks for i in range(4)] == [480, 160, 720, 1920]
    assert score.notes[0] == Note(string=0, fret=3, midi=43)
    assert score.notes[3].palm_muted


@pytest.mark.parametrize('reader_class', [Gp7Reader, Gp6Reader, GpifXmlReader])
def test_unparsed_data_via_element_and_properties(tmp_path, reader_class):
    score = load_score(write_full_score(tmp_path)[reader_class])
    assert score.notes[0].element.find('LetRing') is not None    # a Note child element
    assert score.beats[0].properties['Brush'] == 'Down'          # a Beat property
    whammy = score.beats[2].element.find('Whammy')               # attributes on a Beat child
    assert float(whammy.get('destinationValue')) == -100.0

# ---------------------------------------------------------------------------
# The user's own files in in/ (git-ignored; skipped when there are none)
# ---------------------------------------------------------------------------

INPUT_SUFFIXES = ('.gp', '.gpx', '.gpif', '.gp3', '.gp4', '.gp5')


def test_all_input_files_load(in_dir):
    # A check over whatever Guitar Pro files are in in/, in every format;
    # unit tests don't depend on any of them
    paths = sorted(p for p in in_dir.glob('*') if p.suffix.lower() in INPUT_SUFFIXES)
    if not paths:
        pytest.skip('no Guitar Pro files in in/')
    for path in paths:
        score = load_score(path)
        assert score.tracks and score.master_bars, path.name
