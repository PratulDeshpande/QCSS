from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from qcss_dashboard.app import create_app
from qcss_dashboard.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(workspace=tmp_path, lab_target=None, admin_target=None, embedded_chassis=False)


@pytest.fixture
def client(settings) -> TestClient:
    return TestClient(base_url="http://127.0.0.1", app=create_app(settings))


