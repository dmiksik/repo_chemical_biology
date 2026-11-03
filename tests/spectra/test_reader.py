import io

import pytest

from common.spectra.mzml_index import read_index
from common.spectra.reader import SpectrumReadError, parse_spectrum, read_spectrum_xml, to_proxi

from .mzml_factory import Spectrum, build_mzml, thermo_id


@pytest.mark.parametrize("zlib_compressed", [True, False])
@pytest.mark.parametrize("float64", [True, False])
def test_read_spectrum(zlib_compressed, float64):
    spectra = [
        Spectrum(thermo_id(1), [100.5, 200.25], [1.0, 2.0], ms_level=1, precursor_mz=None),
        Spectrum(thermo_id(2), [150.5, 250.75, 300.0], [3.0, 4.0, 5.0], rt=2.25),
    ]
    mzml = build_mzml(spectra, zlib_compressed=zlib_compressed, float64=float64)
    fp = io.BytesIO(mzml.content)
    entry = read_index(fp, len(mzml.content))[1]

    spectrum = parse_spectrum(read_spectrum_xml(fp, entry.offset, entry.length))

    assert spectrum["native_id"] == thermo_id(2)
    assert spectrum["index"] == 1
    assert spectrum["mzs"] == [150.5, 250.75, 300.0]
    assert spectrum["intensities"] == [3.0, 4.0, 5.0]
    values = {a["accession"]: a.get("value") for a in spectrum["attributes"]}
    assert values["MS:1000511"] == "2"
    assert values["MS:1000016"] == "2.25"
    assert values["MS:1000744"] == "445.12"
    assert values["MS:1000041"] == "2"
    # scan start time is in minutes in the factory
    assert spectrum["summary"] == {"ms_level": 2, "rt": 135.0, "precursor_mz": 445.12, "charge": 2}


def test_parse_spectrum_without_arrays():
    mzml = build_mzml([Spectrum(thermo_id(1), [100.5], [1.0], ms_level=1, precursor_mz=None)])
    fp = io.BytesIO(mzml.content)
    entry = read_index(fp, len(mzml.content))[0]
    spectrum = parse_spectrum(read_spectrum_xml(fp, entry.offset, entry.length), decode_arrays=False)
    assert spectrum["mzs"] == []
    assert spectrum["summary"] == {"ms_level": 1, "rt": 90.0, "precursor_mz": None, "charge": None}


def test_read_spectrum_wrong_offset():
    mzml = build_mzml([Spectrum(thermo_id(1), [1.0], [1.0])])
    with pytest.raises(SpectrumReadError):
        read_spectrum_xml(io.BytesIO(mzml.content), 3, 100)


def test_unsupported_compression():
    xml = b"""<spectrum index="0" id="scan=1" defaultArrayLength="1"><binaryDataArrayList count="1">
    <binaryDataArray><cvParam accession="MS:1000523" name="64-bit float"/>
    <cvParam accession="MS:1002312" name="MS-Numpress linear prediction compression"/>
    <cvParam accession="MS:1000514" name="m/z array"/><binary>AAAA</binary></binaryDataArray>
    </binaryDataArrayList></spectrum>"""
    with pytest.raises(SpectrumReadError):
        parse_spectrum(xml)


def test_to_proxi():
    spectrum = {"attributes": [{"accession": "MS:1000511", "name": "ms level", "value": "2"}], "mzs": [1.0], "intensities": [2.0]}
    full = to_proxi("mzspec:PXD000001:run:scan:1", spectrum)
    assert full == {
        "usi": "mzspec:PXD000001:run:scan:1",
        "status": "READABLE",
        "mzs": [1.0],
        "intensities": [2.0],
        "attributes": spectrum["attributes"],
    }
    assert "attributes" not in to_proxi("mzspec:PXD000001:run:scan:1", spectrum, "compact")
