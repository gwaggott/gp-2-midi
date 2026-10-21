"""
One reader class per file format (see base.ScoreReader), built from mixins,
and the registry that picks one by a file's first bytes.

  base        ScoreReader
  containers  container mixins: ZIP, GP6 BCFZ/BCFS, raw XML
  mixins      mixins shared by the content mixins of all formats: track
              classification, rhythm, pitch effects, dynamics; ScoreBuilder
  gpif_xml    GpifContentMixin (GPIF XML → Score; its parse_* methods are
              also module functions) and the GPIF readers: Gp7Reader,
              Gp6Reader, GpifXmlReader
  gp345       PyGuitarProMixin (guitarpro.Song → Score) and the GP3-5
              readers: Gp3Reader, Gp4Reader, Gp5Reader
  registry    READERS, reader_for, load_score, load_gpif_xml
"""

from .base import ScoreReader
from .containers import BcfsContainerMixin, RawXmlContainerMixin, ZipContainerMixin
from .gp345 import Gp3Reader, Gp4Reader, Gp5Reader, PyGuitarProMixin
from .gpif_xml import Gp6Reader, Gp7Reader, GpifContentMixin, GpifXmlReader
from .mixins import (
    DynamicsMixin,
    PitchEffectsMixin,
    RhythmMixin,
    ScoreBuilder,
    TrackClassificationMixin,
)
from .registry import READERS, load_gpif_xml, load_score, reader_for

__all__ = [
    'ScoreReader',
    'BcfsContainerMixin', 'RawXmlContainerMixin', 'ZipContainerMixin',
    'DynamicsMixin', 'PitchEffectsMixin', 'RhythmMixin', 'ScoreBuilder', 'TrackClassificationMixin',
    'Gp3Reader', 'Gp4Reader', 'Gp5Reader', 'PyGuitarProMixin',
    'Gp6Reader', 'Gp7Reader', 'GpifContentMixin', 'GpifXmlReader',
    'READERS', 'load_gpif_xml', 'load_score', 'reader_for',
]
