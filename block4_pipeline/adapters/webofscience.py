"""Web of Science: official API path, used only when an entitlement (WOS_API_KEY) is
confirmed. Not implemented until then; use the tab-delimited or RIS export and `import-manual`.
"""
from __future__ import annotations

from .base import BaseAdapter


class WebOfScienceAdapter(BaseAdapter):
    name = "wos"

    def supports_api(self) -> bool:
        return False

    def describe_request(self, exact_query: str, **kwargs):
        raise NotImplementedError(
            "Web of Science API path not implemented: API entitlement is ACCESS_TO_CONFIRM. "
            "Export from the WoS interface and use `import-manual`."
        )
