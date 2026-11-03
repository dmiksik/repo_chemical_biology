"""Download the original mzML files of MassIVE datasets listed in <MSV>.csv.

The csv files come from the GNPS dataset cache
(https://datasetcache.gnps2.org/datasette/database/filename.csv?dataset__exact=<MSV>).
Only original files (peak/, raw/) are downloaded; ccms_peak/ are GNPS copies.

Usage: python download.py <MSV> [<MSV> ...]
Files go to $MASSIVE_DATA_DIR (default: ./data, not in git), under their MassIVE path.
"""

import csv
import json
import os
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("MASSIVE_DATA_DIR", ROOT / "data"))
# The HTTPS download of MassIVE rate-limits (429); FTP requires TLS.
FTP_TERM = "MS:1002852"


def ftp_location(dataset):
    data = json.loads((ROOT / f"{dataset}.proxi.json").read_text())
    url = next(link["value"] for link in data["datasetLink"] if link["accession"] == FTP_TERM)
    return url.replace("ftp://massive.ucsd.edu/", "ftp://massive-ftp.ucsd.edu/")


def files(dataset):
    with open(ROOT / f"{dataset}.csv") as f:
        for row in csv.DictReader(f):
            if row["filepath"].split("/")[0] in ("peak", "raw") and row["filepath"].lower().endswith(".mzml"):
                yield dataset, row["filepath"], int(row["size"])


def download(item):
    dataset, path, size = item
    target = DATA / dataset / path
    if target.exists() and target.stat().st_size == size:
        return f"skip {dataset}/{path}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    url = f"{ftp_location(dataset)}/{urllib.parse.quote(path)}"
    for attempt in range(3):
        result = subprocess.run(
            ["curl", "-sS", "--ssl-reqd", "--retry", "3", "-o", str(partial), url], capture_output=True, text=True
        )
        if result.returncode == 0 and partial.stat().st_size == size:
            os.replace(partial, target)
            return f"ok {dataset}/{path}"
        print(f"retry {dataset}/{path}: {result.stderr.strip()}", flush=True)
    return f"FAILED {dataset}/{path}"


if __name__ == "__main__":
    items = [item for dataset in sys.argv[1:] for item in files(dataset)]
    print(f"{len(items)} files, {sum(i[2] for i in items) / 1e9:.2f} GB", flush=True)
    with ThreadPoolExecutor(3) as pool:
        for result in pool.map(download, items):
            print(result, flush=True)
