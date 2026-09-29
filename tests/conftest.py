"""Test setup: every test runs against a temporary data directory and never touches the
network (requests.Session.request is replaced by a stub that fails loudly)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOCK4_DATA_DIR", str(tmp_path / "data"))
    from block4_pipeline import paths
    monkeypatch.setattr(paths, "REFINEMENTS_FILE", tmp_path / "refinements.yaml")  # never the real one
    yield tmp_path / "data"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(self, method, url, *args, **kwargs):
        raise AssertionError("network access attempted in tests: %s %s" % (method, url))
    monkeypatch.setattr(requests.Session, "request", _blocked)


@pytest.fixture
def fixtures():
    return FIXTURES
