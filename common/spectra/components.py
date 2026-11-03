"""Record service component scheduling the indexing of mzML files on publish."""

from __future__ import annotations

from typing import Any

from invenio_db import db
from invenio_drafts_resources.services.records.components import ServiceComponent
from invenio_i18n import gettext as _
from invenio_records_resources.services.uow import TaskOp
from marshmallow import ValidationError

from .models import SpectraRun
from .tasks import index_run
from .usi import is_mzml, ms_run_name


class SpectraIndexComponent(ServiceComponent):
    """On publish, register mzML files of the record and index them in the background."""

    def publish(self, identity: Any, draft: Any = None, record: Any = None, **kwargs: Any) -> None:
        if not record.files.enabled:
            return
        keys = [key for key in record.files.entries if is_mzml(key)]

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

        # Editing metadata of a published record publishes it again with the
        # same files - their runs are already registered.
        record_pid = record.pid.pid_value
        registered = {run.ms_run for run in SpectraRun.query.filter_by(record_pid=record_pid)}

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
            self.uow.register(TaskOp(index_run, str(run.id)))
