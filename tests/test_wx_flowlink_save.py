import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from plugins.wx_flowlink_save.api.flowlink_api import FlowLinkApi
from plugins.wx_flowlink_save.utils import config


def test_flowlink_shortcut_saves_then_scans_named_task(monkeypatch):
    monkeypatch.setattr(
        config,
        "_cache",
        {"base_url": "http://flowlink", "name": "115sub", "token": "secret"},
    )
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    seen = {}

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        seen.setdefault("get", []).append({"url": url, **kwargs})
        return Response({"success": True, "ok": True, "message": "转存成功"})

    def fake_post(url, **kwargs):
        seen["post"] = {"url": url, **kwargs}
        return Response({"success": True, "ok": True, "queued": 1})

    monkeypatch.setattr("plugins.wx_flowlink_save.api.flowlink_api.httpx.get", fake_get)
    monkeypatch.setattr("plugins.wx_flowlink_save.api.flowlink_api.httpx.post", fake_post)
    result = FlowLinkApi().shortcut("https://115.com/s/abc123")
    assert result["success"] is True
    assert seen["get"][0]["url"] == "http://flowlink/api/transfer/shortcut"
    assert seen["get"][0]["params"] == {
        "token": "secret",
        "url": "https://115.com/s/abc123",
    }
    assert seen["post"]["url"] == "http://flowlink/api/transfer/transfer/scan"
    assert seen["post"]["json"] == {"task_name": "115sub"}
    assert seen["post"]["headers"]["X-Api-Token"] == "secret"


def test_flowlink_shortcut_falls_back_for_legacy_flowlink(monkeypatch):
    monkeypatch.setattr(
        config,
        "_cache",
        {"base_url": "http://flowlink", "name": "115sub", "token": "secret"},
    )
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if len(calls) == 1:
            return Response({"success": False, "ok": False, "message": "必须指定对应的转存任务配置"})
        return Response({"success": True, "ok": True, "message": "转存成功"})

    monkeypatch.setattr("plugins.wx_flowlink_save.api.flowlink_api.httpx.get", fake_get)
    monkeypatch.setattr(
        "plugins.wx_flowlink_save.api.flowlink_api.httpx.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy path must not scan")),
    )
    result = FlowLinkApi().shortcut("https://115.com/s/abc123")
    assert result["success"] is True
    assert calls[1]["params"] == {
        "name": "115sub",
        "token": "secret",
        "url": "https://115.com/s/abc123",
    }


def test_legacy_callback_is_not_used():
    manifest = __import__("json").loads(
        (Path(__file__).parents[1] / "plugins/wx_flowlink_save/manifest.json").read_text()
    )
    assert "shortcut" in manifest["documentation"]
    assert {field["fieldName"] for field in manifest["configField"]} == {"base_url", "name", "token"}
