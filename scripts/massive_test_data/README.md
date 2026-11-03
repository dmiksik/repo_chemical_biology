# Test data from MassIVE

Six public MassIVE datasets of *The biosynthetic origin of psychoactive
kavalactones in kava* (Nature Plants 2019, doi:10.1038/s41477-019-0474-0):
MSV000083272, MSV000083274, MSV000083275, MSV000083276, MSV000083277,
MSV000087906 - 169 mzML files, 9.85 GB, 1.24 million spectra.

```bash
export MASSIVE_DATA_DIR=/path/with/10GB/free   # default: ./data
python download.py MSV000083272 MSV000083274 MSV000083275 MSV000083276 MSV000083277 MSV000087906
python import_records.py https://127.0.0.1:5000 token.txt MSV000083272 ...
```

- `<MSV>.csv`: file list with sizes from the GNPS dataset cache; `<MSV>.proxi.json`
  and `<MSV>.row.json`: dataset metadata from MassIVE (PROXI and dataset list).
- Only the original files (`peak/`, `raw/`) are downloaded; `ccms_peak/` are GNPS copies.
- MassIVE rate-limits HTTPS downloads (HTTP 429), so files are downloaded over
  FTP with TLS (`curl --ssl-reqd`).
- `import_records.py` creates and publishes one record per dataset; files keep
  their MassIVE path as key, so USIs are the same as on MassIVE.
