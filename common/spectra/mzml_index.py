"""Reading the byte offset index of indexed mzML files.

An indexed mzML file ends with::

    <indexList count="2">
      <index name="spectrum">
        <offset idRef="controllerType=0 controllerNumber=1 scan=1">4826</offset>
        ...
      </index>
      <index name="chromatogram">...</index>
    </indexList>
    <indexListOffset>123456</indexListOffset>
    <fileChecksum>...</fileChecksum>
    </indexedmzML>

Only the end of the file is read, so this works with range reads from S3.
This module has no Invenio dependencies.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import BinaryIO
from xml.sax.saxutils import unescape

# The tail after </indexList> is short (offset + SHA-1 checksum).
TAIL_SIZE = 4096

_INDEX_LIST_OFFSET_RE = re.compile(rb"<indexListOffset>\s*(\d+)\s*</indexListOffset>")
_INDEX_RE = re.compile(rb'<index\s+name="(\w+)"\s*>(.*?)</index>', re.S)
_OFFSET_RE = re.compile(rb'<offset\s+idRef="([^"]*)"[^>]*>\s*(\d+)\s*</offset>')


class NotIndexedMzML(ValueError):
    """The file is not an indexed mzML (no indexListOffset at its end)."""


@dataclass(frozen=True)
class IndexEntry:
    """Position of one spectrum in the file.

    ``length`` reaches to the next indexed element, so the bytes read may
    contain a trailing ``</spectrumList>`` and the start of the next element;
    the reader trims them at ``</spectrum>``.
    """

    position: int
    native_id: str
    offset: int
    length: int


def read_index(fp: BinaryIO, size: int) -> list[IndexEntry]:
    """Return the spectrum index of an indexed mzML file, in file order.

    :param fp: seekable binary file
    :param size: file size in bytes
    """
    tail_start = max(0, size - TAIL_SIZE)
    fp.seek(tail_start)
    tail = fp.read(size - tail_start)
    match = _INDEX_LIST_OFFSET_RE.search(tail)
    if not match:
        raise NotIndexedMzML("indexListOffset not found at the end of the file")

    index_list_offset = int(match.group(1))
    if not 0 < index_list_offset < size:
        raise NotIndexedMzML(f"indexListOffset {index_list_offset} is outside the file")
    fp.seek(index_list_offset)
    index_list = fp.read(size - index_list_offset)

    spectra: list[tuple[str, int]] = []
    # Offsets of all indexed elements, used to compute spectrum lengths.
    boundaries = [index_list_offset]
    for name, body in _INDEX_RE.findall(index_list):
        offsets = [(unescape(ref.decode()), int(off)) for ref, off in _OFFSET_RE.findall(body)]
        boundaries.extend(off for _, off in offsets)
        if name == b"spectrum":
            spectra = offsets

    boundaries.sort()
    entries = []
    for position, (native_id, offset) in enumerate(sorted(spectra, key=lambda s: s[1])):
        end = _next_boundary(boundaries, offset)
        entries.append(IndexEntry(position, native_id, offset, end - offset))
    return entries


def _next_boundary(boundaries: list[int], offset: int) -> int:
    """Return the smallest boundary greater than offset (boundaries are sorted)."""
    return boundaries[bisect_right(boundaries, offset)]
