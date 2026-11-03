"""Celery tasks converting raw files and indexing mzML files of published records."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from celery import shared_task
from flask import current_app
from invenio_access.permissions import system_identity
from invenio_db import db
from invenio_files_rest.models import FileInstance, Location

from .converter import ConversionError, convert_raw
from .models import RunStatus, SpectraRun, SpectrumIndexEntry
from .mzml_index import NotIndexedMzML, read_index
from .reader import SpectrumReadError, parse_spectrum, read_spectrum_xml
from .usi import scan_number

BATCH_SIZE = 5000


def run_file(run: SpectraRun) -> FileInstance:
    """Return the file holding the mzML of a run: the record file, or the mzML converted from it."""
    from .service import records_service

    if run.converted_file_id:
        return db.session.get(FileInstance, run.converted_file_id)
    record = records_service().record_cls.pid.resolve(run.record_pid)
    return record.files[run.file_key].file.file_model


@shared_task(ignore_result=True)
def convert_run(run_id: str) -> None:
    """Convert the raw file of a run to mzML, store it and index it."""
    from .service import files_service

    run = db.session.get(SpectraRun, run_id)
    if run is None or run.converted_file_id:
        return
    _finish(run_id, RunStatus.CONVERTING)

    workdir = Path(tempfile.mkdtemp(prefix="spectra-"))
    try:
        (workdir / "input").mkdir()
        (workdir / "output").mkdir()
        raw_path = workdir / "input" / Path(run.file_key).name
        file = files_service().get_file_content(system_identity, run.record_pid, run.file_key)
        with file.open_stream("rb") as source, raw_path.open("wb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)

        mzml_path = convert_raw(raw_path, workdir / "output")

        # Not stored in the record (media) files: those have their own access
        # rules, the converted data must be protected as the raw file.
        converted = FileInstance.create()
        with mzml_path.open("rb") as stream:
            converted.set_contents(
                stream,
                default_location=Location.get_default().uri,
                default_storage_class=current_app.config["FILES_REST_DEFAULT_STORAGE_CLASS"],
            )
        run.converted_file_id = converted.id
        db.session.commit()
    except ConversionError as e:
        db.session.rollback()
        _finish(run_id, RunStatus.FAILED, error=str(e))
        return
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Conversion of spectra run %s failed", run_id)
        _finish(run_id, RunStatus.FAILED, error=str(e))
        return
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    index_run(run_id)


@shared_task(ignore_result=True)
def index_run(run_id: str) -> None:
    """Build the spectrum index of one run (mzML file)."""
    run = db.session.get(SpectraRun, run_id)
    if run is None or run.status == RunStatus.INDEXED:
        return

    try:
        file = run_file(run)
        stream = file.storage().open()
        try:
            count = _index(run, stream, file.size)
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
