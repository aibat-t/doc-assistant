"""Проверка, что docker compose поднял всю инфраструктуру. Запуск: make up && make test-int"""

import pytest
from fastapi.testclient import TestClient

from docs_assistant.api.main import app

pytestmark = pytest.mark.integration


def test_all_dependencies_ready():
    resp = TestClient(app).get("/health/ready")
    assert resp.status_code == 200, resp.json()
    assert set(resp.json()["checks"].values()) == {"ok"}
