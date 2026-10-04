"""S0 support: look up in OpenAlex, by DOI, the documents that were not retrieved through OpenAlex,
to obtain citation counts, topic fields (subject labels), type and venue ISSNs.

    python3 block4_pipeline/tools/s0_openalex_lookup.py --live

Answers are saved unchanged under data/raw/openalex_s0_lookup/<timestamp>/ (one file per batch of
50 DOIs). Nothing is changed in the corpus; the S0 filter reads these files.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from block4_pipeline import secrets, storage  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SELECT = "id,doi,title,publication_year,type,is_paratext,cited_by_count,topics,primary_location,locations"


def main() -> None:
    if "--live" not in sys.argv:
        raise SystemExit("needs --live (network calls)")
    docs = [json.loads(l) for l in open(ROOT / "data" / "normalized" / "documents.jsonl")]
    dois = sorted({d["doi"].lower() for d in docs if not d.get("after_cutoff") and not d.get("openalex_id") and d.get("doi")})
    out = ROOT / "data" / "raw" / "openalex_s0_lookup" / storage.utc_stamp()
    out.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": "Bearer %s" % secrets.get_secret("OPENALEX_API_KEY")}
    mailto = secrets.get_mailto()
    found = 0
    for n, i in enumerate(range(0, len(dois), 50), 1):
        batch = dois[i:i + 50]
        params = {"filter": "doi:" + "|".join(batch), "per_page": 50, "select": SELECT}
        if mailto:
            params["mailto"] = mailto
        for attempt in range(3):
            r = requests.get("https://api.openalex.org/works", params=params, headers=headers, timeout=60)
            if r.status_code == 200:
                break
            time.sleep(3 * (attempt + 1))
        r.raise_for_status()
        data = r.json()
        found += len(data.get("results", []))
        (out / ("batch_%03d.json" % n)).write_text(json.dumps({"dois": batch, "response": data}), encoding="utf-8")
        time.sleep(0.15)
    print(json.dumps({"dois": len(dois), "found": found, "dir": str(out)}))


if __name__ == "__main__":
    main()
