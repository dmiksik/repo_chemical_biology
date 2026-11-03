"""Celery task indexing mzML files of published records."""

from __future__ import annotations

from celery import shared_task
from flask import current_app
from invenio_access.permissions import system_identity
from invenio_db import db

from .models import RunStatus, SpectraRun, SpectrumIndexEntry
from .mzml_index import NotIndexedMzML, read_index
from .reader import SpectrumReadError, parse_spectrum, read_spectrum_xml
from .usi import scan_number

BATCH_SIZE = 5000


@shared_task(ignore_result=True)
def index_run(run_id: str) -> None:
    """Build the spectrum index of one run (mzML file)."""
    from .service import files_service

    run = db.session.get(SpectraRun, run_id)
    if run is None or run.status == RunStatus.INDEXED:
        return

    try:
        file = files_service().get_file_content(system_identity, run.record_pid, run.file_key)
        stream = file.get_stream("rb")
        try:
            count = _index(run, stream, file.data["size"])
        finally:
            stream.close()
    except (NotIndexedMzML, SpectrumReadError) as e:
        db.session.rollback()
        _finish(run_id, RunStatus.UNSUPPORTED, error=str(e))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Indexing of spectra run %s failed", run_id)
        _finish(run_id, RunStatus.FAILED, error=str(e))
    else:
        _finish(run_id, RunStatus.INDEXED, spectra_count=count)


def _index(run: SpectraRun, stream, size: int) -> int:
    """Store index entries of all spectra; the file is read sequentially."""
    SpectrumIndexEntry.query.filter_by(run_id=run.id).delete()
    batch = []
    entries = read_index(stream, size)
    for entry in entries:
        summary = parse_spectrum(read_spectrum_xml(stream, entry.offset, entry.length), decode_arrays=False)[
            "summary"
        ]
        batch.append(
            {
                "run_id": run.id,
                "position": entry.position,
                "native_id": entry.native_id,
                "scan": scan_number(entry.native_id),
                "offset": entry.offset,
                "length": entry.length,
                **summary,
            }
        )
        if len(batch) >= BATCH_SIZE:
            db.session.execute(db.insert(SpectrumIndexEntry), batch)
            batch = []
    if batch:
        db.session.execute(db.insert(SpectrumIndexEntry), batch)
    return len(entries)


def _finish(run_id: str, status: RunStatus, **values) -> None:
    run = db.session.get(SpectraRun, run_id)
    run.status = status
    for key, value in values.items():
        setattr(run, key, value)
    db.session.commit()
