import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "plugins"))
from ndu_monitor.main import State, image_message, poll_once, release_message


def make_db(path):
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE image_info (
            id INTEGER PRIMARY KEY,
            image_name TEXT NOT NULL,
            image_tag TEXT NOT NULL,
            image_update_time TEXT NOT NULL,
            image_platform TEXT NOT NULL,
            image_digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE release_info (
            id INTEGER PRIMARY KEY,
            repo_name TEXT NOT NULL,
            release_version TEXT NOT NULL,
            release_time TEXT NOT NULL,
            release_log TEXT NOT NULL,
            release_log_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    db.execute(
        "INSERT INTO image_info VALUES (1, 'demo/app', 'latest', '2026-01-01', 'linux/amd64', 'sha256:old', '', '')"
    )
    db.execute(
        "INSERT INTO release_info VALUES (1, 'demo/repo', 'v1', '2026-01-01', 'raw', 'log', '', '')"
    )
    db.commit()
    db.close()


def test_ndu_monitor_baselines_then_detects_changes(tmp_path):
    db_path = tmp_path / "main.db"
    make_db(db_path)
    state = State(tmp_path / "state.json")
    config = {"ndu_db_path": str(db_path), "route_id": "r1"}

    assert poll_once(config, state, notify=False) == {"releases": 1, "images": 1, "first_run": True}

    db = sqlite3.connect(db_path)
    db.execute(
        "INSERT INTO release_info VALUES (2, 'demo/repo', 'v2', '2026-01-02', 'raw', 'log2', '', '')"
    )
    db.execute("UPDATE image_info SET image_digest='sha256:new', image_update_time='2026-01-02' WHERE id=1")
    db.commit()
    db.close()

    assert poll_once(config, state, notify=False) == {"releases": 1, "images": 1, "first_run": False}


def test_ndu_monitor_formats_news_content():
    assert "仓库：demo/repo" in release_message((1, "demo/repo", "v1", "2026-01-01", "raw", "log"))
    assert "镜像：demo/app:latest" in image_message((1, "demo/app", "latest", "2026-01-01", "linux/amd64", "sha"))
