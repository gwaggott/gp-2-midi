"""Tests for gpif/score.py: Score and track_bars (load_score is in test_loading.py)."""

import pytest

from gpif import Bar, MasterBar, Score, Staff, Track, track_bars


def score_with_bars(tracks: list[Track], master_bars: list[MasterBar]) -> Score:
    bar_ids = {i for mb in master_bars for i in mb.bar_ids}
    return Score(tracks=tracks, master_bars=master_bars,
                 bars={i: Bar(voice_ids=[i]) for i in bar_ids if 0 <= i < 50},
                 voices={}, beats={}, notes={}, rhythms={}, tempos=[])


def test_track_bars_skips_earlier_tracks_staves():
    # Track 0 has two staves, so track 1's bars are third in MasterBar/Bars
    tracks = [Track(id=0, bar_index=0, staves=[Staff(), Staff()]),
              Track(id=1, bar_index=2)]
    score = score_with_bars(tracks, [
        MasterBar(bar_ids=[0, 1, 2]),
        MasterBar(bar_ids=[3, 4, 5]),
    ])
    assert track_bars(score, tracks[1]) == [Bar(voice_ids=[2]), Bar(voice_ids=[5])]
    assert track_bars(score, tracks[0]) == [Bar(voice_ids=[0]), Bar(voice_ids=[3])]
    assert track_bars(score, tracks[0], staff=1) == [Bar(voice_ids=[1]), Bar(voice_ids=[4])]


def test_track_bars_none_where_missing():
    track = Track(id=1, bar_index=1)
    score = score_with_bars([track], [
        MasterBar(bar_ids=[0, 1]),
        MasterBar(bar_ids=[2, 99]),       # unknown bar id
        MasterBar(bar_ids=[3]),           # too few ids
        MasterBar(bar_ids=[4, -1]),
    ])
    assert track_bars(score, track) == [Bar(voice_ids=[1]), None, None, None]


@pytest.mark.parametrize('staff', [-1, 1])
def test_track_bars_rejects_missing_staff(staff):
    track = Track(id=0)
    with pytest.raises(IndexError):
        track_bars(score_with_bars([track], [MasterBar(bar_ids=[0])]), track, staff)
