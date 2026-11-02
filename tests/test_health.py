from fastapi.testclient import TestClient

from docs_assistant.api.main import app

client = TestClient(app)


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_reports_each_dependency(monkeypatch):
    from docs_assistant.api import health

    async def ok(_url):
        return None

    async def broken(_url):
        raise ConnectionError("нет соединения")

    monkeypatch.setattr(health, "_check_postgres", ok)
    monkeypatch.setattr(health, "_check_rabbitmq", broken)
    monkeypatch.setattr(health, "_check_redis", ok)

    resp = client.get("/health/ready")
    body = resp.json()
    assert resp.status_code == 503
    assert body["status"] == "degraded"
    assert body["checks"]["postgres"] == "ok"
    assert body["checks"]["rabbitmq"].startswith("error: ConnectionError")
