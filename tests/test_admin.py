import importlib

from fastapi.testclient import TestClient

from notifyhub.store import Store, redact_secret_text


def test_redaction_and_masked_merge_preserve_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDIR", str(tmp_path))
    main = importlib.import_module("notifyhub.main")
    current = {
        "app": {"github_token": "github-secret"},
        "channels": [
            {"name": "second", "config": {"corpsecret": "two"}},
            {"name": "first", "config": {"corpsecret": "one", "server_url": "https://example.com"}},
            {"name": "hook", "type": "webhook", "config": {"url": "https://example.com/private-token"}},
        ],
    }
    safe = main._redact(current)
    assert safe["app"]["github_token"] == main.MASK
    assert safe["channels"][0]["config"]["corpsecret"] == main.MASK
    assert safe["channels"][2]["config"]["url"] == main.MASK
    safe["channels"] = [safe["channels"][1], safe["channels"][0], safe["channels"][2]]
    safe["channels"][0]["config"]["server_url"] = "https://new.example.com"
    merged = main._merge_masked(safe, current)
    assert merged["channels"][0]["name"] == "first"
    assert merged["channels"][0]["config"]["corpsecret"] == "one"
    assert merged["channels"][0]["config"]["server_url"] == "https://new.example.com"


def test_admin_login_masks_config_and_can_queue_channel_test(tmp_path, monkeypatch):
    monkeypatch.setenv("NH_USER", "admin")
    monkeypatch.setenv("NH_PASSWORD", "test-password")
    main = importlib.import_module("notifyhub.main")
    test_store = Store(tmp_path)
    test_store.save_config(
        {
            "app": {},
            "channels": [{"name": "test", "type": "webhook", "config": {"webhook_url": "http://127.0.0.1:9"}}],
            "routes": [{"route_id": "r1", "route_name": "Route", "channel_name": ["test"], "active": True}],
        }
    )
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)
    try:
        assert client.get("/").status_code == 200
        assert client.get("/api/admin/config").status_code == 401
        response = client.post("/api/admin/login", json={"username": "admin", "password": "test-password"})
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        config = client.get("/api/admin/config").json()
        assert config["channels"][0]["config"]["webhook_url"] == main.MASK
        response = client.post("/api/admin/channels/test/test", json={})
        assert response.status_code == 200
        assert test_store.delivery_status()[0]["status"] == "pending"
    finally:
        client.close()


def test_dashboard_stats_and_delivery_filter(tmp_path):
    store = Store(tmp_path)
    store.save_config(
        {
            "app": {},
            "channels": [{"name": "test", "type": "webhook", "config": {"url": "http://127.0.0.1:9"}}],
            "routes": [{"route_id": "r1", "route_name": "Route", "channel_name": ["test"], "active": True}],
        }
    )
    store.enqueue_router("r1", "title", "content")
    stats = store.dashboard_stats()
    assert stats["queue"] == {"pending": 1}
    assert store.delivery_status(status="pending")[0]["content"] == "content"
    assert store.delivery_status(status="failed") == []


def test_log_and_delivery_errors_hide_embedded_tokens():
    value = "POST https://api.telegram.org/bot123456:ABC/sendMessage?access_token=secret Authorization: Bearer private"
    safe = redact_secret_text(value)
    assert "123456:ABC" not in safe
    assert "access_token=secret" not in safe
    assert "Bearer private" not in safe
