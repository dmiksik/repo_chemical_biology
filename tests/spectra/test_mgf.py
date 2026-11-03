import io

import pytest

from common.spectra.mgf import failure_comment, mgf, spectrum_mgf
from common.spectra.reader import parse_spectrum

from .mzml_factory import Spectrum, build_mzml

USI = "mzspec:MSV000083272:peak/20170731_WTcol:scan:3"

PROVENANCE = {
    "dataset": {
        "id": "66txz-r6232",
        "accession": "MSV000083272",
        "creators": ["Weng, Jing-Ke"],
        "data_collectors": ["Pluskal, Tomáš"],
        "organism": "Arabidopsis thaliana",
        "licenses": [{"id": "cc-by-4.0"}],
        "citation": "Weng, Jing-Ke (2018). Kava [Data set].\nMSV000083272.",
    },
    "file": {"key": "peak/20170731_WTcol.mzML"},
}


def _spectrum(**kwargs):
    defaults = {"native_id": "scan=3", "mzs": [100.5, 200.25], "intensities": [10.0, 20.0]}
    mzml = build_mzml([Spectrum(**{**defaults, **kwargs})])
    xml = mzml.content[mzml.offsets["scan=3"] :]
    spectrum = parse_spectrum(xml[: xml.find(b"</spectrum>") + len(b"</spectrum>")])
    spectrum["attributes"] += [
        {"accession": "MS:1000130", "name": "positive scan"},
        {"accession": "MS:1000045", "name": "collision energy", "value": "30"},
    ]
    return spectrum


def test_spectrum_mgf():
    block = spectrum_mgf(USI, _spectrum(), PROVENANCE, instrument="Q Exactive", scan=3)
    assert block == (
        "BEGIN IONS\n"
        f"TITLE={USI}\n"
        f"USI={USI}\n"
        "PEPMASS=445.12\n"
        "CHARGE=2+\n"
        "MSLEVEL=2\n"
        "RTINSECONDS=90.0000\n"
        "SCANS=3\n"
        "IONMODE=positive\n"
        "COLLISION_ENERGY=30\n"
        "SOURCE_INSTRUMENT=Q Exactive\n"
        "FILENAME=peak/20170731_WTcol.mzML\n"
        "DATASET=MSV000083272\n"
        "ORGANISM=Arabidopsis thaliana\n"
        "PI=Weng, Jing-Ke\n"
        "DATACOLLECTOR=Pluskal, Tomáš\n"
        "LICENSE=cc-by-4.0\n"
        "CITATION=Weng, Jing-Ke (2018). Kava [Data set]. MSV000083272.\n"
        "100.5 10.0\n"
        "200.25 20.0\n"
        "END IONS\n"
    )


def test_ms1_spectrum_without_precursor():
    block = spectrum_mgf(USI, _spectrum(ms_level=1, precursor_mz=None, charge=None))
    assert "PEPMASS" not in block
    assert "CHARGE" not in block
    assert "MSLEVEL=1\n" in block


def test_negative_charge():
    spectrum = _spectrum()
    spectrum["attributes"] = [{"accession": "MS:1000129", "name": "negative scan"}]
    assert "CHARGE=2-\n" in spectrum_mgf(USI, spectrum)


def test_readable_by_pyteomics():
    pyteomics_mgf = pytest.importorskip("pyteomics.mgf")
    text = "".join(
        mgf(
            [
                failure_comment("mzspec:MSV000000001:x:scan:1", 404, "Spectrum scan:1 not found"),
                spectrum_mgf(USI, _spectrum(), PROVENANCE, instrument="Q Exactive", scan=3),
                spectrum_mgf(USI.replace(":3", ":4"), _spectrum(), PROVENANCE),
            ]
        )
    )
    spectra = list(pyteomics_mgf.read(io.StringIO(text), use_index=False))
    assert len(spectra) == 2
    params = spectra[0]["params"]
    assert params["title"] == USI
    assert params["pepmass"][0] == 445.12
    assert params["charge"] == [2]
    assert params["organism"] == "Arabidopsis thaliana"
    assert list(spectra[0]["m/z array"]) == [100.5, 200.25]
