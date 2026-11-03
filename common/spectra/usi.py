"""Universal Spectrum Identifier (USI) parsing and building.

Specification: https://www.psidev.info/usi (USI 1.0)::

    mzspec:<collection>:<msRun>:<indexType>:<indexNumber>[:<interpretation>]

Collection is a ProteomeXchange / MassIVE accession (PXD..., MSV...) if the
dataset has one. Otherwise the record id is used - this is not in the list of
USI collection identifiers, but it is unique within this repository.

msRun is the file key without the ``.mzML`` extension.

This module has no Invenio dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

USI_PREFIX = "mzspec"

INDEX_TYPES = ("scan", "index", "nativeId")

# Collection identifiers registered in the USI specification.
ACCESSION_RE = re.compile(r"^(PXD|RPXD|PXL)\d{6}$|^(MSV|RMSV)\d{9}$")

MZML_EXTENSIONS = (".mzml",)

# Vendor raw files converted to mzML (Thermo)
RAW_EXTENSIONS = (".raw",)

# msRun may contain colons, so the USI is anchored on the index type instead
# of being split on ':'.
USI_RE = re.compile(
    r"^mzspec:(?P<collection>[^:]+):(?P<ms_run>.+?)"
    r":(?P<index_type>scan|index|nativeId):(?P<index>[^:]+)"
    r"(?::(?P<interpretation>.+))?$"
)

_NATIVE_ID_PAIR_RE = re.compile(r"(\S+?)=(\S+)")


class InvalidUSI(ValueError):
    """The string is not a valid USI."""


@dataclass(frozen=True)
class USI:
    """Parsed USI."""

    collection: str
    ms_run: str
    index_type: str
    index: str
    interpretation: str | None = None

    @property
    def is_accession(self) -> bool:
        """True if the collection is a ProteomeXchange / MassIVE accession, not a record id."""
        return is_accession(self.collection)

    def __str__(self) -> str:
        return build_usi(self.collection, self.ms_run, self.index_type, self.index, self.interpretation)


def is_accession(collection: str) -> bool:
    """Return True if the collection is a PXD/MSV style accession."""
    return bool(ACCESSION_RE.match(collection))


def is_mzml(key: str) -> bool:
    """Return True if the file key has an mzML extension (case insensitive)."""
    return key.lower().endswith(MZML_EXTENSIONS)


def is_raw(key: str) -> bool:
    """Return True if the file key has a raw file extension that is converted to mzML."""
    return key.lower().endswith(RAW_EXTENSIONS)


def ms_run_name(key: str) -> str:
    """Return the msRun component for a file key: the key without the mzML or raw extension."""
    for extension in (*MZML_EXTENSIONS, *RAW_EXTENSIONS):
        if key.lower().endswith(extension):
            return key[: -len(extension)]
    return key


def parse_usi(value: str) -> USI:
    """Parse a USI string; raises InvalidUSI."""
    match = USI_RE.match(value.strip()) if value else None
    if not match:
        raise InvalidUSI(f"Invalid USI: {value!r}")
    return USI(**match.groupdict())


def build_usi(
    collection: str,
    ms_run: str,
    index_type: str,
    index: str | int,
    interpretation: str | None = None,
) -> str:
    """Assemble a USI string."""
    if index_type not in INDEX_TYPES:
        raise InvalidUSI(f"Invalid index type: {index_type!r}")
    if not collection or not ms_run:
        raise InvalidUSI("Collection and msRun are required")
    usi = f"{USI_PREFIX}:{collection}:{ms_run}:{index_type}:{index}"
    return f"{usi}:{interpretation}" if interpretation else usi


def scan_number(native_id: str) -> int | None:
    """Return the scan number from an mzML nativeID, or None if it has none.

    Handles ``scan=N`` and Thermo ``controllerType=0 controllerNumber=1 scan=N``.
    """
    pairs = dict(_NATIVE_ID_PAIR_RE.findall(native_id))
    scan = pairs.get("scan")
    if scan is None or not scan.isdigit():
        return None
    if pairs.keys() == {"scan"} or (
        pairs.keys() == {"controllerType", "controllerNumber", "scan"}
        and pairs["controllerType"] == "0"
        and pairs["controllerNumber"] == "1"
    ):
        return int(scan)
    return None


def native_id_value(native_id: str) -> str:
    """Return the USI ``nativeId`` index value: the nativeID values joined by commas.

    For example ``sample=1 period=1 cycle=2 experiment=1`` -> ``1,1,2,1``.
    """
    pairs = _NATIVE_ID_PAIR_RE.findall(native_id)
    return ",".join(v for _, v in pairs) if pairs else native_id
