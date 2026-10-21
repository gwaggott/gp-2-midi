"""A whole parsed score, and lookups across its sections."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .model import Bar, Beat, MasterBar, Note, Rhythm, ScoreInfo, Tempo, Track, Voice


@dataclass(frozen=True)
class Score:
    """Every parsed section of a score, whatever file format it came from (see gpif.readers)."""
    tracks:      list[Track]
    master_bars: list[MasterBar]
    bars:        dict[int, Bar]
    voices:      dict[int, Voice]
    beats:       dict[int, Beat]
    notes:       dict[int, Note]
    rhythms:     dict[int, Rhythm]
    tempos:      list[Tempo]
    info:        ScoreInfo = field(default_factory=ScoreInfo)
    # The GPIF XML root, for anything the parse_* functions don't cover;
    # None for other formats and for a Score built by hand (e.g. in tests)
    root:        ET.Element | None = None
    # The object a non-GPIF reader parsed the file into, for anything not
    # converted (GP3-5: the guitarpro.Song); None for GPIF
    source:      object | None = field(default=None, compare=False, repr=False)


def track_bars(score: Score, track: Track, staff: int = 0) -> list[Bar | None]:
    """
    The bar for one staff of `track` in each master bar, in order (None
    where there is none). Staves are numbered as in track.staves.
    """
    if not 0 <= staff < len(track.staves):
        raise IndexError(f"track {track.id} has no staff {staff}")
    index = track.bar_index + staff
    return [score.bars.get(mb.bar_ids[index]) if index < len(mb.bar_ids) else None
            for mb in score.master_bars]
