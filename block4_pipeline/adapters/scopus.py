"""Scopus: official API path, used only when an institutional API entitlement is confirmed
(sources.yaml access_mode: api) and SCOPUS_API_KEY is set. Not implemented until then;
the manual-export importer handles Scopus CSV/RIS/BibTeX exports in the meantime.
"""
from __future__ import annotations

from .base import BaseAdapter


class ScopusAdapter(BaseAdapter):
    name = "scopus"

    def supports_api(self) -> bool:
        return False

    def describe_request(self, exact_query: str, **kwargs):
        raise NotImplementedError(
            "Scopus API path not implemented: API entitlement is ACCESS_TO_CONFIRM. "
            "Run the query in the Scopus interface, export CSV/RIS, then use `import-manual`."
        )
