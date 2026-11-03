"""Spectrum access on top of the dataset record and file services.

Permissions are those of the record files: every access goes through
``files_service.get_file_content``, so embargo, restricted access and share
links apply as for downloading the file.
"""

from __future__ import annotations

from typing import Any

import s3fs
from flask import current_app
from invenio_cache import current_cache
from invenio_files_rest.models import FileInstance
from invenio_records_resources.services.errors import FileKeyNotFoundError
from invenio_search import current_search_client
from invenio_search.engine import dsl
from invenio_search.utils import build_alias_name

from .models import RunStatus, SpectraRun, SpectrumIndexEntry
from .reader import parse_spectrum, spectrum_xml
from .tasks import run_file
from .usi import USI, build_usi, is_accession, native_id_value, parse_usi

DATASET_MODEL = "dataset"

# Record identifier schemes holding the dataset's USI collection accession.
ACCESSION_SCHEMES = ("proteomexchange", "massive")

MAX_PAGE_SIZE = 1000


class SpectrumNotFound(LookupError):
    """The record, file or spectrum does not exist."""


class RunNotIndexed(Exception):
    """The file is not indexed (yet); ``status`` tells why."""

    def __init__(self, run: SpectraRun):
        super().__init__(f"Run {run.ms_run} is not indexed ({run.status.name})")
        self.status = run.status
        self.error = run.error


def records_service():
    return current_app.extensions[DATASET_MODEL].records_service


def files_service():
    return current_app.extensions[DATASET_MODEL].files_service


def collection_of(record_id: str) -> str:
    """Return the USI collection of a published record: its PXD/MSV accession, else its id.

    The record is loaded without the service (no serialization, which is
    most of the cost of a service read); callers check the permissions.
    """
    record = records_service().record_cls.pid.resolve(record_id)
    for identifier in record.get("metadata", {}).get("identifiers", []):
        if identifier.get("scheme") in ACCESSION_SCHEMES and is_accession(identifier.get("identifier", "")):
            return identifier["identifier"]
    return record_id


def resolve_collection(collection: str) -> str:
    """Return the record id for a USI collection (accession or record id)."""
    if not is_accession(collection):
        return collection
    # A plain search, without the record service which serializes the hits;
    # access to the record files is checked afterwards. New versions of a
    # dataset keep its accession, so the latest version is taken.
    search = (
        dsl.Search(
            using=current_search_client, index=build_alias_name(records_service().record_cls.index.search_alias)
        )
        .filter("term", **{"metadata.identifiers.identifier": collection})
        .filter("terms", **{"metadata.identifiers.scheme": list(ACCESSION_SCHEMES)})
        .sort({"versions.is_latest": "desc"}, {"versions.index": "desc"})
        .source(["id"])[:1]
    )
    hits = search.execute().hits
    if not hits:
        raise SpectrumNotFound(f"No dataset with accession {collection}")
    return hits[0].id


def _file(identity, record_id: str, file_key: str):
    """Return the file result, checking the read permission on record files."""
    try:
        return files_service().get_file_content(identity, record_id, file_key)
    except FileKeyNotFoundError as e:
        raise SpectrumNotFound(str(e)) from e


def _run(record_id: str, *, file_key: str | None = None, ms_run: str | None = None) -> SpectraRun:
    query = SpectraRun.query.filter_by(record_pid=record_id)
    query = query.filter_by(file_key=file_key) if file_key else query.filter_by(ms_run=ms_run)
    run = query.one_or_none()
    if run is None:
        raise SpectrumNotFound(f"File {file_key or ms_run} of record {record_id} has no indexed spectra (not an mzML or raw file)")
    return run


def _check_indexed(run: SpectraRun) -> None:
    if run.status != RunStatus.INDEXED:
        raise RunNotIndexed(run)


def _entry(run: SpectraRun, index_type: str, value: str) -> SpectrumIndexEntry:
    query = SpectrumIndexEntry.query.filter_by(run_id=run.id)
    if index_type == "scan" and value.isdigit():
        query = query.filter_by(scan=int(value))
    elif index_type == "index" and value.isdigit():
        query = query.filter_by(position=int(value))
    elif index_type == "nativeId":
        query = query.filter(SpectrumIndexEntry.native_id.in_(_native_id_candidates(run, value)))
    else:
        raise SpectrumNotFound(f"Invalid {index_type} value {value!r}")
    entry = query.first()
    if entry is None:
        raise SpectrumNotFound(f"Spectrum {index_type}:{value} not found in {run.ms_run}")
    return entry


def _native_id_candidates(run: SpectraRun, value: str) -> list[str]:
    """nativeId USI values hold only the nativeID values ("1,1,2,1"); also accept the full nativeID."""
    if "=" in value:
        return [value]
    sample = SpectrumIndexEntry.query.filter_by(run_id=run.id).first()
    if sample is None:
        return []
    # rebuild "key1=v1 key2=v2 ..." with the keys of this file's nativeID format
    keys = [pair.split("=", 1)[0] for pair in sample.native_id.split()]
    values = value.split(",")
    if len(keys) != len(values):
        return []
    return [" ".join(f"{k}={v}" for k, v in zip(keys, values, strict=True))]


def entry_usi(collection: str, run: SpectraRun, entry: SpectrumIndexEntry) -> str:
    """Return the USI of an indexed spectrum, preferring the scan number."""
    if entry.scan is not None:
        return build_usi(collection, run.ms_run, "scan", entry.scan)
    if entry.native_id.startswith("index="):
        return build_usi(collection, run.ms_run, "index", entry.position)
    return build_usi(collection, run.ms_run, "nativeId", native_id_value(entry.native_id))


def get_spectrum(
    identity,
    record_id: str,
    index_type: str,
    value: str,
    *,
    file_key: str | None = None,
    ms_run: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the USI and the parsed spectrum."""
    run = _run(record_id, file_key=file_key, ms_run=ms_run)
    # permission check on the uploaded file, also for runs converted from raw
    _file(identity, record_id, run.file_key)
    _check_indexed(run)
    entry = _entry(run, index_type, value)

    # Published files never change, so a parsed spectrum can be cached.
    # The permission check above is done on every request.
    cache_key = f"spectra:{run.id}:{entry.position}"
    spectrum = current_cache.get(cache_key)
    if spectrum is None:
        chunk = read_range(run_file(run), entry.offset, entry.length)
        spectrum = parse_spectrum(spectrum_xml(chunk, entry.offset))
        current_cache.set(cache_key, spectrum, timeout=current_app.config.get("SPECTRA_CACHE_TIMEOUT", 86400))
    return entry_usi(collection_of(record_id), run, entry), spectrum


def read_range(file: FileInstance, offset: int, length: int) -> bytes:
    """Read ``length`` bytes at ``offset`` of a file.

    On S3 this is a single ranged GET; reading from the file stream would
    fetch a whole S3_DEFAULT_BLOCK_SIZE block (5 MB) for every spectrum.
    """
    storage = file.storage()
    fs, path = storage._get_fs()
    if isinstance(fs, s3fs.S3FileSystem):
        return fs.cat_file(path, start=offset, end=offset + length)
    stream = storage.open()
    try:
        stream.seek(offset)
        return stream.read(length)
    finally:
        stream.close()


def get_spectrum_by_usi(identity, usi_value: str) -> tuple[USI, dict[str, Any]]:
    """Return the parsed USI and the spectrum it identifies."""
    usi = parse_usi(usi_value)
    record_id = resolve_collection(usi.collection)
    _, spectrum = get_spectrum(identity, record_id, usi.index_type, usi.index, ms_run=usi.ms_run)
    return usi, spectrum


def list_spectra(
    identity, record_id: str, file_key: str, *, ms_level: int | None = None, page: int = 1, size: int = 100
) -> dict[str, Any]:
    """Return a page of spectrum summaries of an indexed file."""
    run = _run(record_id, file_key=file_key)
    _file(identity, record_id, file_key)
    _check_indexed(run)

    query = SpectrumIndexEntry.query.filter_by(run_id=run.id)
    if ms_level is not None:
        query = query.filter_by(ms_level=ms_level)
    size = max(1, min(size, MAX_PAGE_SIZE))
    total = query.count()
    entries = query.order_by(SpectrumIndexEntry.position).offset((max(page, 1) - 1) * size).limit(size)

    collection = collection_of(record_id)
    return {
        "ms_run": run.ms_run,
        "total": total,
        "page": page,
        "size": size,
        "hits": [
            {
                "usi": entry_usi(collection, run, entry),
                "index": entry.position,
                "native_id": entry.native_id,
                "scan": entry.scan,
                "ms_level": entry.ms_level,
                "rt": entry.rt,
                "precursor_mz": entry.precursor_mz,
                "charge": entry.charge,
            }
            for entry in entries
        ],
    }
