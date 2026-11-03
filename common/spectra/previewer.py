"""Previewer of mzML files: list of spectra and a plot of the selected one.

Registered as ``invenio_previewer.previewers`` entry point ``mzml``; the data
are loaded in the browser from the spectra API (views.py).
"""

from __future__ import annotations

from flask import render_template, request
from invenio_previewer.proxies import current_previewer

previewable_extensions = ["mzml", "raw"]


def can_preview(file) -> bool:
    """Determine if the given file can be previewed (raw files are converted to mzML)."""
    return file.has_extensions(".mzml", ".raw")


def preview(file):
    """Render the previewer page."""
    return render_template(
        "spectra/mzml_previewer.html",
        file=file,
        record_pid=request.view_args.get("pid_value"),
        # spectra are indexed on publish, a draft has none yet
        is_draft=(request.endpoint or "").endswith("draft_file_preview"),
        js_bundles=[*current_previewer.js_bundles, "spectra-mzml-previewer.js"],
        css_bundles=[*current_previewer.css_bundles, "spectra-mzml-previewer.css"],
    )
