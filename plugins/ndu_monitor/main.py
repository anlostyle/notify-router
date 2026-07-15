import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter

from notifyhub.controller.server import server
from notifyhub.plugins.common import after_setup
from notifyhub.plugins.utils import get_plugin_config


PLUGIN_ID = "ndu_monitor"
LOG_PREFIX = "NDU 更新监控"
logger = logging.getLogger(__name__)
ndu_monitor_router = APIRouter(prefix="/ndu_monitor", tags=["ndu_monitor"])


def _workdir():
    import os

    return Path(os.environ.get("WORKDIR") or "/data")


class State:
    def __init__(self, path=None):
        self.path = Path(path or (_workdir() / "plugins" / PLUGIN_ID / "state.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def save(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _config():
    return get_plugin_config(PLUGIN_ID) or {}


def _enabled(value):
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _poll_seconds(config):
    try:
        return max(60, int(config.get("poll_seconds") or 300))
    except Exception:
        return 300


def _connect(db_path):
    return sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True, timeout=5)


def _release_url(repo, version):
    return f"https://github.com/{repo}/releases/tag/{quote(str(version), safe='')}"


def _docker_url(image):
    if "/" not in image:
        return f"https://hub.docker.com/_/{image}"
    return f"https://hub.docker.com/r/{image}"


def _short(text, limit=420):
    text = str(text or "").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def release_message(row):
    repo, version, release_time, release_log_text = row[1], row[2], row[3], row[5]
    return (
        f"仓库：{repo}\n"
        f"版本：{version}\n"
        f"发布时间：{release_time}\n"
        f"更新日志：{_short(release_log_text)}"
    )


def image_message(row):
    image, tag, update_time, platform = row[1], row[2], row[3], row[4]
    return f"镜像：{image}:{tag}\n更新时间：{update_time}\n平台：{platform}"


def poll_once(config=None, state=None, notify=True):
    config = config or _config()
    route_id = str(config.get("route_id") or "").strip()
    db_path = str(config.get("ndu_db_path") or "/ndu/db/main.db").strip()
    state = state or State()
    data = state.load()
    with _connect(db_path) as db:
        releases = db.execute(
            "SELECT id, repo_name, release_version, release_time, release_log, release_log_text FROM release_info WHERE id>? ORDER BY id",
            (int(data.get("release_id") or 0),),
        ).fetchall()
        images = db.execute(
            "SELECT id, image_name, image_tag, image_update_time, image_platform, image_digest FROM image_info ORDER BY id"
        ).fetchall()

    known_images = dict(data.get("images") or {})
    first_run = not data
    if notify and route_id and not first_run:
        for row in releases:
            server.send_notify_by_router(
                route_id,
                f"仓库 {row[1]} 发布了新版本",
                release_message(row),
                config.get("github_picurl") or None,
                _release_url(row[1], row[2]),
            )
        for row in images:
            key = f"{row[1]}:{row[2]}"
            if known_images.get(key) and known_images[key] != row[5]:
                server.send_notify_by_router(
                    route_id,
                    f"镜像 {key} 更新了",
                    image_message(row),
                    config.get("docker_picurl") or None,
                    _docker_url(row[1]),
                )

    if releases:
        data["release_id"] = max(row[0] for row in releases)
    elif "release_id" not in data:
        data["release_id"] = 0
    data["images"] = {f"{row[1]}:{row[2]}": row[5] for row in images}
    state.save(data)
    return {"releases": len(releases), "images": len(images), "first_run": first_run}


class Poller(threading.Thread):
    def __init__(self):
        super().__init__(name="NDUMonitor", daemon=True)

    def run(self):
        while True:
            config = _config()
            if _enabled(config.get("enabled", "1")):
                try:
                    result = poll_once(config)
                    logger.info("%s 检查完成: %s", LOG_PREFIX, result)
                except Exception as exc:
                    logger.error("%s 检查失败: %s", LOG_PREFIX, exc, exc_info=True)
            time.sleep(_poll_seconds(config))


_poller = None


@after_setup(PLUGIN_ID, "poll ndu sqlite")
def start():
    global _poller
    if _poller is None:
        _poller = Poller()
        _poller.start()


@ndu_monitor_router.get("/status")
def status():
    config = _config()
    data = State().load()
    return {
        "enabled": _enabled(config.get("enabled", "1")),
        "configured": bool(config.get("route_id")),
        "release_id": data.get("release_id"),
        "images": len(data.get("images") or {}),
    }
