"""`scopus-check --live`: one request to see whether the Scopus subscription applies from
the current network. Sends `TITLE-ABS-KEY("resource dependence")` with view=COMPLETE and
count=1; the answer is either a record with an abstract (entitled) or HTTP 401/403 (not
entitled from here: use the Uni.lu network or VPN). The response is saved under
data/logs/scopus_check_<UTC>.json with the key redacted. Nothing else is retrieved."""
from __future__ import annotations

from typing import Any, Dict

from .. import config_loader as cl
from .. import paths, secrets, storage
from ..adapters.scopus import ScopusAdapter


def live_probe() -> Dict[str, Any]:
    protocol = cl.load_protocol()
    scfg = cl.load_sources()["sources"]["scopus"]
    if not secrets.get_secret("SCOPUS_API_KEY"):
        return {"ok": False, "reason": "SCOPUS_API_KEY is not set (environment or .env)"}
    adapter = ScopusAdapter(protocol, scfg)
    result = adapter.entitlement_probe()
    result["recorded_at"] = storage.utc_now()
    path = paths.logs_dir() / ("scopus_check_%s.json" % storage.utc_stamp())
    storage.write_json(path, secrets.redact_obj(result))
    entitled = result.get("http_status") == 200 and result.get("abstract_present") is True
    return {"ok": entitled, "http_status": result.get("http_status"), "total": result.get("total"),
            "abstract_present": result.get("abstract_present"), "authors_present": result.get("authors_present"),
            "saved_to": str(path),
            "next": ("set scopus access_mode: api in sources.yaml (deviation-log entry: implementation choice per protocol section 5)"
                     if entitled else "not entitled from this network: retry on campus or VPN, or keep manual export")}
