"""Dataset records as PROXI Dataset objects.

PROXI schema: https://github.com/HUPO-PSI/proxi-schemas (specs/swagger.yaml).
Terms are from the PSI-MS controlled vocabulary. The record id and its web
page have no PSI-MS term; they use the accession ``local``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .usi import is_raw

ACCESSION_TERMS = {
    "proteomexchange": ("MS:1001919", "ProteomeXchange accession number"),
    "massive": ("MS:1002487", "MassIVE dataset identifier"),
    "doi": ("MS:1001922", "Digital Object Identifier (DOI)"),
}
LOCAL = "local"


def _term(accession: str, name: str, value: Any = None) -> dict[str, Any]:
    term = {"accession": accession, "name": name}
    if value is not None:
        term["value"] = str(value)
    return term


def _title(value: dict | str | None) -> str | None:
    if isinstance(value, dict):
        return value.get("en") or next(iter(value.values()), None)
    return value


def _identifiers(record: dict) -> list[dict]:
    identifiers = [_term(LOCAL, "repository record identifier", record["id"])]
    for identifier in record.get("metadata", {}).get("identifiers", []):
        if identifier.get("scheme") in ACCESSION_TERMS:
            identifiers.append(_term(*ACCESSION_TERMS[identifier["scheme"]], identifier["identifier"]))
    doi = record.get("pids", {}).get("doi", {}).get("identifier")
    if doi:
        identifiers.append(_term(*ACCESSION_TERMS["doi"], doi))
    return identifiers


def _species(metadata: dict) -> list[dict]:
    species = []
    for section in ("microbiology", "plant_biology"):
        value = (metadata.get(section) or {}).get("species")
        if not value:
            continue
        terms = []
        name = _title(value.get("title"))
        if name:
            terms.append(_term("MS:1001469", "taxonomy: scientific name", name))
        if str(value.get("id", "")).startswith("NCBITaxon:"):
            terms.append(_term("MS:1001467", "taxonomy: NCBI TaxID", value["id"].split(":", 1)[1]))
        if terms:
            species.append({"terms": terms})
    return species


def _contacts(metadata: dict) -> list[dict]:
    contacts = []
    for index, creator in enumerate(metadata.get("creators", [])):
        person = creator.get("person_or_org", {})
        terms = [_term("MS:1000586", "contact name", person.get("name"))]
        for affiliation in creator.get("affiliations", []):
            terms.append(_term("MS:1000590", "contact affiliation", affiliation.get("name") or _title(affiliation.get("title"))))
        # the dataset model has one creator, the principal investigator
        if index == 0 and metadata.get("principal_investigator_email"):
            terms.append(_term("MS:1000589", "contact email", metadata["principal_investigator_email"]))
        contacts.append({"terms": terms})
    return contacts


def to_proxi_dataset(record: dict, result_type: str = "compact") -> dict[str, Any]:
    """Return the PROXI Dataset of a dataset record (as returned by the record service)."""
    metadata = record.get("metadata", {})
    dataset = {
        "identifiers": _identifiers(record),
        "title": metadata.get("title"),
        "species": _species(metadata),
        "instruments": [],
        "contacts": _contacts(metadata),
        "publications": [],
    }
    if result_type == "compact":
        return dataset

    if metadata.get("description"):
        dataset["description"] = metadata["description"]
    dataset["modifications"] = [
        _term(m["id"], _title(m.get("title")) or m["id"]) if m.get("id") else _term(LOCAL, _title(m.get("title")))
        for m in metadata.get("post_translational_modifications", [])
    ]
    dataset["keywords"] = [
        _term("MS:1001925", "submitter keyword", _title(s.get("subject")) or _title(s.get("title")) or s.get("id"))
        for s in metadata.get("subjects", [])
    ]
    links = record.get("links", {})
    if links.get("self_html"):
        dataset["fullDatasetLinks"] = [_term(LOCAL, "dataset web page", links["self_html"])]
    files = record.get("files", {}).get("entries", {})
    entries = files.values() if isinstance(files, dict) else files
    files_url = links.get("files", "")
    dataset["datasetFiles"] = [
        _term(
            *(("MS:1002846", "Associated raw file URI") if is_raw(f["key"]) else ("MS:1002845", "Associated file URI")),
            f"{files_url}/{quote(f['key'])}/content" if files_url else f["key"],
        )
        for f in entries
    ]
    return dataset
