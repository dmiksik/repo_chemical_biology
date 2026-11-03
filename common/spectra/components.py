"""Record service component scheduling the indexing of mzML files on publish."""

from __future__ import annotations

from typing import Any

from invenio_db import db
from invenio_drafts_resources.services.records.components import ServiceComponent
from invenio_i18n import gettext as _
from invenio_records_resources.services.uow import TaskOp
from marshmallow import ValidationError

from .models import SpectraRun
from .tasks import convert_run, index_run
from .usi import is_mzml, is_raw, ms_run_name


def _runs(keys: list[str]) -> dict[str, str]:
    """Return file keys by run name; raises ValidationError if two files have the same run name."""
    runs: dict[str, str] = {}
    for key in keys:
        ms_run = ms_run_name(key)
        if ms_run in runs:
            raise ValidationError(
                _("Files %(a)s and %(b)s have the same run name %(run)s.")
                % {"a": runs[ms_run], "b": key, "run": ms_run},
                field_name="files",
            )
        runs[ms_run] = key
    return runs


def register_runs(record) -> list[tuple[SpectraRun, Any]]:
    """Register runs of the mzML and raw files of a published record not registered yet.

    Raw files are converted to mzML first, unless the record also has an mzML
    file of the same run. Returns the new runs with the task to process them.
    """
    if not record.files.enabled:
        return []
    mzml_runs = _runs([key for key in record.files.entries if is_mzml(key)])
    raw_runs = {
        ms_run: key
        for ms_run, key in _runs([key for key in record.files.entries if is_raw(key)]).items()
        if ms_run not in mzml_runs
    }

    # Editing metadata of a published record publishes it again with the
    # same files - their runs are already registered.
    record_pid = record.pid.pid_value
    registered = {run.ms_run for run in SpectraRun.query.filter_by(record_pid=record_pid)}

    new_runs = []
    for runs, task in ((mzml_runs, index_run), (raw_runs, convert_run)):
        for ms_run, key in runs.items():
            if ms_run in registered:
                continue
            run = SpectraRun(
                record_pid=record_pid,
                file_key=key,
                ms_run=ms_run,
                checksum=record.files[key].file.checksum,
            )
            db.session.add(run)
            db.session.flush()
            new_runs.append((run, task))
    return new_runs


class SpectraIndexComponent(ServiceComponent):
    """On publish, register mzML and raw files of the record and process them in the background."""

    def publish(self, identity: Any, draft: Any = None, record: Any = None, **kwargs: Any) -> None:
        for run, task in register_runs(record):
            self.uow.register(TaskOp(task, str(run.id)))
