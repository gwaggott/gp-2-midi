"""ScoreReader: the interface every file-format reader implements."""

from pathlib import Path

from ..score import Score


class ScoreReader:
    """
    Reads one Guitar Pro file format into a Score. A concrete reader is a
    class combining mixins: for GPIF formats, a container mixin (sniff,
    load_xml; see containers.py) and GpifContentMixin (read; see
    gpif_xml.py). Readers hold no state, so the registry keeps one instance
    of each.
    """
    name: str = ''                      # e.g. 'GP7/8', for messages
    extensions: tuple[str, ...] = ()    # usual file suffixes, for messages

    @classmethod
    def sniff(cls, head: bytes) -> bool:
        """Whether a file starting with these bytes is in this format."""
        raise NotImplementedError

    def read(self, filepath: str | Path) -> Score:
        """The whole file, parsed into a Score."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f'<{type(self).__name__} {self.name}>'
