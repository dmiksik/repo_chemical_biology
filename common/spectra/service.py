"""Spectrum access on top of the dataset record and file services.

Permissions are those of the record files: every access goes through
``files_service.get_file_content``, so embargo, restricted access and share
links apply as for downloading the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import s3fs
from flask import current_app
from invenio_access.permissions import system_identity
from invenio_cache import current_cache
from invenio_files_rest.models import FileInstance
from invenio_pidstore.errors import PIDDoesNotExistError, PIDUnregistered
from invenio_records_resources.services.errors import (
    FileKeyNotFoundError,
    PermissionDeniedError,
)
from invenio_search import current_search_client
from invenio_search.engine import dsl
from invenio_search.utils import build_alias_name
from sqlalchemy import or_

from .models import RunStatus, SpectraRun, SpectrumIndexEntry
from .provenance import dataset_info, run_attributes, spectrum_provenance
from .reader import SpectrumReadError, parse_spectrum, spectrum_xml, to_proxi
from .tasks import run_file
from .usi import (
    InvalidUSI,
    build_usi,
    is_accession,
    ms_run_name,
    native_id_value,
    normalize_ms_run,
    parse_usi,
)

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


# Errors of a single spectrum; in a batch they are reported per USI.
SPECTRUM_ERRORS = (
    InvalidUSI,
    PermissionDeniedError,
    SpectrumNotFound,
    PIDDoesNotExistError,
    PIDUnregistered,
    RunNotIndexed,
    SpectrumReadError,
)


def records_service():
    return current_app.extensions[DATASET_MODEL].records_service


def files_service():
    return current_app.extensions[DATASET_MODEL].files_service


def collection_of(record_id: str) -> str:
    """Return the USI collection of a published record: its PXD/MSV accession, else its id.

    The record is loaded without the service (no serialization, which is
    most of the cost of a service read); callers check the permissions.
    """
    return accession_of(records_service().record_cls.pid.resolve(record_id)) or record_id


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
    if file_key:
        run = query.filter_by(file_key=file_key).one_or_none()
    else:
        # msRun as a path, with or without an extension (MassIVE uses both), or only the
        # file name of a run stored under a path (peak/x.mzML -> x); most specific first
        name = normalize_ms_run(ms_run)
        names = [ms_run, ms_run_name(ms_run), name]
        runs = query.filter(or_(SpectraRun.ms_run.in_(names), SpectraRun.ms_run.endswith(f"/{name}"))).all()
        by_name = {r.ms_run: r for r in runs}
        run = next((by_name[n] for n in names if n in by_name), None)
        if run is None and len(runs) == 1:  # unambiguous file name
            run = runs[0]
    if run is None:
        raise SpectrumNotFound(
            f"File {file_key or ms_run} of record {record_id} has no indexed spectra (not an mzML or raw file)"
        )
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


@dataclass
class SpectrumResult:
    """A located spectrum; ``spectrum`` is filled by ``SpectrumAccess.load``."""

    usi: str  # canonical USI (scan number preferred)
    record_id: str
    run: SpectraRun
    entry: SpectrumIndexEntry
    spectrum: dict[str, Any] | None = None
    error: Exception | None = None


@dataclass
class SpectrumFailure:
    """A requested USI that could not be read, with the reason."""

    usi: str
    error: Exception


class SpectrumAccess:
    """Spectrum lookups of one request for one identity.

    Lookups of records, runs, permissions and files are memoized: a batch of
    USIs usually comes from a few files.
    """

    def __init__(self, identity):
        self.identity = identity
        self._record_ids: dict[str, str] = {}
        self._records: dict[str, Any] = {}
        self._runs: dict[tuple, SpectraRun] = {}
        self._access: dict[tuple, Exception | None] = {}
        self._files: dict[Any, FileInstance] = {}
        self._datasets: dict[str, dict[str, Any]] = {}

    def record_id(self, collection: str) -> str:
        if collection not in self._record_ids:
            self._record_ids[collection] = resolve_collection(collection)
        return self._record_ids[collection]

    def record(self, record_id: str):
        """The record, resolved without the service (no serialization); permissions are checked separately."""
        if record_id not in self._records:
            self._records[record_id] = records_service().record_cls.pid.resolve(record_id)
        return self._records[record_id]

    def collection(self, record_id: str) -> str:
        return accession_of(self.record(record_id)) or record_id

    def run(self, record_id: str, *, file_key: str | None = None, ms_run: str | None = None) -> SpectraRun:
        key = (record_id, file_key, ms_run)
        if key not in self._runs:
            self._runs[key] = _run(record_id, file_key=file_key, ms_run=ms_run)
        return self._runs[key]

    def check_access(self, record_id: str, file_key: str) -> None:
        """Check the permission to read the file (for converted runs, the raw file)."""
        key = (record_id, file_key)
        if key not in self._access:
            try:
                _file(self.identity, record_id, file_key)
                self._access[key] = None
            except Exception as e:  # noqa: BLE001 - re-raised for every spectrum of the file
                self._access[key] = e
        if self._access[key] is not None:
            raise self._access[key]

    def file(self, run: SpectraRun) -> FileInstance:
        if run.id not in self._files:
            self._files[run.id] = run_file(run)
        return self._files[run.id]

    def locate(
        self, record_id: str, index_type: str, value: str, *, file_key: str | None = None, ms_run: str | None = None
    ) -> SpectrumResult:
        run = self.run(record_id, file_key=file_key, ms_run=ms_run)
        self.check_access(record_id, run.file_key)
        _check_indexed(run)
        entry = _entry(run, index_type, value)
        return SpectrumResult(entry_usi(self.collection(record_id), run, entry), record_id, run, entry)

    def load(self, results: list[SpectrumResult]) -> None:
        """Fill in the spectra: from the cache, else read from storage in one batch.

        Published files never change, so parsed spectra can be cached; the
        permission check is done for every request (``locate``).
        """
        if not results:
            return
        keys = [f"spectra:{r.run.id}:{r.entry.position}" for r in results]
        missing = []
        for result, key, spectrum in zip(results, keys, current_cache.get_many(*keys), strict=True):
            if spectrum is None:
                missing.append((result, key))
            else:
                result.spectrum = spectrum
        chunks = read_ranges([(self.file(r.run), r.entry.offset, r.entry.length) for r, _ in missing])
        to_cache = {}
        for (result, key), chunk in zip(missing, chunks, strict=True):
            try:
                result.spectrum = to_cache[key] = parse_spectrum(spectrum_xml(chunk, result.entry.offset))
            except SpectrumReadError as e:
                result.error = e
        if to_cache:
            current_cache.set_many(to_cache, timeout=current_app.config.get("SPECTRA_CACHE_TIMEOUT", 86400))

    def dataset(self, record_id: str) -> dict[str, Any]:
        """Citation metadata of the record, cached per record revision.

        Read with the system identity: callers have checked the access to a
        file of the record, which implies access to its metadata.
        """
        if record_id not in self._datasets:
            record = self.record(record_id)
            key = f"spectra:dataset:{record_id}:{record.revision_id}"
            info = current_cache.get(key)
            if info is None:
                serialized = records_service().read(system_identity, record_id).to_dict()
                info = dataset_info(
                    serialized, accession_of(record), current_app.config.get("THEME_SITENAME")
                )
                current_cache.set(key, info, timeout=current_app.config.get("SPECTRA_CACHE_TIMEOUT", 86400))
            self._datasets[record_id] = info
        return self._datasets[record_id]

    def provenance(self, result: SpectrumResult) -> dict[str, Any]:
        run = result.run
        return spectrum_provenance(
            self.dataset(result.record_id), run.file_key, run.checksum, bool(run.converted_file_id), run.header
        )

    def proxi(self, result: SpectrumResult, result_type: str, usi: str | None = None) -> dict[str, Any]:
        """PROXI Spectrum; ``full`` adds instrument and software terms and the provenance."""
        spectrum = to_proxi(usi or result.usi, result.spectrum, result_type)
        if result_type == "full":
            spectrum["attributes"] = spectrum["attributes"] + run_attributes(result.run.header)
            spectrum["provenance"] = self.provenance(result)
        return spectrum


def accession_of(record) -> str | None:
    """Return the PXD/MSV accession of a record (its USI collection), if it has one."""
    for identifier in record.get("metadata", {}).get("identifiers", []):
        if identifier.get("scheme") in ACCESSION_SCHEMES and is_accession(identifier.get("identifier", "")):
            return identifier["identifier"]
    return None


def get_spectrum(
    access: SpectrumAccess,
    record_id: str,
    index_type: str,
    value: str,
    *,
    file_key: str | None = None,
    ms_run: str | None = None,
) -> SpectrumResult:
    """Return one spectrum of a record file."""
    result = access.locate(record_id, index_type, value, file_key=file_key, ms_run=ms_run)
    access.load([result])
    if result.error:
        raise result.error
    return result


def get_spectrum_by_usi(access: SpectrumAccess, usi_value: str) -> SpectrumResult:
    """Return the spectrum a USI identifies."""
    usi = parse_usi(usi_value)
    return get_spectrum(access, access.record_id(usi.collection), usi.index_type, usi.index, ms_run=usi.ms_run)


def get_spectra(access: SpectrumAccess, usi_values: list[str]) -> list[SpectrumResult | SpectrumFailure]:
    """Return the spectra of a list of USIs, in order; unreadable ones as SpectrumFailure."""
    results: list[SpectrumResult | SpectrumFailure] = []
    for value in usi_values:
        try:
            usi = parse_usi(value)
            results.append(
                access.locate(access.record_id(usi.collection), usi.index_type, usi.index, ms_run=usi.ms_run)
            )
        except SPECTRUM_ERRORS as e:
            results.append(SpectrumFailure(value, e))
    access.load([r for r in results if isinstance(r, SpectrumResult)])
    return [SpectrumFailure(r.usi, r.error) if isinstance(r, SpectrumResult) and r.error else r for r in results]


def read_ranges(ranges: list[tuple[FileInstance, int, int]]) -> list[bytes]:
    """Read byte ranges (file, offset, length) of files.

    On S3 the ranged GETs run concurrently (``cat_ranges``); reading from the
    file stream would fetch a whole S3_DEFAULT_BLOCK_SIZE block (5 MB) for
    every spectrum.
    """
    chunks: list[bytes | None] = [None] * len(ranges)
    s3_reads: dict[int, tuple[Any, list[int], list[str]]] = {}
    for i, (file, offset, length) in enumerate(ranges):
        storage = file.storage()
        fs, path = storage._get_fs()
        if isinstance(fs, s3fs.S3FileSystem):
            s3_reads.setdefault(id(fs), (fs, [], []))
            s3_reads[id(fs)][1].append(i)
            s3_reads[id(fs)][2].append(path)
        else:
            stream = storage.open()
            try:
                stream.seek(offset)
                chunks[i] = stream.read(length)
            finally:
                stream.close()
    for fs, indexes, paths in s3_reads.values():
        starts = [ranges[i][1] for i in indexes]
        ends = [ranges[i][1] + ranges[i][2] for i in indexes]
        for i, chunk in zip(indexes, fs.cat_ranges(paths, starts, ends), strict=True):
            chunks[i] = chunk
    return chunks


def read_range(file: FileInstance, offset: int, length: int) -> bytes:
    """Read ``length`` bytes at ``offset`` of a file."""
    return read_ranges([(file, offset, length)])[0]


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
