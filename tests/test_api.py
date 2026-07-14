import importlib
import json

from fastapi.testclient import TestClient


def test_notify_api_keeps_legacy_response_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDIR", str(tmp_path))
    main = importlib.import_module("notifyhub.main")
    main.store.save_config(
        {
            "app": {},
            "channels": [{"name": "test", "type": "webhook", "config": {"url": "http://127.0.0.1:9"}}],
            "routes": [
                {
                    "route_id": "r1",
                    "route_name": "Route",
                    "channel_name": ["test"],
                    "bind_template": ["movie", "series"],
                    "active": True,
                }
            ],
        }
    )
    main.store.templates_path.write_text(
        json.dumps(
            {
                "template": [
                    {"name": "movie", "type": "Emby.LibraryNewMovie", "title": "{{ title }}", "content": "movie"},
                    {"name": "series", "type": "Emby.LibraryNewSeries", "title": "{{ title }}", "content": "series"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with TestClient(main.app) as client:
        response = client.post("/api/service/notify", json={"route_id": "r1", "title": "t", "content": "c"})
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "errorCode": 0,
            "message": "通知已进入发送队列",
            "data": {"route_id": "r1", "channels": ["test"]},
        }
        response = client.post("/api/service/notify", json={})
        assert response.status_code == 400
        assert response.json()["errorCode"] == 1

        response = client.post(
            "/api/service/notify",
            content=json.dumps({"route_id": "r1", "title": "t", "content": "Uptime Kuma"}),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        response = client.get(
            "/api/service/notify",
            params={"route_id": "r1", "title": "t", "content": "legacy query"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        response = client.post(
            "/api/service/pve/notify/r1/message",
            json={"title": "Test notification", "message": "Proxmox VE test notification"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        for item, expected_id in (
            ({"Id": "movie/1", "Type": "Movie", "Name": "Film"}, "movie%2F1"),
            ({"Id": "episode/1", "SeriesId": "series/1", "Type": "Episode", "Name": "Episode"}, "series%2F1"),
        ):
            response = client.post(
                "/api/service/emby/notify/r1",
                params={"emby_url": "https://tv.example/"},
                json={"Event": "library.new", "Item": item},
            )
            assert response.status_code == 200
            with main.store.connect() as db:
                image = db.execute("SELECT push_img_url FROM outbox ORDER BY rowid DESC LIMIT 1").fetchone()[0]
            assert image == f"https://tv.example/emby/Items/{expected_id}/Images/Primary"
