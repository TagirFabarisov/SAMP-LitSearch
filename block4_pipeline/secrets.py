"""Credentials come from the environment (or a local .env file) only, and are redacted
from everything the pipeline writes.

Precedence: process environment, then a `.env` file in the repository root (never
committed). Optionally the OS keyring, if the `keyring` package is installed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

KEY_VARS = ("OPENALEX_API_KEY", "SCOPUS_API_KEY", "WOS_API_KEY", "IEEE_API_KEY")
REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_secret(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value:
        return value
    value = _load_dotenv(REPO_ROOT / ".env").get(name)
    if value:
        return value
    try:  # optional OS keyring
        import keyring  # type: ignore

        value = keyring.get_password("block4_pipeline", name)
        if value:
            return value
    except Exception:
        pass
    return None


def get_mailto() -> Optional[str]:
    return get_secret("OPENALEX_MAILTO")


# --- redaction -----------------------------------------------------------------

_PARAM_RE = re.compile(r"(?i)((?:api[_-]?key|apikey|token|access_token|key)=)[^&\s\"']+")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")


def redact_text(text: str) -> str:
    """Remove every known secret value and any key=... / Bearer ... pattern from text."""
    out = text
    for var in KEY_VARS:
        val = get_secret(var)
        if val and len(val) >= 6:
            out = out.replace(val, "<REDACTED>")
    out = _PARAM_RE.sub(r"\1<REDACTED>", out)
    out = _BEARER_RE.sub(r"\1<REDACTED>", out)
    return out


def redact_obj(obj: Any) -> Any:
    """Deep-copy an object (dict/list/str) with secrets redacted; other types pass through."""
    if isinstance(obj, dict):
        return {
            k: ("<REDACTED>" if _is_secret_key(k) else redact_obj(v)) for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def _is_secret_key(key: Any) -> bool:
    k = str(key).lower().replace("-", "_")
    return k in {"api_key", "apikey", "authorization", "token", "access_token", "x_api_key"}
