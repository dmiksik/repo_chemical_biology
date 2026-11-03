from common.spectra.proxi import to_proxi_dataset

RECORD = {
    "id": "abcde-12345",
    "pids": {"doi": {"identifier": "10.1234/abcde-12345"}},
    "links": {
        "self_html": "https://repo.example.org/dataset/records/abcde-12345",
        "files": "https://repo.example.org/api/dataset/abcde-12345/files",
    },
    "metadata": {
        "title": "Test dataset",
        "description": "<p>Description</p>",
        "identifiers": [{"identifier": "MSV000096242", "scheme": "massive"}, {"identifier": "x", "scheme": "url"}],
        "principal_investigator_email": "pi@example.org",
        "creators": [
            {"person_or_org": {"name": "Doe, Jane"}, "affiliations": [{"name": "IOCB Prague"}]},
        ],
        "microbiology": {"species": {"id": "NCBITaxon:562", "title": {"en": "Escherichia coli"}}},
        "post_translational_modifications": [{"id": "UNIMOD:21", "title": {"en": "Phosphorylation (Phospho)"}}],
        "subjects": [{"subject": "metabolomics"}],
    },
    "files": {"entries": {"run 1.raw": {"key": "run 1.raw"}, "run2.mzML": {"key": "run2.mzML"}}},
}


def test_compact_dataset():
    dataset = to_proxi_dataset(RECORD)
    assert set(dataset) == {"identifiers", "title", "species", "instruments", "contacts", "publications"}
    assert dataset["identifiers"] == [
        {"accession": "local", "name": "repository record identifier", "value": "abcde-12345"},
        {"accession": "MS:1002487", "name": "MassIVE dataset identifier", "value": "MSV000096242"},
        {"accession": "MS:1001922", "name": "Digital Object Identifier (DOI)", "value": "10.1234/abcde-12345"},
    ]
    assert dataset["species"] == [
        {
            "terms": [
                {"accession": "MS:1001469", "name": "taxonomy: scientific name", "value": "Escherichia coli"},
                {"accession": "MS:1001467", "name": "taxonomy: NCBI TaxID", "value": "562"},
            ]
        }
    ]
    assert dataset["contacts"] == [
        {
            "terms": [
                {"accession": "MS:1000586", "name": "contact name", "value": "Doe, Jane"},
                {"accession": "MS:1000590", "name": "contact affiliation", "value": "IOCB Prague"},
                {"accession": "MS:1000589", "name": "contact email", "value": "pi@example.org"},
            ]
        }
    ]


def test_full_dataset():
    dataset = to_proxi_dataset(RECORD, "full")
    assert dataset["description"] == "<p>Description</p>"
    assert dataset["modifications"] == [{"accession": "UNIMOD:21", "name": "Phosphorylation (Phospho)"}]
    assert dataset["keywords"] == [{"accession": "MS:1001925", "name": "submitter keyword", "value": "metabolomics"}]
    assert dataset["datasetFiles"] == [
        {
            "accession": "MS:1002846",
            "name": "Associated raw file URI",
            "value": "https://repo.example.org/api/dataset/abcde-12345/files/run%201.raw/content",
        },
        {
            "accession": "MS:1002845",
            "name": "Associated file URI",
            "value": "https://repo.example.org/api/dataset/abcde-12345/files/run2.mzML/content",
        },
    ]
