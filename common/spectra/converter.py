"""Conversion of vendor raw files to indexed mzML.

The command is configurable (``SPECTRA_RAW_CONVERTER``), by default
ThermoRawFileParser in Docker. Placeholders ``{input_dir}``, ``{input}``,
``{output_dir}``, ``{uid}`` and ``{gid}`` are replaced; the command must
write ``<input name without extension>.mzML`` to the output directory.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from flask import current_app

DEFAULT_CONVERTER = [
    "docker", "run", "--rm",
    "--user", "{uid}:{gid}",
    "-v", "{input_dir}:/input:ro",
    "-v", "{output_dir}:/output",
    "quay.io/biocontainers/thermorawfileparser:1.4.5--h05cac1d_1",
    "ThermoRawFileParser.sh", "-i", "/input/{input}", "-o", "/output", "-f", "2",
]  # fmt: skip

DEFAULT_TIMEOUT = 3600


class ConversionError(RuntimeError):
    """The raw file could not be converted."""


def convert_raw(raw_path: Path, output_dir: Path) -> Path:
    """Convert a raw file to indexed mzML and return the path of the mzML."""
    command = [
        part.format(
            input_dir=raw_path.parent,
            input=raw_path.name,
            output_dir=output_dir,
            uid=os.getuid(),
            gid=os.getgid(),
        )
        for part in current_app.config.get("SPECTRA_RAW_CONVERTER", DEFAULT_CONVERTER)
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=current_app.config.get("SPECTRA_CONVERSION_TIMEOUT", DEFAULT_TIMEOUT),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ConversionError(f"Conversion of {raw_path.name} failed: {e}") from e

    mzml = output_dir / f"{raw_path.stem}.mzML"
    if result.returncode != 0 or not mzml.exists():
        output = (result.stderr or result.stdout).strip()[-2000:]
        raise ConversionError(f"Conversion of {raw_path.name} failed (exit {result.returncode}): {output}")
    return mzml
