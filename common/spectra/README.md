# Spectra: access to individual mass spectra

Overview for colleagues (in Czech, with an architecture diagram): [docs/spectra-api.md](../../docs/spectra-api.md).

Individual spectra of the mzML and Thermo `.raw` files of published `dataset`
records can be read one by one, addressed by a
[Universal Spectrum Identifier](https://www.psidev.info/usi) (USI) or by
record, file and scan, in the [PROXI](https://github.com/HUPO-PSI/proxi-schemas)
format.

## USI

```
mzspec:<collection>:<msRun>:<scan|index|nativeId>:<value>[:<interpretation>]
```

- **collection**: the ProteomeXchange / MassIVE accession of the dataset
  (`metadata.identifiers` with the scheme `proteomexchange` or `massive`),
  otherwise the record id. The record id is not a registered USI collection
  identifier, so such USIs work only in this repository.
- **msRun**: the file name without the `.mzML` / `.raw` extension. A path and an
  extension are accepted too (`peak/.../run.mzML`, as MassIVE uses them).
- **index**: `scan` (scan number), `index` (0-based position in the file) or
  `nativeId` (values of the mzML nativeID joined by commas).

## API

| Endpoint | |
|---|---|
| `GET /api/proxi/v0.1/spectra?usi=…&resultType=compact\|full` | PROXI spectrum; or `accession`, `msRun`, `scan` instead of `usi` |
| `POST /api/proxi/v0.1/spectra?resultType=compact\|full&format=json\|mgf` | spectra of a list of USIs, body `{"usis": […]}` (not part of PROXI 0.1) |
| `GET /api/proxi/v0.1/datasets?pageSize=&pageNumber=&accession=&species=&search=` | PROXI datasets |
| `GET /api/proxi/v0.1/datasets/<accession or record id>` | PROXI dataset |
| `GET /api/dataset/<id>/files/<key>/spectra?ms_level=&page=&size=` | list of spectra of a file (summaries and USIs) |
| `GET /api/dataset/<id>/files/<key>/spectra/<scan\|index\|nativeId>/<value>` | one spectrum (PROXI fields and `index`) |

Access follows the permissions of the record files: a spectrum can be read by
whoever can download the file it comes from (embargo, restricted files and share
links apply). Errors are PROXI `{code, message}` objects; 409 means the file is
not indexed (yet), with `indexing_status` `PENDING`, `CONVERTING`, `FAILED` or
`UNSUPPORTED`.

A `full` spectrum has, besides the spectrum's own attributes, the instrument and
software of its file (PSI-MS terms from the mzML header) and a `provenance`
object (not part of PROXI): the dataset (accession, DOI, URL, creators, organism,
licenses, citation), the file (key, URL, checksum, converted from raw), and the
run (acquisition start time, source raw file with its SHA-1, data processing).

### Batch download

`POST /api/proxi/v0.1/spectra` returns the spectra of up to `SPECTRA_BATCH_LIMIT`
USIs, e.g. spectra found similar in an external tool:

```bash
curl -X POST -H 'Content-Type: application/json' \
  'https://<repo>/api/proxi/v0.1/spectra?format=mgf' \
  -d '{"usis": ["mzspec:MSV000083272:peak/20170731_WTcol:scan:3", "..."]}'
```

- `format=json` (default): a list of PROXI spectra in the order of the USIs
  (`resultType=full` by default). A spectrum that cannot be read (invalid USI,
  not found, no access, not indexed) has the status `PEAK UNAVAILABLE` and
  `error: {code, message}`; the other spectra are returned.
- `format=mgf`: MGF with the Mascot keys (`TITLE`=USI, `PEPMASS`, `CHARGE`,
  `RTINSECONDS`), the keys of GNPS libraries (`MSLEVEL`, `SCANS`, `IONMODE`,
  `SOURCE_INSTRUMENT`, `ORGANISM`, `PI`, `DATACOLLECTOR`, `FILENAME`) and `USI`,
  `DATASET`, `COLLISION_ENERGY`, `LICENSE`, `CITATION`. Spectra that cannot be
  read are listed as `#` comments. Readable by pyteomics and matchms.

Records, permissions and files are looked up once per request; spectra not in
the cache are read from S3 by concurrent ranged GETs.

The record detail page previews mzML and raw files: list of spectra, spectrum
plot, "Copy USI". `?spectrum=scan:N` on the record page selects a spectrum.

## How it works

1. On publish (`SpectraIndexComponent`), each mzML and Thermo raw file is
   registered as a run (`spectra_run`). A raw file with an mzML of the same run
   name is not converted.
2. A Celery task converts raw files to indexed mzML (`converter.py`), stored as a
   file instance in the default location, not in the record or media files - it
   is reachable only through this API, which checks access to the raw file.
3. A Celery task reads the byte offsets from the mzML `<indexList>` and a summary
   of each spectrum (MS level, RT, precursor m/z, charge) into `spectra_index`,
   and the mzML header (instrument, software, source files) into `spectra_run`.
4. A spectrum is read by a single ranged GET of its bytes from S3, parsed and
   cached (Redis).

Supported: indexed mzML with uncompressed or zlib binary arrays. Not indexed mzML,
`.mzML.gz` and MS-Numpress get the status `UNSUPPORTED`.

## Configuration

| Variable | Default | |
|---|---|---|
| `SPECTRA_RAW_CONVERTER` | ThermoRawFileParser 1.4.5 in Docker | command converting a raw file; placeholders `{input_dir}`, `{input}`, `{output_dir}`, `{uid}`, `{gid}`; must write `<name>.mzML` to `{output_dir}` |
| `SPECTRA_CONVERSION_TIMEOUT` | 3600 | seconds |
| `SPECTRA_CACHE_TIMEOUT` | 86400 | seconds a parsed spectrum (and record citation metadata) stays in the cache |
| `SPECTRA_BATCH_LIMIT` | 1000 | maximum number of USIs in one batch request |

With the default converter, the Celery worker needs access to Docker
(`quay.io/biocontainers/thermorawfileparser:1.4.5--h05cac1d_1`).

## CLI

```bash
invenio spectra index <record ids> | --all [--sync]   # register and index files of published records
invenio spectra status <record id>                    # indexing status of the files
invenio spectra reset <record id>                     # remove the index (and converted files)
```

`index` is needed for records published before this module was deployed; it
also reads the mzML header of files indexed before headers were stored.
