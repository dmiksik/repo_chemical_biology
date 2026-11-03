"""Where a spectrum comes from: dataset, file, run and processing.

Sent with each spectrum (PROXI ``full`` result and MGF export), so that a
spectrum taken out of the repository stays citable and reusable. This module
has no Invenio dependencies; it works on serialized records.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .header import attributes as header_attributes

SHA1 = "MS:1000569"
DATA_COLLECTOR = "DataCollector"


def _title(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("en") or next(iter(value.values()), None)
    return value


def dataset_info(record: dict[str, Any], accession: str | None, publisher: str | None = None) -> dict[str, Any]:
    """Return the citation-relevant metadata of a dataset record (as returned by the record service)."""
    metadata = record.get("metadata", {})
    links = record.get("links", {})
    doi = (record.get("pids") or {}).get("doi", {}).get("identifier")
    creators = [c.get("person_or_org", {}).get("name") for c in metadata.get("creators", [])]
    collectors = [
        c.get("person_or_org", {}).get("name")
        for c in metadata.get("contributors", [])
        if (c.get("role") or {}).get("id") == DATA_COLLECTOR
    ]
    species = [
        _title((metadata.get(section) or {}).get("species", {}).get("title"))
        for section in ("plant_biology", "microbiology")
    ]
    info = {
        "id": record.get("id"),
        "accession": accession,
        "doi": doi,
        "url": links.get("self_html"),
        "title": metadata.get("title"),
        "creators": [c for c in creators if c],
        "data_collectors": [c for c in collectors if c],
        "publication_date": metadata.get("publication_date"),
        "organism": next((s for s in species if s), None),
        "licenses": [
            {k: v for k, v in {"id": r.get("id"), "title": _title(r.get("title")), "link": r.get("link")}.items() if v}
            for r in metadata.get("rights", [])
        ],
        "files_url": links.get("files"),
    }
    info["citation"] = citation(info, publisher)
    return info


def citation(info: dict[str, Any], publisher: str | None = None) -> str:
    """Return a data citation: Creators (year). Title [Data set]. Publisher. DOI or URL."""
    parts = []
    creators = "; ".join(info.get("creators") or [])
    year = (info.get("publication_date") or "")[:4]
    if creators or year:
        parts.append(f"{creators} ({year})." if year else f"{creators}.")
    if info.get("title"):
        parts.append(f"{info['title']} [Data set].")
    if publisher:
        parts.append(f"{publisher}.")
    if info.get("accession"):
        parts.append(f"{info['accession']}.")
    link = f"https://doi.org/{info['doi']}" if info.get("doi") else info.get("url")
    if link:
        parts.append(link)
    return " ".join(parts)


def spectrum_provenance(
    dataset: dict[str, Any], file_key: str, checksum: str | None, converted: bool, header: dict[str, Any] | None
) -> dict[str, Any]:
    """Return the provenance object of a spectrum."""
    header = header or {}
    files_url = dataset.get("files_url")
    run = header.get("run") or {}
    return {
        "dataset": {k: v for k, v in dataset.items() if k != "files_url"},
        "file": {
            "key": file_key,
            "url": f"{files_url}/{quote(file_key)}/content" if files_url else None,
            "checksum": checksum,
            # raw file converted to mzML by the repository
            "converted": converted,
        },
        "run": {
            "id": run.get("id"),
            "start_time": run.get("start_time"),
            "source_files": [
                {
                    "name": f.get("name"),
                    "checksum": next((f"sha1:{p['value']}" for p in f["params"] if p["accession"] == SHA1), None),
                }
                for f in header.get("source_files", [])
            ],
            "data_processing": header.get("data_processing", []),
        },
    }


def run_attributes(header: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return instrument and software terms of a run, to add to the spectrum attributes."""
    return header_attributes(header) if header else []
