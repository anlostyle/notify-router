import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter

from notifyhub.controller.server import server
from notifyhub.plugins.common import after_setup
from notifyhub.plugins.utils import get_plugin_config
from notifyhub.plugins.sdk import record_monitor


PLUGIN_ID = "ndu_monitor"
LOG_PREFIX = "NDU 更新监控"
logger = logging.getLogger(__name__)
ndu_monitor_router = APIRouter(prefix="/ndu_monitor", tags=["ndu_monitor"])


def _workdir():
    import os

    return Path(os.environ.get("WORKDIR") or "/data")


def _data_dir():
    import os

    return Path(os.environ.get("PLUGIN_DATA_DIR") or (_workdir() / "plugin-data" / PLUGIN_ID))


class State:
    def __init__(self, path=None):
        self.path = Path(path or (_data_dir() / "state.json"))
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


def _lines(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value or "").replace(",", "\n").splitlines() if x.strip()]


def _poll_seconds(config):
    try:
        return max(300, int(config.get("poll_seconds") or 3600))
    except Exception:
        return 3600


def _split_image(value):
    image, _, tag = value.partition(":")
    return image, tag or "latest"


def _docker_url(image):
    if "/" not in image:
        return f"https://hub.docker.com/_/{image}"
    return f"https://hub.docker.com/r/{image}"


def _release_url(repo, version):
    return f"https://github.com/{repo}/releases/tag/{quote(str(version), safe='')}"


def _short(text, limit=420):
    text = str(text or "").strip()
    return text[:limit] + ("..." if len(text) > limit else "")


def client_get(url, headers=None):
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def docker_info(ref):
    image, tag = _split_image(ref)
    namespace, repo = ("library", image) if "/" not in image else image.split("/", 1)
    data = client_get(f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags/{quote(tag, safe='')}")
    images = data.get("images") or []
    digest = data.get("digest") or "|".join(sorted(str(x.get("digest") or "") for x in images if x.get("digest")))
    platforms = " | ".join(
        sorted({"/".join(str(x.get(k) or "") for k in ("os", "architecture") if x.get(k)) for x in images if x.get("os")})
    )
    return {
        "key": f"{image}:{tag}",
        "image": image,
        "tag": tag,
        "digest": digest or str(data.get("last_updated") or ""),
        "updated": str(data.get("tag_last_pushed") or data.get("last_updated") or ""),
        "platforms": platforms,
    }


def github_release(repo, token=""):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = client_get(f"https://api.github.com/repos/{repo}/releases?per_page=1", headers=headers)
    release = data[0] if data else {}
    return {
        "repo": repo,
        "id": str(release.get("id") or release.get("tag_name") or ""),
        "version": str(release.get("name") or release.get("tag_name") or ""),
        "time": str(release.get("published_at") or ""),
        "body": str(release.get("body") or ""),
        "url": str(release.get("html_url") or _release_url(repo, release.get("tag_name") or "")),
    }


def release_message(release):
    return (
        f"仓库：{release['repo']}\n"
        f"版本：{release['version']}\n"
        f"发布时间：{release['time']}\n"
        f"更新日志：{_short(release['body'])}"
    )


def image_message(image):
    return f"镜像：{image['key']}\n更新时间：{image['updated']}\n平台：{image['platforms']}"


def poll_once(config=None, state=None, notify=True):
    config = config or _config()
    route_id = str(config.get("route_id") or "").strip()
    state = state or State()
    data = state.load()
    first_run = not data
    previous_releases = dict(data.get("releases") or {})
    previous_images = dict(data.get("images") or {})
    releases = {}
    images = {}

    for repo in _lines(config.get("github_repos")):
        try:
            release = github_release(repo, str(config.get("github_token") or ""))
        except Exception as exc:
            logger.warning("%s GitHub 检查失败 %s: %s", LOG_PREFIX, repo, exc)
            continue
        releases[repo] = release["id"]
        if notify and route_id and not first_run and previous_releases.get(repo) and previous_releases[repo] != release["id"]:
            server.send_notify_by_router(
                route_id,
                f"仓库 {repo} 发布了新版本",
                release_message(release),
                config.get("github_picurl") or None,
                release["url"],
            )

    for ref in _lines(config.get("images")):
        try:
            image = docker_info(ref)
        except Exception as exc:
            logger.warning("%s DockerHub 检查失败 %s: %s", LOG_PREFIX, ref, exc)
            continue
        images[image["key"]] = image["digest"]
        if notify and route_id and not first_run and previous_images.get(image["key"]) and previous_images[image["key"]] != image["digest"]:
            server.send_notify_by_router(
                route_id,
                f"镜像 {image['key']} 更新了",
                image_message(image),
                config.get("docker_picurl") or None,
                _docker_url(image["image"]),
            )

    data.update({"releases": releases, "images": images, "updated_at": time.time()})
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
                    record_monitor("registry", "NDU 镜像与仓库更新", "healthy", f"已检查 {result['releases']} 个仓库、{result['images']} 个镜像", "container")
                    logger.info("%s 检查完成: %s", LOG_PREFIX, result)
                except Exception as exc:
                    record_monitor("registry", "NDU 镜像与仓库更新", "error", "最近一次检查失败", "container")
                    logger.error("%s 检查失败: %s", LOG_PREFIX, exc, exc_info=True)
            time.sleep(_poll_seconds(config))


_poller = None


@after_setup(PLUGIN_ID, "poll registries")
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
        "repos": len(_lines(config.get("github_repos"))),
        "images": len(_lines(config.get("images"))),
        "known_releases": len(data.get("releases") or {}),
        "known_images": len(data.get("images") or {}),
    }
