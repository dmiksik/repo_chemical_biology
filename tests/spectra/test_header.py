import io

import pytest

from common.spectra.header import attributes, instrument_model, parse_header, read_header
from common.spectra.reader import SpectrumReadError

from .mzml_factory import Spectrum, build_mzml


def _file(**kwargs):
    return build_mzml([Spectrum("scan=1", [100.0], [1.0])], **kwargs).content


def test_read_header():
    header = read_header(io.BytesIO(_file(file_header=True)))
    assert header["run"] == {"id": "test_run", "start_time": "2017-07-31T16:10:13Z", "instrument": "IC1"}
    assert header["source_files"] == [
        {
            "id": "RAW1",
            "name": "test_run.raw",
            "params": [
                {"accession": "MS:1000768", "name": "Thermo nativeID format"},
                {"accession": "MS:1000569", "name": "SHA-1", "value": "d0bfe48c1e71d17020a60bdff9c931658d2c9065"},
            ],
        }
    ]
    ic1 = header["instruments"][1]
    # the referenced param group is resolved
    assert ic1["params"][0] == {"accession": "MS:1001911", "name": "Q Exactive"}
    assert [c["type"] for c in ic1["components"]] == ["source", "analyzer"]
    assert [(s["id"], s["version"]) for s in header["software"]] == [("Xcalibur", "2.8"), ("pwiz", "3.0.18353")]
    assert header["data_processing"][0]["methods"][0]["software"] == "pwiz"


def test_header_read_in_chunks(monkeypatch):
    monkeypatch.setattr("common.spectra.header.CHUNK_SIZE", 100)
    assert read_header(io.BytesIO(_file(file_header=True)))["run"]["id"] == "test_run"


def test_instrument_model_of_default_configuration():
    header = read_header(io.BytesIO(_file(file_header=True)))
    # IC0 comes first, but the run uses IC1
    assert instrument_model(header) == {"accession": "MS:1001911", "name": "Q Exactive"}


def test_attributes():
    header = read_header(io.BytesIO(_file(file_header=True)))
    assert attributes(header) == [
        {"accession": "MS:1001911", "name": "Q Exactive"},
        {"accession": "MS:1000073", "name": "electrospray ionization"},
        {"accession": "MS:1000484", "name": "orbitrap"},
        {"accession": "MS:1000532", "name": "Xcalibur", "value": "2.8"},
        {"accession": "MS:1000615", "name": "ProteoWizard software", "value": "3.0.18353"},
    ]


def test_minimal_header():
    header = read_header(io.BytesIO(_file()))
    assert header == {
        "run": {"id": "test_run", "start_time": "2017-07-31T16:10:13Z", "instrument": "IC1"},
        "source_files": [],
        "instruments": [],
        "software": [],
        "data_processing": [],
    }
    assert instrument_model(header) is None
    assert attributes(header) == []


def test_not_mzml():
    with pytest.raises(SpectrumReadError):
        read_header(io.BytesIO(b"<?xml version='1.0'?><foo/>"))
    with pytest.raises(SpectrumReadError):
        parse_header(b"<foo/>")
