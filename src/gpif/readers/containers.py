"""
Container mixins: how a reader gets the GPIF XML out of a file. Each
provides sniff(head) (does this file's first bytes look like my container?)
and load_xml(path) -> the XML root; a reader class combines one of them
with a content mixin (see gpif_xml.py).

  ZipContainerMixin     .gp (Guitar Pro 7/8): ZIP archive holding
                        Content/score.gpif (zip .gpx files too)
  BcfsContainerMixin    .gpx (Guitar Pro 6): BCFZ-compressed (or plain) BCFS
                        container holding score.gpif
  RawXmlContainerMixin  .gpif / .xml: the XML itself
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _bcfz_decompress(data: bytes) -> bytes:
    """
    Decompress a GP6 BCFZ stream (the bytes after the 'BCFZ' header).

    Layout: int32 LE uncompressed length, then a bit stream read MSB-first.
    Each chunk starts with a flag bit:
      1 → back-reference: 4-bit word size W, then W-bit offset and W-bit
          length (both LSB-first); copy min(offset, length) bytes from
          `offset` bytes back in the output.
      0 → literal: 2-bit count N (LSB-first), then N raw 8-bit bytes.
    """
    expected = int.from_bytes(data[0:4], 'little')
    # Pre-expand the stream to one int per bit; simpler and faster in Python
    # than shifting per read.
    bits = [(byte >> shift) & 1 for byte in data[4:] for shift in range(7, -1, -1)]
    n_bits = len(bits)
    pos = 0
    out = bytearray()

    def read_msb(count: int) -> int:
        nonlocal pos
        value = 0
        for _ in range(count):
            value = (value << 1) | (bits[pos] if pos < n_bits else 0)
            pos += 1
        return value

    def read_lsb(count: int) -> int:
        nonlocal pos
        value = 0
        for i in range(count):
            value |= (bits[pos] if pos < n_bits else 0) << i
            pos += 1
        return value

    while len(out) < expected and pos < n_bits:
        if read_msb(1):
            word_size = read_msb(4)
            offset = read_lsb(word_size)
            length = read_lsb(word_size)
            src = len(out) - offset
            if offset == 0 or src < 0:
                raise ValueError("Corrupt BCFZ stream: back-reference out of range")
            out += out[src:src + min(offset, length)]
        else:
            for _ in range(read_lsb(2)):
                out.append(read_msb(8))

    return bytes(out[:expected])


def _bcfs_files(data: bytes) -> dict[str, bytes]:
    """
    Extract files from a GP6 BCFS container (the bytes after the 'BCFS' header).

    The container is split into 0x1000-byte sectors. A sector starting with
    int32 2 is a file entry: name at +0x04 (127 bytes, NUL-padded), size at
    +0x8C, then a 0-terminated list of int32 sector indices holding the data.
    """
    sector_size = 0x1000

    def int_at(pos: int) -> int:
        return int.from_bytes(data[pos:pos + 4], 'little')

    files = {}
    for entry in range(0, len(data) - 3, sector_size):
        if int_at(entry) != 2:
            continue
        name = data[entry + 0x04:entry + 0x04 + 127].split(b'\0', 1)[0].decode('utf-8', 'replace')
        size = int_at(entry + 0x8C)
        content = bytearray()
        ptr = entry + 0x94
        while ptr + 4 <= len(data) and (sector := int_at(ptr)) != 0:
            content += data[sector * sector_size:(sector + 1) * sector_size]
            ptr += 4
        files[name] = bytes(content[:size])
    return files


class ZipContainerMixin:
    """ZIP archive ('PK'), score at Content/score.gpif or score.gpif."""

    @classmethod
    def sniff(cls, head: bytes) -> bool:
        return head[:2] == b'PK'

    def load_xml(self, filepath: str | Path) -> ET.Element:
        with zipfile.ZipFile(filepath, 'r') as zf:
            names = zf.namelist()
            gpif_name = next(
                (n for n in names if n.lower() in ('content/score.gpif', 'score.gpif')),
                None
            )
            if gpif_name is None:
                raise ValueError(
                    f"score.gpif not found in archive. Contents: {names}"
                )
            with zf.open(gpif_name) as f:
                return ET.parse(f).getroot()


class BcfsContainerMixin:
    """GP6 container: 'BCFZ' (compressed) or 'BCFS', holding score.gpif."""

    @classmethod
    def sniff(cls, head: bytes) -> bool:
        return head[:4] in (b'BCFZ', b'BCFS')

    def load_xml(self, filepath: str | Path) -> ET.Element:
        data = Path(filepath).read_bytes()
        magic, data = data[:4], data[4:]
        if magic == b'BCFZ':
            data = _bcfz_decompress(data)
            if data[:4] != b'BCFS':
                raise ValueError("BCFZ data did not decompress to a BCFS container")
            data = data[4:]
        files = _bcfs_files(data)
        gpif_name = next((n for n in files if n.lower() == 'score.gpif'), None)
        if gpif_name is None:
            raise ValueError(
                f"score.gpif not found in container. Contents: {list(files)}"
            )
        return ET.fromstring(files[gpif_name])


class RawXmlContainerMixin:
    """
    Raw GPIF XML. Its sniff accepts anything, so the registry tries it last:
    a file no other reader recognises is parsed as XML (and fails there if
    it isn't).
    """

    @classmethod
    def sniff(cls, head: bytes) -> bool:
        return True

    def load_xml(self, filepath: str | Path) -> ET.Element:
        return ET.parse(filepath).getroot()
