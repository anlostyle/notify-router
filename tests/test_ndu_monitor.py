import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "plugins"))
from ndu_monitor import main


def test_ndu_monitor_baselines_then_detects_changes(tmp_path, monkeypatch):
    calls = []
    docker_digest = {"value": "sha256:old"}
    release_id = {"value": 1}

    def fake_get(url, headers=None):
        if "hub.docker.com" in url:
            return {
                "digest": docker_digest["value"],
                "tag_last_pushed": "2026-01-01T00:00:00Z",
                "images": [{"os": "linux", "architecture": "amd64", "digest": docker_digest["value"]}],
            }
        return [
            {
                "id": release_id["value"],
                "name": f"v{release_id['value']}",
                "tag_name": f"v{release_id['value']}",
                "published_at": "2026-01-01T00:00:00Z",
                "body": "log",
                "html_url": "https://github.com/demo/repo/releases/tag/v1",
            }
        ]

    monkeypatch.setattr(main, "client_get", fake_get)
    monkeypatch.setattr(main.server, "send_notify_by_router", lambda *args: calls.append(args))
    state = main.State(tmp_path / "state.json")
    config = {"route_id": "r1", "images": "demo/app:latest", "github_repos": "demo/repo"}

    assert main.poll_once(config, state) == {"releases": 1, "images": 1, "first_run": True}
    assert calls == []

    docker_digest["value"] = "sha256:new"
    release_id["value"] = 2
    assert main.poll_once(config, state) == {"releases": 1, "images": 1, "first_run": False}
    assert len(calls) == 2


def test_ndu_monitor_formats_news_content():
    assert "仓库：demo/repo" in main.release_message({"repo": "demo/repo", "version": "v1", "time": "now", "body": "log"})
    assert "镜像：demo/app:latest" in main.image_message(
        {"key": "demo/app:latest", "updated": "now", "platforms": "linux/amd64"}
    )
