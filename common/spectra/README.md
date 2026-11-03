# Spectra: access to individual mass spectra

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
| `GET /api/proxi/v0.1/datasets?pageSize=&pageNumber=&accession=&species=&search=` | PROXI datasets |
| `GET /api/proxi/v0.1/datasets/<accession or record id>` | PROXI dataset |
| `GET /api/dataset/<id>/files/<key>/spectra?ms_level=&page=&size=` | list of spectra of a file (summaries and USIs) |
| `GET /api/dataset/<id>/files/<key>/spectra/<scan\|index\|nativeId>/<value>` | one spectrum (PROXI fields and `index`) |

Access follows the permissions of the record files: a spectrum can be read by
whoever can download the file it comes from (embargo, restricted files and share
links apply). Errors are PROXI `{code, message}` objects; 409 means the file is
not indexed (yet), with `indexing_status` `PENDING`, `CONVERTING`, `FAILED` or
`UNSUPPORTED`.

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
   of each spectrum (MS level, RT, precursor m/z, charge) into `spectra_index`.
4. A spectrum is read by a single ranged GET of its bytes from S3, parsed and
   cached (Redis).

Supported: indexed mzML with uncompressed or zlib binary arrays. Not indexed mzML,
`.mzML.gz` and MS-Numpress get the status `UNSUPPORTED`.

## Configuration

| Variable | Default | |
|---|---|---|
| `SPECTRA_RAW_CONVERTER` | ThermoRawFileParser 1.4.5 in Docker | command converting a raw file; placeholders `{input_dir}`, `{input}`, `{output_dir}`, `{uid}`, `{gid}`; must write `<name>.mzML` to `{output_dir}` |
| `SPECTRA_CONVERSION_TIMEOUT` | 3600 | seconds |
| `SPECTRA_CACHE_TIMEOUT` | 86400 | seconds a parsed spectrum stays in the cache |

With the default converter, the Celery worker needs access to Docker
(`quay.io/biocontainers/thermorawfileparser:1.4.5--h05cac1d_1`).

## CLI

```bash
invenio spectra index <record ids> | --all [--sync]   # register and index files of published records
invenio spectra status <record id>                    # indexing status of the files
invenio spectra reset <record id>                     # remove the index (and converted files)
```

`index` is needed for records published before this module was deployed.
