"""REST API for individual spectra.

- ``GET /api/proxi/v0.1/spectra?usi=...&resultType=compact|full`` (PROXI)
- ``POST /api/proxi/v0.1/spectra?resultType=&format=json|mgf`` with ``{"usis": [...]}`` (batch, extension)
- ``GET /api/proxi/v0.1/datasets``, ``/api/proxi/v0.1/datasets/<accession or id>`` (PROXI)
- ``GET /api/dataset/<id>/files/<key>/spectra?ms_level=&page=&size=`` (list)
- ``GET /api/dataset/<id>/files/<key>/spectra/<scan|index|nativeId>/<value>``
"""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
    current_app,
    g,
    jsonify,
    request,
    stream_with_context,
)
from invenio_pidstore.errors import PIDDoesNotExistError, PIDUnregistered
from invenio_records_resources.services.errors import PermissionDeniedError

from .header import instrument_model
from .mgf import failure_comment, mgf, spectrum_mgf
from .proxi import to_proxi_dataset
from .reader import SpectrumReadError
from .service import (
    RunNotIndexed,
    SpectrumAccess,
    SpectrumFailure,
    SpectrumNotFound,
    get_spectra,
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
FORMATS = ("json", "mgf")
DEFAULT_BATCH_LIMIT = 1000


def create_blueprint(app):
    """Return the API blueprint (``invenio_base.api_blueprints`` entry point)."""
    return blueprint


def create_ui_blueprint(app):
    """Return the UI blueprint (``invenio_base.blueprints`` entry point)."""
    return ui_blueprint


def _error(status: int, message: str, **extra):
    # PROXI Error object
    return jsonify({"code": status, "message": message, **extra}), status


def error_status(e: Exception) -> tuple[int, str]:
    """HTTP status and message of a spectrum error."""
    if isinstance(e, InvalidUSI):
        return 400, str(e)
    if isinstance(e, PermissionDeniedError):
        return 403, "Permission denied"
    if isinstance(e, (SpectrumNotFound, PIDDoesNotExistError, PIDUnregistered)):
        return 404, str(e) or "Not found"
    if isinstance(e, RunNotIndexed):
        return 409, str(e)
    if isinstance(e, SpectrumReadError):
        return 422, str(e)
    raise e


@blueprint.errorhandler(InvalidUSI)
@blueprint.errorhandler(PermissionDeniedError)
@blueprint.errorhandler(SpectrumNotFound)
@blueprint.errorhandler(PIDDoesNotExistError)
@blueprint.errorhandler(PIDUnregistered)
@blueprint.errorhandler(SpectrumReadError)
def _spectrum_error(e):
    return _error(*error_status(e))


@blueprint.errorhandler(RunNotIndexed)
def _not_indexed(e):
    return _error(409, str(e), indexing_status=e.status.name, detail=e.error)


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
    access = SpectrumAccess(g.identity)
    result = get_spectrum_by_usi(access, usi_value)
    # echo the USI as requested (it may include an interpretation)
    return jsonify([access.proxi(result, result_type, usi=usi_value)])


@blueprint.route("/proxi/v0.1/spectra", methods=["POST"])
def proxi_spectra_batch():
    """Spectra of a list of USIs (not part of PROXI 0.1).

    Body: ``{"usis": [...]}``. ``format=json`` (default) returns a list of
    PROXI spectra in the order of the USIs; spectra that cannot be read get
    the status ``PEAK UNAVAILABLE`` and an ``error`` {code, message}.
    ``format=mgf`` returns MGF with unreadable spectra as comments.
    """
    body = request.get_json(silent=True) or {}
    usis = body.get("usis")
    if not isinstance(usis, list) or not all(isinstance(u, str) for u in usis):
        return _error(400, 'Body must be {"usis": [<USI>, ...]}')
    limit = current_app.config.get("SPECTRA_BATCH_LIMIT", DEFAULT_BATCH_LIMIT)
    if len(usis) > limit:
        return _error(400, f"At most {limit} USIs per request")
    output = request.args.get("format", "json")
    if output not in FORMATS:
        return _error(400, f"format must be one of {', '.join(FORMATS)}")
    result_type = _result_type("full")

    access = SpectrumAccess(g.identity)
    results = get_spectra(access, usis)
    if output == "json":
        return jsonify([_batch_item(access, requested, r, result_type) for requested, r in zip(usis, results, strict=True)])

    blocks = [_mgf_block(access, requested, r) for requested, r in zip(usis, results, strict=True)]
    return Response(
        stream_with_context(mgf(blocks)),
        mimetype="text/plain",
        headers={"Content-Disposition": 'attachment; filename="spectra.mgf"'},
    )


def _batch_item(access: SpectrumAccess, requested: str, result, result_type: str) -> dict:
    if isinstance(result, SpectrumFailure):
        code, message = error_status(result.error)
        return {"usi": requested, "status": "PEAK UNAVAILABLE", "error": {"code": code, "message": message}}
    return access.proxi(result, result_type, usi=requested)


def _mgf_block(access: SpectrumAccess, requested: str, result) -> str:
    if isinstance(result, SpectrumFailure):
        return failure_comment(requested, *error_status(result.error))
    model = instrument_model(result.run.header or {})
    return spectrum_mgf(
        requested,
        result.spectrum,
        access.provenance(result),
        instrument=model["name"] if model else None,
        scan=result.entry.scan,
    )


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
    access = SpectrumAccess(g.identity)
    result = get_spectrum(access, pid_value, index_type, value, file_key=key)
    # besides the PROXI fields, the position of the spectrum in the file
    return jsonify({**access.proxi(result, _result_type("full")), "index": result.spectrum["index"]})
