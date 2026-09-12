import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "plugins"))
from baiyun_traffic import main


TZ = ZoneInfo("Asia/Shanghai")
VALUES = {"upload": 100, "download": 200, "total": 1000, "expire": 1893456000}


def test_parse_userinfo_requires_all_fields():
    assert main.parse_userinfo("upload=100; download=200; total=1000; expire=1893456000") == VALUES
    with pytest.raises(ValueError, match="expire"):
        main.parse_userinfo("upload=100; download=200; total=1000")


def test_collect_tracks_increment_without_counting_first_snapshot(tmp_path, monkeypatch):
    values = dict(VALUES)
    monkeypatch.setattr(main, "fetch_userinfo", lambda _url: dict(values))
    state = main.State(tmp_path / "state.json")
    config = {"subscription_token_url": "https://example.com/secret"}

    first = main.collect_once(config, state, datetime(2026, 9, 12, 8, tzinfo=TZ))
    assert first["todayUsed"] == 0
    values["download"] += 50
    second = main.collect_once(config, state, datetime(2026, 9, 12, 8, 30, tzinfo=TZ))
    assert second["todayUsed"] == 50
    assert second["remaining"] == 650


def test_report_uses_internal_route_and_external_image(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "fetch_userinfo", lambda _url: dict(VALUES))
    monkeypatch.setattr(main.server, "send_notify_by_router", lambda *args: calls.append(args))
    state = main.State(tmp_path / "state.json")
    state.save({"daily": {}, "last": None, "reportBaseline": {"used": 250, "at": "2026-09-11T09:00:00+08:00"}})
    image = "https://img.example.com/baiyun.png"
    config = {
        "subscription_token_url": "https://example.com/secret",
        "route_id": "route_baiyun",
        "image_url": image,
        "link_url": "",
        "reset_day": 12,
    }

    report = main.report_once(config, state, datetime(2026, 9, 12, 9, tzinfo=TZ))
    assert report["periodUsed"] == 50
    assert calls[0][0] == "route_baiyun"
    assert calls[0][3:] == (image, image)
    assert not any(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"} for path in Path(main.__file__).parent.iterdir())
