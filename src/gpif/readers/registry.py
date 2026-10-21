"""Pick a reader for a file by its first bytes, and the load_* entry points."""

import xml.etree.ElementTree as ET
from pathlib import Path

from ..score import Score
from .base import ScoreReader
from .gp345 import Gp3Reader, Gp4Reader, Gp5Reader
from .gpif_xml import Gp6Reader, Gp7Reader, GpifContentMixin, GpifXmlReader

# Bytes read from the start of a file for ScoreReader.sniff
HEAD_BYTES = 64

# One instance of each reader, in the order their sniff is tried: the
# catch-all raw XML reader last
READERS: list[ScoreReader] = [
    Gp7Reader(), Gp6Reader(), Gp5Reader(), Gp4Reader(), Gp3Reader(), GpifXmlReader(),
]


def reader_for(filepath: str | Path) -> ScoreReader:
    """The reader for a file, detected from its content, not its suffix."""
    with open(filepath, 'rb') as f:
        head = f.read(HEAD_BYTES)
    for reader in READERS:
        if reader.sniff(head):
            return reader
    raise ValueError(f"{filepath}: not a Guitar Pro file this library can read")


def load_score(filepath: str | Path) -> Score:
    """Load a Guitar Pro file, in any format a reader handles, into a Score."""
    return reader_for(filepath).read(filepath)


def load_gpif_xml(filepath: str | Path) -> ET.Element:
    """
    Load the GPIF XML root from a Guitar Pro 6/7/8 file, detected by content:
      - ZIP ('PK')  → GP7/GP8 .gp/.gpx, score at Content/score.gpif or score.gpif
      - 'BCFZ'      → GP6 .gpx, compressed BCFS container holding score.gpif
      - 'BCFS'      → GP6 .gpx, uncompressed container
      - otherwise   → raw .gpif/.xml
    """
    reader = reader_for(filepath)
    if not isinstance(reader, GpifContentMixin):
        raise ValueError(f"{filepath}: a {reader.name} file has no GPIF XML")
    return reader.load_xml(filepath)
