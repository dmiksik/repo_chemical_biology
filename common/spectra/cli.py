"""CLI for the spectrum index: ``invenio spectra ...``."""

from __future__ import annotations

import click
from flask.cli import with_appcontext


@click.group()
def spectra():
    """Spectrum index commands."""


@spectra.command("index")
@click.argument("record_ids", nargs=-1)
@click.option("--all", "all_records", is_flag=True, help="All published dataset records.")
@click.option("--sync", is_flag=True, help="Process in this process instead of a Celery worker.")
@with_appcontext
def index(record_ids, all_records, sync):
    """Register and index spectra of RECORD_IDS (e.g. records published before spectra indexing).

    Files already registered are skipped; to re-index a file, use ``reset`` first.
    """
    from invenio_db import db

    from .components import register_runs
    from .service import records_service

    record_cls = records_service().record_cls
    if all_records:
        record_ids = [
            m.json["id"]
            for m in record_cls.model_cls.query.filter_by(is_deleted=False).all()
            if m.json and m.json.get("id")
        ]
    for record_id in record_ids:
        record = record_cls.pid.resolve(record_id)
        runs = register_runs(record)
        db.session.commit()
        for run, task in runs:
            if sync:
                task(str(run.id))
            else:
                task.delay(str(run.id))
        click.echo(f"{record_id}: {len(runs)} new run(s): {', '.join(run.file_key for run, _ in runs) or '-'}")


@spectra.command("reset")
@click.argument("record_id")
@with_appcontext
def reset(record_id):
    """Remove the spectrum index of RECORD_ID (converted files are deleted too)."""
    from invenio_db import db
    from invenio_files_rest.models import FileInstance

    from .models import SpectraRun, SpectrumIndexEntry

    runs = SpectraRun.query.filter_by(record_pid=record_id).all()
    for run in runs:
        SpectrumIndexEntry.query.filter_by(run_id=run.id).delete()
        converted = db.session.get(FileInstance, run.converted_file_id) if run.converted_file_id else None
        db.session.delete(run)
        if converted:
            db.session.flush()
            converted.storage().delete()
            db.session.delete(converted)
    db.session.commit()
    click.echo(f"{record_id}: removed {len(runs)} run(s)")


@spectra.command("status")
@click.argument("record_id")
@with_appcontext
def status(record_id):
    """Show the indexing status of the files of RECORD_ID."""
    from .models import SpectraRun

    for run in SpectraRun.query.filter_by(record_pid=record_id).order_by(SpectraRun.file_key):
        converted = " (converted)" if run.converted_file_id else ""
        error = f" - {run.error}" if run.error else ""
        click.echo(f"{run.file_key}{converted}: {run.status.name}, {run.spectra_count or 0} spectra{error}")
