"""REST API for individual spectra.

- ``GET /api/proxi/v0.1/spectra?usi=...&resultType=compact|full`` (PROXI)
- ``GET /api/dataset/<id>/files/<key>/spectra?ms_level=&page=&size=`` (list)
- ``GET /api/dataset/<id>/files/<key>/spectra/<scan|index|nativeId>/<value>``
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from invenio_pidstore.errors import PIDDoesNotExistError, PIDUnregistered
from invenio_records_resources.services.errors import PermissionDeniedError

from .reader import SpectrumReadError, to_proxi
from .service import RunNotIndexed, SpectrumNotFound, get_spectrum, get_spectrum_by_usi, list_spectra
from .usi import INDEX_TYPES, InvalidUSI

blueprint = Blueprint("spectra_api", __name__)

RESULT_TYPES = ("compact", "full")


def create_blueprint(app):
    """Return the API blueprint (``invenio_base.api_blueprints`` entry point)."""
    return blueprint


def _error(status: int, message: str, **extra):
    return jsonify({"status": status, "title": message, **extra}), status


@blueprint.errorhandler(InvalidUSI)
def _invalid_usi(e):
    return _error(400, str(e))


@blueprint.errorhandler(PermissionDeniedError)
def _forbidden(e):
    return _error(403, "Permission denied")


@blueprint.errorhandler(SpectrumNotFound)
@blueprint.errorhandler(PIDDoesNotExistError)
@blueprint.errorhandler(PIDUnregistered)
def _not_found(e):
    return _error(404, str(e) or "Not found")


@blueprint.errorhandler(RunNotIndexed)
def _not_indexed(e):
    return _error(409, str(e), indexing_status=e.status.name, detail=e.error)


@blueprint.errorhandler(SpectrumReadError)
def _unreadable(e):
    return _error(422, str(e))


def _result_type() -> str:
    result_type = request.args.get("resultType", "full")
    if result_type not in RESULT_TYPES:
        raise InvalidUSI(f"resultType must be one of {', '.join(RESULT_TYPES)}")
    return result_type


@blueprint.route("/proxi/v0.1/spectra")
def proxi_spectra():
    """PROXI spectra endpoint; returns a list with one spectrum."""
    usi_value = request.args.get("usi")
    if not usi_value:
        return _error(400, "Parameter usi is required")
    result_type = _result_type()
    usi, spectrum = get_spectrum_by_usi(g.identity, usi_value)
    # echo the USI as requested (it may include an interpretation)
    return jsonify([to_proxi(str(usi), spectrum, result_type)])


@blueprint.route("/dataset/<pid_value>/files/<path:key>/spectra")
def file_spectra(pid_value, key):
    """List spectra of an mzML file."""
    ms_level = request.args.get("ms_level", type=int)
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 100, type=int)
    return jsonify(list_spectra(g.identity, pid_value, key, ms_level=ms_level, page=page, size=size))


@blueprint.route("/dataset/<pid_value>/files/<path:key>/spectra/<index_type>/<value>")
def file_spectrum(pid_value, key, index_type, value):
    """Return one spectrum of an mzML file in PROXI format."""
    if index_type not in INDEX_TYPES:
        return _error(400, f"Index type must be one of {', '.join(INDEX_TYPES)}")
    usi, spectrum = get_spectrum(g.identity, pid_value, index_type, value, file_key=key)
    return jsonify(to_proxi(usi, spectrum, _result_type()))
