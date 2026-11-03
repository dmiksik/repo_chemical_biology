"""Reading the file-level metadata of an mzML file: instrument, software, source files.

These live in the mzML header, before the ``<run>`` element, so only the start
of the file is read. This module has no Invenio dependencies.
"""

from __future__ import annotations

import re
from typing import Any, BinaryIO
from xml.etree import ElementTree

from .reader import MZML_NS, SpectrumReadError, cv_params

CHUNK_SIZE = 64 * 1024
# The header is a few kB; give up on files without <run> near the start.
MAX_HEADER_SIZE = 4 * 1024 * 1024

INSTRUMENT_SERIAL_NUMBER = "MS:1000529"

_RUN_RE = re.compile(rb"<run\b([^>]*)>")
_ATTRIBUTE_RE = re.compile(rb'(\w+)="([^"]*)"')
_HEADER_START_RE = re.compile(rb"<(cvList|fileDescription)\b")


def read_header(fp: BinaryIO) -> dict[str, Any]:
    """Return instruments, software, source files, data processing and run attributes of an mzML file."""
    fp.seek(0)
    data = b""
    while (match := _RUN_RE.search(data)) is None:
        chunk = fp.read(CHUNK_SIZE)
        if not chunk or len(data) > MAX_HEADER_SIZE:
            raise SpectrumReadError("No <run> element at the start of the file")
        data += chunk
    return parse_header(data[: match.end()])


def parse_header(data: bytes) -> dict[str, Any]:
    """Parse the mzML header, from the start of the file up to the ``<run>`` start tag."""
    run_match = _RUN_RE.search(data)
    start_match = _HEADER_START_RE.search(data)
    if run_match is None:
        raise SpectrumReadError("Not an mzML header")
    # cvList ... dataProcessingList are complete sibling elements (required by
    # the mzML schema, but tolerate files without them)
    body = data[start_match.start() : run_match.start()] if start_match and start_match.start() < run_match.start() else b""
    try:
        root = ElementTree.fromstring(b'<w xmlns="http://psi.hupo.org/ms/mzml">' + body + b"</w>")
    except ElementTree.ParseError as e:
        raise SpectrumReadError(f"Invalid mzML header: {e}") from e

    groups = {
        group.get("id"): cv_params(group)
        for group in root.iterfind(_path("referenceableParamGroupList/referenceableParamGroup"))
    }

    def params(element: ElementTree.Element) -> list[dict[str, str]]:
        """cvParams of an element, including the referenced param groups."""
        result = []
        for ref in element.iterfind(MZML_NS + "referenceableParamGroupRef"):
            result.extend(groups.get(ref.get("ref"), []))
        return result + cv_params(element)

    run = {key.decode(): value.decode() for key, value in _ATTRIBUTE_RE.findall(run_match.group(1))}
    return {
        "run": {
            "id": run.get("id"),
            "start_time": run.get("startTimeStamp"),
            "instrument": run.get("defaultInstrumentConfigurationRef"),
        },
        "source_files": [
            {"id": f.get("id"), "name": f.get("name"), "params": params(f)}
            for f in root.iterfind(_path("fileDescription/sourceFileList/sourceFile"))
        ],
        "instruments": [
            {
                "id": ic.get("id"),
                "params": params(ic),
                "components": [
                    {"type": component.tag.removeprefix(MZML_NS), "params": params(component)}
                    for component in ic.iterfind(_path("componentList/*"))
                ],
            }
            for ic in root.iterfind(_path("instrumentConfigurationList/instrumentConfiguration"))
        ],
        "software": [
            {"id": s.get("id"), "version": s.get("version"), "params": params(s)}
            for s in root.iterfind(_path("softwareList/software"))
        ],
        "data_processing": [
            {
                "id": dp.get("id"),
                "methods": [
                    {"software": method.get("softwareRef"), "params": params(method)}
                    for method in dp.iterfind(MZML_NS + "processingMethod")
                ],
            }
            for dp in root.iterfind(_path("dataProcessingList/dataProcessing"))
        ],
    }


def default_instrument(header: dict[str, Any]) -> dict[str, Any] | None:
    """Return the instrument configuration used by default in the run."""
    instruments = header.get("instruments") or []
    ref = (header.get("run") or {}).get("instrument")
    return next((i for i in instruments if i["id"] == ref), instruments[0] if instruments else None)


def instrument_model(header: dict[str, Any]) -> dict[str, str] | None:
    """Return the instrument model term (e.g. MS:1001911 Q Exactive).

    The model is the instrument configuration's cvParam without a value;
    the serial number is the only valued one mzML puts there.
    """
    instrument = default_instrument(header)
    if instrument is None:
        return None
    return next(
        (p for p in instrument["params"] if p["accession"] != INSTRUMENT_SERIAL_NUMBER and "value" not in p), None
    )


def attributes(header: dict[str, Any]) -> list[dict[str, str]]:
    """Return the instrument and software of a run as PROXI attributes (PSI-MS terms)."""
    result = []
    instrument = default_instrument(header)
    if instrument is not None:
        result.extend(p for p in instrument["params"] if p["accession"] != INSTRUMENT_SERIAL_NUMBER)
        for component in instrument["components"]:
            result.extend(component["params"])
    for software in header.get("software") or []:
        for param in software["params"]:
            term = {"accession": param["accession"], "name": param["name"]}
            if software.get("version"):
                term["value"] = software["version"]
            result.append(term)
    return result


def _path(path: str) -> str:
    return "/".join(part if part == "*" else MZML_NS + part for part in path.split("/"))
