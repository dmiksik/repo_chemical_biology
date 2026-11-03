"""Create and publish dataset records from downloaded MassIVE datasets.

Usage: python import_records.py <repo url> <token file> <MSV> [<MSV> ...]

Metadata come from the MassIVE PROXI dataset (<MSV>.proxi.json) and the
MassIVE dataset list (<MSV>.row.json); files from $MASSIVE_DATA_DIR/<MSV>/
(see download.py), uploaded under their MassIVE path (e.g.
peak/Nicotiana_SPS_KOMT/x.mzML). The token is a personal access token of a
repository user. Records already imported ($MASSIVE_DATA_DIR/imported.json)
are skipped.
"""

import datetime
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("MASSIVE_DATA_DIR", ROOT / "data"))
STATE = DATA / "imported.json"
CONTEXT = ssl._create_unverified_context()  # local instance, self-signed certificate
NAT_PLANTS_DOI = "10.1038/s41477-019-0474-0"  # PubMed 31332312, publication of all these datasets


def request(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, context=CONTEXT, timeout=600) as response:
        text = response.read()
    return json.loads(text) if text else None


def terms(group):
    return {term["name"]: term.get("value") for term in group}


def person(name, affiliation):
    given, _, family = name.rpartition(" ")
    return {
        "person_or_org": {"type": "personal", "family_name": family, "given_name": given},
        "affiliations": [{"name": affiliation}] if affiliation else [],
    }


def metadata(dataset):
    proxi = json.loads((ROOT / f"{dataset}.proxi.json").read_text())
    row = json.loads((ROOT / f"{dataset}.row.json").read_text())["row_data"][0]
    contacts = [terms(c) for c in proxi["contacts"]]
    head = next(c for c in contacts if "lab head" in c)
    submitter = next(c for c in contacts if "dataset submitter" in c)

    species = [terms(s) for s in proxi["species"]]
    if len(species) == 1:
        taxon = {"id": f"NCBITaxon:{species[0]['taxonomy: NCBI TaxID']}"}
    else:  # one species field; several species of a genus
        names = [s["taxonomy: scientific name"] for s in species]
        taxon = {"title": {"en": ", ".join(names)}}

    created = datetime.datetime.fromtimestamp(int(row["createdMillis"]) / 1000, datetime.UTC).date()
    instrument = proxi["instruments"][0]["name"]
    description = (
        f"<p>{row['description']}</p>"
        f"<p>Imported from MassIVE {dataset} (https://massive.ucsd.edu/ProteoSAFe/QueryMSV?id={dataset}). "
        f"Instrument: {instrument}. Files are the original mzML files of the MassIVE dataset, "
        "under their MassIVE paths.</p>"
    )
    if len(species) > 1:
        description += f"<p>Species (NCBI Taxonomy): {', '.join(f'{s['taxonomy: scientific name']} ({s['taxonomy: NCBI TaxID']})' for s in species)}.</p>"

    return {
        "title": proxi["title"],
        "description": description,
        "publication_date": created.isoformat(),
        "resource_type": {"id": "c_ddb1"},
        "domain_type": {"id": "topic_3172"},  # Metabolomics
        "analysis_type": "plant_biology",
        "plant_biology": {"species": taxon},
        "creators": [person(head["contact name"], head.get("contact affiliation"))],
        "contributors": [
            {**person(submitter["contact name"], submitter.get("contact affiliation")), "role": {"id": "DataCollector"}}
        ],
        "principal_investigator_email": head["contact email"],
        "sample_preparer_email": submitter["contact email"],
        "subjects": [{"subject": k["value"]} for k in proxi["keywords"]],
        "identifiers": [{"identifier": dataset, "scheme": "massive"}],
        "related_identifiers": [
            {
                "identifier": NAT_PLANTS_DOI,
                "scheme": "doi",
                "relation_type": {"id": "IsSupplementTo"},
                "resource_type": {"id": "c_2df8fbb1"},
            }
        ],
    }


def files(dataset):
    base = DATA / dataset
    return sorted((str(p.relative_to(base)), p) for p in base.rglob("*.mzML"))


def import_dataset(api, token, dataset):
    draft = request("POST", f"{api}/api/dataset", token, {"metadata": metadata(dataset), "files": {"enabled": True}})
    record_id = draft["id"]
    print(f"{dataset}: draft {record_id}", flush=True)
    entries = files(dataset)
    init = request("POST", draft["links"]["files"], token, [{"key": key} for key, _ in entries])
    links = {entry["key"]: entry["links"] for entry in init["entries"]}
    for key, path in entries:
        with open(path, "rb") as f:
            req = urllib.request.Request(links[key]["content"], data=f, method="PUT")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("Content-Length", str(path.stat().st_size))
            urllib.request.urlopen(req, context=CONTEXT, timeout=600).read()
        request("POST", links[key]["commit"], token)
        print(f"  {key}", flush=True)
    record = request("POST", draft["links"]["publish"], token)
    print(f"{dataset}: published {record['id']} {record['links']['self_html']}", flush=True)
    return record["id"]


if __name__ == "__main__":
    api, token_file, *datasets = sys.argv[1:]
    token = Path(token_file).read_text().strip()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    for dataset in datasets:
        if dataset in state:
            print(f"{dataset}: already imported as {state[dataset]}")
            continue
        state[dataset] = import_dataset(api.rstrip("/"), token, dataset)
        STATE.write_text(json.dumps(state, indent=2))
