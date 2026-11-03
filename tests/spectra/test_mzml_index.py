import io

import pytest

from common.spectra.mzml_index import NotIndexedMzML, read_index

from .mzml_factory import Spectrum, build_mzml, thermo_id


def _spectra(n):
    return [Spectrum(thermo_id(i + 1), [100.0 + i, 200.0], [10.0, 20.0]) for i in range(n)]


def test_read_index_offsets_and_lengths():
    mzml = build_mzml(_spectra(3))
    entries = read_index(io.BytesIO(mzml.content), len(mzml.content))

    assert [e.native_id for e in entries] == [thermo_id(1), thermo_id(2), thermo_id(3)]
    assert [e.position for e in entries] == [0, 1, 2]
    for entry in entries:
        assert entry.offset == mzml.offsets[entry.native_id]
        chunk = mzml.content[entry.offset : entry.offset + entry.length]
        assert chunk.startswith(b"<spectrum ")
        assert b"</spectrum>" in chunk
    # the last spectrum reaches to the chromatogram, not to the end of the file
    last = entries[-1]
    assert b"<chromatogram " in mzml.content[last.offset + last.length : last.offset + last.length + 20]


def test_read_index_large_index_list():
    # the index list is longer than the tail read from the end of the file
    mzml = build_mzml(_spectra(200))
    entries = read_index(io.BytesIO(mzml.content), len(mzml.content))
    assert len(entries) == 200


def test_not_indexed():
    content = b'<?xml version="1.0"?><mzML xmlns="http://psi.hupo.org/ms/mzml"></mzML>'
    with pytest.raises(NotIndexedMzML):
        read_index(io.BytesIO(content), len(content))


def test_index_list_offset_outside_file():
    # e.g. a truncated file
    content = b"<indexedmzML><indexListOffset>5098921</indexListOffset></indexedmzML>"
    with pytest.raises(NotIndexedMzML):
        read_index(io.BytesIO(content), len(content))
