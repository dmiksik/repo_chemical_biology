"""REST API for individual spectra.

- ``GET /api/proxi/v0.1/spectra?usi=...&resultType=compact|full`` (PROXI)
- ``GET /api/proxi/v0.1/datasets``, ``/api/proxi/v0.1/datasets/<accession or id>`` (PROXI)
- ``GET /api/dataset/<id>/files/<key>/spectra?ms_level=&page=&size=`` (list)
- ``GET /api/dataset/<id>/files/<key>/spectra/<scan|index|nativeId>/<value>``
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from invenio_pidstore.errors import PIDDoesNotExistError, PIDUnregistered
from invenio_records_resources.services.errors import PermissionDeniedError

from .proxi import to_proxi_dataset
from .reader import SpectrumReadError, to_proxi
from .service import (
    RunNotIndexed,
    SpectrumNotFound,
    get_spectrum,
    get_spectrum_by_usi,
    list_spectra,
    records_service,
    resolve_collection,
)
from .usi import INDEX_TYPES, InvalidUSI, build_usi

blueprint = Blueprint("spectra_api", __name__)

# UI app blueprint, only provides the templates of the mzML previewer
ui_blueprint = Blueprint("spectra_ui", __name__, template_folder="templates")

RESULT_TYPES = ("compact", "full")


def create_blueprint(app):
    """Return the API blueprint (``invenio_base.api_blueprints`` entry point)."""
    return blueprint


def create_ui_blueprint(app):
    """Return the UI blueprint (``invenio_base.blueprints`` entry point)."""
    return ui_blueprint


def _error(status: int, message: str, **extra):
    # PROXI Error object
    return jsonify({"code": status, "message": message, **extra}), status


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


def _quote(value: str) -> str:
    """Return a value as a quoted phrase of a search query."""
    return '"' + value.strip().replace("\\", "").replace('"', "") + '"'


def _result_type(default: str) -> str:
    result_type = request.args.get("resultType", default)
    if result_type not in RESULT_TYPES:
        raise InvalidUSI(f"resultType must be one of {', '.join(RESULT_TYPES)}")
    return result_type


@blueprint.route("/proxi/v0.1/spectra")
def proxi_spectra():
    """PROXI spectra endpoint; returns a list with one spectrum.

    The spectrum is given by ``usi``, or by ``accession`` (or record id),
    ``msRun`` and ``scan``.
    """
    usi_value = request.args.get("usi")
    if not usi_value:
        accession, ms_run, scan = (request.args.get(p) for p in ("accession", "msRun", "scan"))
        if not (accession and ms_run and scan):
            return _error(400, "Parameter usi, or accession, msRun and scan are required")
        usi_value = build_usi(accession, ms_run, "scan", scan)
    result_type = _result_type("compact")
    usi, spectrum = get_spectrum_by_usi(g.identity, usi_value)
    # echo the USI as requested (it may include an interpretation)
    return jsonify([to_proxi(str(usi), spectrum, result_type)])


@blueprint.route("/proxi/v0.1/datasets")
def proxi_datasets():
    """PROXI datasets endpoint: published dataset records the user can read."""
    page_size = max(1, min(request.args.get("pageSize", 100, type=int), 100))
    page = max(1, request.args.get("pageNumber", 1, type=int))
    result_type = _result_type("compact")
    query = []
    if request.args.get("accession"):
        accessions = [_quote(a) for a in request.args["accession"].strip("[]").split(",") if a.strip()]
        query.append("(" + " OR ".join(f"metadata.identifiers.identifier:{a} OR id:{a}" for a in accessions) + ")")
    if request.args.get("species"):
        query.append(_quote(request.args["species"]))
    if request.args.get("search"):
        query.append(request.args["search"])
    result = records_service().search(
        g.identity, params={"q": " AND ".join(query), "size": page_size, "page": page}
    )
    return jsonify([to_proxi_dataset(hit, result_type) for hit in result.hits])


@blueprint.route("/proxi/v0.1/datasets/<identifier>")
def proxi_dataset(identifier):
    """PROXI dataset endpoint; the identifier is a PXD/MSV accession or a record id."""
    record = records_service().read(g.identity, resolve_collection(identifier)).to_dict()
    return jsonify(to_proxi_dataset(record, _result_type("full")))


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
    # besides the PROXI fields, the position of the spectrum in the file
    return jsonify({**to_proxi(usi, spectrum, _result_type("full")), "index": spectrum["index"]})
