import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from plugins.wx_flowlink_save.api.flowlink_api import FlowLinkApi
from plugins.wx_flowlink_save.utils import config


def test_flowlink_shortcut_posts_expected_query(monkeypatch):
    monkeypatch.setattr(
        config,
        "_cache",
        {"base_url": "http://flowlink", "name": "115sub", "token": "secret"},
    )
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"success": True, "ok": True, "receive_title": "demo"}

    def fake_get(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("plugins.wx_flowlink_save.api.flowlink_api.httpx.get", fake_get)
    result = FlowLinkApi().shortcut("https://115.com/s/abc123")
    assert result["success"] is True
    assert seen["url"] == "http://flowlink/api/transfer/shortcut"
    assert seen["params"] == {
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
