"""Database models of the spectrum index.

One SpectraRun per mzML file of a published record, one SpectrumIndexEntry per
spectrum in it. Published files are immutable, so the index of a record
version never changes.
"""

from __future__ import annotations

import enum
import uuid

from invenio_db import db
from sqlalchemy_utils.types import ChoiceType, UUIDType


class RunStatus(enum.Enum):
    """Indexing state of a run."""

    PENDING = "P"
    INDEXED = "I"
    UNSUPPORTED = "U"
    FAILED = "F"


class SpectraRun(db.Model):
    """One mzML file of a record."""

    __tablename__ = "spectra_run"
    __table_args__ = (db.UniqueConstraint("record_pid", "ms_run", name="uq_spectra_run_record_ms_run"),)

    id = db.Column(UUIDType, primary_key=True, default=uuid.uuid4)
    record_pid = db.Column(db.String(255), nullable=False, index=True)
    file_key = db.Column(db.Text, nullable=False)
    ms_run = db.Column(db.Text, nullable=False)
    checksum = db.Column(db.String(255))
    status = db.Column(ChoiceType(RunStatus, impl=db.CHAR(1)), nullable=False, default=RunStatus.PENDING)
    error = db.Column(db.Text)
    spectra_count = db.Column(db.Integer)
    created = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now())


class SpectrumIndexEntry(db.Model):
    """Position and summary of one spectrum in an mzML file."""

    __tablename__ = "spectra_index"
    __table_args__ = (
        db.Index("ix_spectra_index_run_scan", "run_id", "scan"),
        db.Index("ix_spectra_index_run_native_id", "run_id", "native_id"),
    )

    run_id = db.Column(UUIDType, db.ForeignKey(SpectraRun.id, ondelete="CASCADE"), primary_key=True)
    # 0-based position of the spectrum in the file (USI indexType "index")
    position = db.Column(db.Integer, primary_key=True)
    native_id = db.Column(db.Text, nullable=False)
    scan = db.Column(db.Integer)
    offset = db.Column(db.BigInteger, nullable=False)
    length = db.Column(db.Integer, nullable=False)
    ms_level = db.Column(db.SmallInteger)
    rt = db.Column(db.Float)
    precursor_mz = db.Column(db.Float)
    charge = db.Column(db.SmallInteger)
