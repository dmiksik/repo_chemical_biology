"""Reading one spectrum from an mzML file and converting it to PROXI JSON.

The spectrum is read by its byte offset (see mzml_index.py), so only a small
part of the file is transferred. PROXI response format:
https://github.com/HUPO-PSI/proxi-schemas (specs/swagger.yaml, Spectrum).

This module has no Invenio dependencies.
"""

from __future__ import annotations

import base64
import sys
import zlib
from array import array
from typing import Any, BinaryIO
from xml.etree import ElementTree

MZML_NS = "{http://psi.hupo.org/ms/mzml}"

# Binary data array encodings (PSI-MS accessions)
FLOAT_32 = "MS:1000521"
FLOAT_64 = "MS:1000523"
INT_32 = "MS:1000519"
INT_64 = "MS:1000522"
ZLIB = "MS:1000574"
NO_COMPRESSION = "MS:1000576"
MZ_ARRAY = "MS:1000514"
INTENSITY_ARRAY = "MS:1000515"
MS_LEVEL = "MS:1000511"
SCAN_START_TIME = "MS:1000016"
SELECTED_ION_MZ = "MS:1000744"
CHARGE_STATE = "MS:1000041"
UNIT_MINUTE = "UO:0000031"

_TYPECODES = {FLOAT_32: "f", FLOAT_64: "d", INT_32: "i", INT_64: "q"}

# cvParams of the spectrum returned as PROXI attributes, by element path.
# Scan start time, selected ion m/z, charge state etc. live in nested elements.
_ATTRIBUTE_PATHS = (
    ".",
    "scanList/scan",
    "precursorList/precursor/isolationWindow",
    "precursorList/precursor/selectedIonList/selectedIon",
    "precursorList/precursor/activation",
)

_SPECTRUM_END = b"</spectrum>"


class SpectrumReadError(ValueError):
    """The spectrum could not be read or decoded."""


def read_spectrum_xml(fp: BinaryIO, offset: int, length: int) -> bytes:
    """Read the ``<spectrum>`` element at offset, trimmed after ``</spectrum>``."""
    fp.seek(offset)
    return spectrum_xml(fp.read(length), offset)


def spectrum_xml(chunk: bytes, offset: int) -> bytes:
    """Return the ``<spectrum>`` element from bytes read at its offset (see mzml_index.IndexEntry)."""
    if not chunk.lstrip().startswith(b"<spectrum"):
        raise SpectrumReadError(f"No <spectrum> element at offset {offset}")
    end = chunk.find(_SPECTRUM_END)
    if end < 0:
        raise SpectrumReadError(f"Unterminated <spectrum> element at offset {offset}")
    return chunk[: end + len(_SPECTRUM_END)]


def parse_spectrum(xml: bytes, decode_arrays: bool = True) -> dict[str, Any]:
    """Parse a ``<spectrum>`` element into native_id, index, attributes, mzs and intensities.

    With ``decode_arrays=False`` mzs and intensities are left empty (used when indexing).
    """
    # The element is cut out of its document, so declare the mzML namespace.
    wrapped = b'<w xmlns="http://psi.hupo.org/ms/mzml">' + xml + b"</w>"
    try:
        spectrum = ElementTree.fromstring(wrapped)[0]
    except ElementTree.ParseError as e:
        raise SpectrumReadError(f"Invalid spectrum XML: {e}") from e

    attributes = []
    for path in _ATTRIBUTE_PATHS:
        for element in spectrum.findall(_ns(path)) if path != "." else [spectrum]:
            attributes.extend(_cv_params(element))

    arrays = {}
    for data_array in spectrum.iterfind(_ns("binaryDataArrayList/binaryDataArray")):
        params = {p["accession"] for p in _cv_params(data_array)}
        kind = MZ_ARRAY if MZ_ARRAY in params else INTENSITY_ARRAY if INTENSITY_ARRAY in params else None
        if kind and decode_arrays:
            arrays[kind] = _decode_array(data_array, params)

    return {
        "native_id": spectrum.get("id"),
        "index": int(spectrum.get("index", -1)),
        "summary": _summary(spectrum),
        "attributes": attributes,
        "mzs": arrays.get(MZ_ARRAY, []),
        "intensities": arrays.get(INTENSITY_ARRAY, []),
    }


def to_proxi(usi: str, spectrum: dict[str, Any], result_type: str = "full") -> dict[str, Any]:
    """Build a PROXI Spectrum object. ``compact`` omits attributes."""
    result = {
        "usi": usi,
        "status": "READABLE",
        "mzs": spectrum["mzs"],
        "intensities": spectrum["intensities"],
    }
    if result_type == "full":
        result["attributes"] = spectrum["attributes"]
    return result


def _summary(spectrum: ElementTree.Element) -> dict[str, Any]:
    """Return ms_level, rt (seconds), precursor_mz and charge of the spectrum."""

    def param(path: str, accession: str) -> ElementTree.Element | None:
        parent = spectrum.find(_ns(path)) if path else spectrum
        return parent.find(f"{MZML_NS}cvParam[@accession='{accession}']") if parent is not None else None

    def number(element: ElementTree.Element | None, cast: type) -> Any:
        try:
            return cast(element.get("value")) if element is not None else None
        except (TypeError, ValueError):
            return None

    rt_param = param("scanList/scan", SCAN_START_TIME)
    rt = number(rt_param, float)
    if rt is not None and rt_param.get("unitAccession") == UNIT_MINUTE:
        rt *= 60
    selected_ion = "precursorList/precursor/selectedIonList/selectedIon"
    return {
        "ms_level": number(param("", MS_LEVEL), int),
        "rt": rt,
        "precursor_mz": number(param(selected_ion, SELECTED_ION_MZ), float),
        "charge": number(param(selected_ion, CHARGE_STATE), int),
    }


def _ns(path: str) -> str:
    return "/".join(MZML_NS + part for part in path.split("/"))


def _cv_params(element: ElementTree.Element) -> list[dict[str, str]]:
    params = []
    for cv in element.iterfind(MZML_NS + "cvParam"):
        param = {"accession": cv.get("accession"), "name": cv.get("name")}
        if cv.get("value"):
            param["value"] = cv.get("value")
        params.append(param)
    return params


def _decode_array(data_array: ElementTree.Element, params: set[str]) -> list[float]:
    typecode = next((code for acc, code in _TYPECODES.items() if acc in params), None)
    if typecode is None:
        raise SpectrumReadError("Unsupported binary data type")
    if not params & {ZLIB, NO_COMPRESSION}:
        # e.g. MS-Numpress encodings
        raise SpectrumReadError("Unsupported binary data compression")

    binary = data_array.find(MZML_NS + "binary")
    raw = base64.b64decode((binary.text or "") if binary is not None else "")
    if ZLIB in params:
        raw = zlib.decompress(raw)
    values = array(typecode)
    values.frombytes(raw)
    if sys.byteorder == "big":
        # mzML binary data are little-endian
        values.byteswap()
    return values.tolist()
