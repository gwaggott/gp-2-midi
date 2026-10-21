"""Tests for gpinfo.py: the per-file summary."""

from gpinfo import file_info


def test_gp5_file_info_and_directory_listing(tmp_path):
    # A GP5 song built in code (the GP3-5 files in in/ aren't used in tests)
    import guitarpro as gp
    from gpinfo import find_files
    song = gp.Song(title='Song', artist='Band')
    song.tracks[0].name, song.tracks[0].offset = 'Guitar', 3
    song.tracks[0].strings = [gp.GuitarString(n, v)
                              for n, v in enumerate([64, 59, 55, 50, 45, 38], 1)]
    song.tracks.append(gp.Track(song, number=2, name='Bass',
                                channel=gp.MidiChannel(channel=2, effectChannel=3, instrument=33),
                                strings=[gp.GuitarString(n, v) for n, v in enumerate([43, 38, 33, 28], 1)]))
    song.tracks.append(gp.Track(song, number=3, name='Vocal',
                                channel=gp.MidiChannel(channel=4, effectChannel=5, instrument=53)))
    song.tracks.append(gp.Track(song, number=4, name='Drums', isPercussionTrack=True,
                                channel=gp.MidiChannel(channel=9, effectChannel=9, instrument=0)))
    path = tmp_path / 'song.gp5'
    gp.write(song, str(path))
    (tmp_path / 'notes.txt').write_text('not a tab')

    assert find_files([str(tmp_path)]) == [path]
    info = file_info(path)
    assert (info['artist'], info['title']) == ('Band', 'Song')
    assert [t['name'] for t in info['tracks']] == ['Guitar', 'Bass']       # not the vocal or drums
    guitar, bass = info['tracks']
    assert (guitar['tuning_name'], guitar['capo']) == ('Drop D', 3)
    assert guitar['instrument'] == 'Acoustic Guitar (steel)'
    assert (bass['tuning_notes'], bass['tuning_name']) == (['E1', 'A1', 'D2', 'G2'], 'Standard')
