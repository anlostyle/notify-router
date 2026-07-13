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
            "routes": [{"route_id": "r1", "route_name": "Route", "channel_name": ["test"], "active": True}],
        }
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
