import io

from common.spectra.header import read_header
from common.spectra.provenance import citation, dataset_info, run_attributes, spectrum_provenance

from .mzml_factory import Spectrum, build_mzml

RECORD = {
    "id": "66txz-r6232",
    "pids": {},
    "links": {
        "self_html": "https://repo.example.org/dataset/records/66txz-r6232",
        "files": "https://repo.example.org/api/dataset/66txz-r6232/files",
    },
    "metadata": {
        "title": "Expression of kava SPS1, SPS2, and CHS in Arabidopsis thaliana",
        "publication_date": "2018-12-21",
        "creators": [{"person_or_org": {"name": "Weng, Jing-Ke"}}],
        "contributors": [
            {"person_or_org": {"name": "Pluskal, Tomáš"}, "role": {"id": "DataCollector"}},
            {"person_or_org": {"name": "Doe, Jane"}, "role": {"id": "Editor"}},
        ],
        "plant_biology": {"species": {"id": "NCBITaxon:3702", "title": {"en": "Arabidopsis thaliana (thale cress)"}}},
        "rights": [{"id": "cc-by-4.0", "title": {"en": "Creative Commons Attribution 4.0"}, "link": "https://x"}],
    },
}


def test_dataset_info():
    info = dataset_info(RECORD, "MSV000083272", "Chemical Biology Repository")
    assert info == {
        "id": "66txz-r6232",
        "accession": "MSV000083272",
        "doi": None,
        "url": "https://repo.example.org/dataset/records/66txz-r6232",
        "title": "Expression of kava SPS1, SPS2, and CHS in Arabidopsis thaliana",
        "creators": ["Weng, Jing-Ke"],
        "data_collectors": ["Pluskal, Tomáš"],
        "publication_date": "2018-12-21",
        "organism": "Arabidopsis thaliana (thale cress)",
        "licenses": [{"id": "cc-by-4.0", "title": "Creative Commons Attribution 4.0", "link": "https://x"}],
        "files_url": "https://repo.example.org/api/dataset/66txz-r6232/files",
        "citation": "Weng, Jing-Ke (2018). Expression of kava SPS1, SPS2, and CHS in Arabidopsis thaliana "
        "[Data set]. Chemical Biology Repository. MSV000083272. "
        "https://repo.example.org/dataset/records/66txz-r6232",
    }


def test_citation_prefers_doi():
    info = {"creators": ["A, B", "C, D"], "publication_date": "2020", "title": "T", "doi": "10.1/x", "url": "u"}
    assert citation(info) == "A, B; C, D (2020). T [Data set]. https://doi.org/10.1/x"


def test_spectrum_provenance():
    header = read_header(io.BytesIO(build_mzml([Spectrum("scan=1", [1.0], [1.0])], file_header=True).content))
    info = dataset_info(RECORD, "MSV000083272")
    provenance = spectrum_provenance(info, "peak/run 1.mzML", "md5:abc", False, header)
    assert "files_url" not in provenance["dataset"]
    assert provenance["file"] == {
        "key": "peak/run 1.mzML",
        "url": "https://repo.example.org/api/dataset/66txz-r6232/files/peak/run%201.mzML/content",
        "checksum": "md5:abc",
        "converted": False,
    }
    assert provenance["run"]["id"] == "test_run"
    assert provenance["run"]["start_time"] == "2017-07-31T16:10:13Z"
    assert provenance["run"]["source_files"] == [
        {"name": "test_run.raw", "checksum": "sha1:d0bfe48c1e71d17020a60bdff9c931658d2c9065"}
    ]
    assert provenance["run"]["data_processing"][0]["id"] == "pwiz_conversion"


def test_without_header():
    provenance = spectrum_provenance(dataset_info(RECORD, None), "a.mzML", None, True, None)
    assert provenance["run"] == {"id": None, "start_time": None, "source_files": [], "data_processing": []}
    assert run_attributes(None) == []
