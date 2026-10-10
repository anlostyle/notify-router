import json
import os

import pytest

from notifyhub import worker as worker_module
from notifyhub.channels import telegram_html
from notifyhub.plugin_supervisor import PluginSupervisor, _strip_session_cookie
from notifyhub.store import Store
from notifyhub.worker import DeliveryWorker


def config():
    return {
        "app": {"app_name": "Notify"},
        "channels": [{"name": "hook", "type": "webhook", "config": {"webhook_url": "http://127.0.0.1:9"}}],
        "routes": [{"route_id": "r1", "route_name": "Route", "channel_name": ["hook"], "active": True}],
    }


def delivery(store):
    with store.connect() as db:
        return dict(db.execute("SELECT * FROM deliveries ORDER BY id DESC LIMIT 1").fetchone())


def test_manual_retry_restarts_the_retry_cycle(tmp_path):
    store = Store(tmp_path)
    store.save_config(config())
    store.enqueue_router("r1", "title", "content")
    for _ in range(5):
        with store.connect() as db:
            db.execute("UPDATE deliveries SET next_attempt_at=0")
        store.fail_delivery(store.claim_delivery(), RuntimeError("boom"))
    assert delivery(store)["status"] == "failed"
    woken = []
    store.on_enqueue = lambda: woken.append(True)
    assert store.retry_failed(delivery(store)["id"])
    row = delivery(store)
    assert row["status"] == "retry" and row["attempts"] == 0
    assert woken


def test_enqueue_wakes_the_worker(tmp_path):
    store = Store(tmp_path)
    store.save_config(config())
    woken = []
    store.on_enqueue = lambda: woken.append(True)
    store.enqueue_router("r1", "title", "content")
    assert woken == [True]


def test_bookkeeping_error_after_send_does_not_resend(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save_config(config())
    store.enqueue_router("r1", "title", "content")
    sent = []
    monkeypatch.setattr(worker_module, "send", lambda channel, item: sent.append(item["delivery_id"]))
    monkeypatch.setattr(worker_module.time, "sleep", lambda _: None)
    calls = {"count": 0}
    original = store.complete_delivery

    def flaky(item):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("database is locked")
        return original(item)

    monkeypatch.setattr(store, "complete_delivery", flaky)
    DeliveryWorker(store)._deliver(store.claim_delivery())
    assert len(sent) == 1
    assert delivery(store)["status"] == "sent"


def test_worker_survives_claim_errors(tmp_path, monkeypatch):
    store = Store(tmp_path)
    worker = DeliveryWorker(store)
    calls = {"count": 0}

    def claim():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("database is locked")
        worker._stop.set()
        return None

    monkeypatch.setattr(store, "claim_delivery", claim)
    monkeypatch.setattr(worker, "_idle", lambda seconds: None)
    worker._run()
    assert calls["count"] == 2


def test_worker_health_reports_stopped_thread(tmp_path):
    worker = DeliveryWorker(Store(tmp_path))
    assert worker.health()["healthy"] is False


def test_telegram_html_escapes_text_but_keeps_supported_tags():
    value = telegram_html('a < b & c <b>粗</b> <script>x</script> <a href="https://x.y/?a=1">l</a>')
    assert value == 'a &lt; b &amp; c <b>粗</b> &lt;script&gt;x&lt;/script&gt; <a href="https://x.y/?a=1">l</a>'


def test_session_cookie_is_not_forwarded_to_plugins():
    assert _strip_session_cookie("a=1; notify_session=secret; b=2") == "a=1; b=2"
    assert _strip_session_cookie("notify_session=secret") == ""


def test_broken_manifest_does_not_block_other_plugins(tmp_path, monkeypatch):
    store = Store(tmp_path)
    broken = store.plugins_dir / "broken"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    good = store.plugins_dir / "good"
    good.mkdir()
    (good / "manifest.json").write_text(json.dumps({"id": "good"}), encoding="utf-8")
    supervisor = PluginSupervisor(store)
    loaded = []
    monkeypatch.setattr(supervisor, "reload", lambda plugin_id: loaded.append(plugin_id))
    supervisor.start_all()
    assert loaded == ["good"]
    assert any("manifest.json" in item["message"] for item in supervisor.logs("broken"))


def test_plugin_worker_environment_excludes_console_secrets(tmp_path, monkeypatch):
    store = Store(tmp_path)
    directory = store.plugins_dir / "demo"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({"id": "demo"}), encoding="utf-8")
    for key in ("NH_PASSWORD", "SESSION_SECRET", "NOTIFY_API_TOKEN"):
        monkeypatch.setenv(key, "secret-value")
    captured = {}

    class Stop(Exception):
        pass

    def popen(*args, **kwargs):
        captured.update(kwargs["env"])
        raise Stop

    monkeypatch.setattr("notifyhub.plugin_supervisor.subprocess.Popen", popen)
    with pytest.raises(Stop):
        PluginSupervisor(store)._spawn("demo")
    assert not {"NH_PASSWORD", "SESSION_SECRET", "NOTIFY_API_TOKEN"} & set(captured)
    assert captured.get("PATH") == os.environ.get("PATH")


def test_index_versions_static_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from notifyhub import __version__
    from notifyhub.main import app

    html = TestClient(app).get("/").text
    assert f'/static/app.css?v={__version__}"' in html
    assert f'/static/app.js?v={__version__}"' in html


def plugin_proxy_client(tmp_path, monkeypatch, manifest):
    import base64
    import importlib

    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient

    monkeypatch.setenv("WORKDIR", str(tmp_path))
    monkeypatch.setenv("NH_USER", "admin")
    monkeypatch.setenv("NH_PASSWORD", "test-password")
    main = importlib.import_module("notifyhub.main")
    monkeypatch.setattr(main, "store", Store(tmp_path))
    monkeypatch.setattr(main.plugin_supervisor, "manifest_for", lambda plugin_id: manifest)

    async def proxy(plugin_id, path, request):
        return PlainTextResponse(f"{plugin_id}:{path}")

    monkeypatch.setattr(main.plugin_supervisor, "proxy", proxy)
    basic = "Basic " + base64.b64encode(b"admin:test-password").decode()
    return TestClient(main.app), basic


def test_plugin_proxy_requires_login_except_wecom_callback(tmp_path, monkeypatch):
    client, basic = plugin_proxy_client(tmp_path, monkeypatch, {"id": "reminder"})
    assert client.get("/api/plugins/reminder/reminder").status_code == 401
    assert client.delete("/api/plugins/reminder/reminder/1").status_code == 401
    assert client.post("/api/plugins/reminder/chat").text == "reminder:chat"
    assert client.get("/api/plugins/reminder/reminder", headers={"Authorization": basic}).status_code == 200
    page = client.get("/api/plugins/reminder/frontend/index.html", headers={"Accept": "text/html"}, follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/#plugins"


def test_plugin_proxy_accepts_console_session(tmp_path, monkeypatch):
    client, _ = plugin_proxy_client(tmp_path, monkeypatch, {"id": "reminder"})
    assert client.post("/api/admin/login", json={"username": "admin", "password": "test-password"}).status_code == 200
    assert client.get("/api/plugins/reminder/reminder").status_code == 200


def test_plugin_manifest_public_paths_override_default(tmp_path, monkeypatch):
    client, _ = plugin_proxy_client(tmp_path, monkeypatch, {"id": "flow", "public_paths": ["chat", "shortcut", "hooks/*"]})
    assert client.get("/api/plugins/flow/shortcut?url=x").status_code == 200
    assert client.post("/api/plugins/flow/hooks/github").status_code == 200
    assert client.get("/api/plugins/flow/settings").status_code == 401
    client, _ = plugin_proxy_client(tmp_path, monkeypatch, {"id": "quiet", "public_paths": []})
    assert client.post("/api/plugins/quiet/chat").status_code == 401
