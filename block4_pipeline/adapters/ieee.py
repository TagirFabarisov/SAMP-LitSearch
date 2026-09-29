"""IEEE Xplore: official API path, used only when an entitlement (IEEE_API_KEY) is
confirmed. Not implemented until then; use the IEEE CSV export and `import-manual`.
"""
from __future__ import annotations

from .base import BaseAdapter


class IeeeAdapter(BaseAdapter):
    name = "ieee"

    def supports_api(self) -> bool:
        return False

    def describe_request(self, exact_query: str, **kwargs):
        raise NotImplementedError(
            "IEEE Xplore API path not implemented: API entitlement is ACCESS_TO_CONFIRM. "
            "Export CSV from IEEE Xplore and use `import-manual`."
        )
