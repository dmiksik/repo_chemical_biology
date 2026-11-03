"""Spectra as MGF (Mascot Generic Format), the common exchange format of MS/MS spectra.

Besides the Mascot keys (TITLE, PEPMASS, CHARGE, RTINSECONDS) it uses the
keys of GNPS spectral libraries (MSLEVEL, SCANS, SOURCE_INSTRUMENT, IONMODE,
ORGANISM, PI, DATACOLLECTOR, FILENAME), which matchms and GNPS read, and
USI, DATASET, LICENSE and CITATION, which keep the spectrum citable.
Spectra that could not be read are listed in ``#`` comment lines, which MGF
readers skip. This module has no Invenio dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

COLLISION_ENERGY = "MS:1000045"
POSITIVE_SCAN = "MS:1000130"
NEGATIVE_SCAN = "MS:1000129"


def _clean(value: Any) -> str:
    """One-line value; MGF has no escaping."""
    return " ".join(str(value).split())


def _attribute(spectrum: dict[str, Any], accession: str) -> dict[str, str] | None:
    return next((a for a in spectrum.get("attributes", []) if a["accession"] == accession), None)


def spectrum_mgf(
    usi: str,
    spectrum: dict[str, Any],
    provenance: dict[str, Any] | None = None,
    instrument: str | None = None,
    scan: int | None = None,
) -> str:
    """Return one spectrum (as parsed by reader.parse_spectrum) as an MGF ``BEGIN IONS`` block."""
    summary = spectrum.get("summary", {})
    lines = ["BEGIN IONS", f"TITLE={_clean(usi)}", f"USI={_clean(usi)}"]

    if summary.get("precursor_mz") is not None:
        lines.append(f"PEPMASS={summary['precursor_mz']}")
    ion_mode = (
        "positive"
        if _attribute(spectrum, POSITIVE_SCAN)
        else "negative"
        if _attribute(spectrum, NEGATIVE_SCAN)
        else None
    )
    if summary.get("charge"):
        sign = "-" if ion_mode == "negative" else "+"
        lines.append(f"CHARGE={abs(summary['charge'])}{sign}")
    if summary.get("ms_level") is not None:
        lines.append(f"MSLEVEL={summary['ms_level']}")
    if summary.get("rt") is not None:
        lines.append(f"RTINSECONDS={summary['rt']:.4f}")
    if scan is not None:
        lines.append(f"SCANS={scan}")
    if ion_mode:
        lines.append(f"IONMODE={ion_mode}")
    collision_energy = _attribute(spectrum, COLLISION_ENERGY)
    if collision_energy and collision_energy.get("value"):
        lines.append(f"COLLISION_ENERGY={collision_energy['value']}")
    if instrument:
        lines.append(f"SOURCE_INSTRUMENT={_clean(instrument)}")

    if provenance:
        dataset = provenance.get("dataset", {})
        file = provenance.get("file", {})
        values = {
            "FILENAME": file.get("key"),
            "DATASET": dataset.get("accession") or dataset.get("id"),
            "ORGANISM": dataset.get("organism"),
            "PI": "; ".join(dataset.get("creators") or []),
            "DATACOLLECTOR": "; ".join(dataset.get("data_collectors") or []),
            "LICENSE": "; ".join(lic.get("id") or lic.get("title", "") for lic in dataset.get("licenses") or []),
            "CITATION": dataset.get("citation"),
        }
        lines.extend(f"{key}={_clean(value)}" for key, value in values.items() if value)

    lines.extend(f"{mz} {intensity}" for mz, intensity in zip(spectrum["mzs"], spectrum["intensities"], strict=True))
    lines.append("END IONS")
    return "\n".join(lines) + "\n"


def failure_comment(usi: str, code: int, message: str) -> str:
    """A comment line for a spectrum that could not be read."""
    return f"# {_clean(usi)}: {code} {_clean(message)}\n"


def mgf(blocks: Iterable[str]) -> Iterator[str]:
    """Join spectrum blocks and comments, a blank line between spectra."""
    for block in blocks:
        yield block if block.startswith("#") else block + "\n"
