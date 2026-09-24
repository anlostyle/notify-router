"""Client for NextEmby's admin card (卡密) endpoints.

NextEmby has no API key for these endpoints; the admin web UI logs in with a
username and password and keeps a session cookie.  The client does the same,
re-logs in once when the session expires, and backs off after a failed login
so a wrong password cannot trigger NextEmby's repeated-failure handling.
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..utils import Site


logger = logging.getLogger(__name__)
USER_AGENT = "wx-nextemby-card/0.1.0"
LOGIN_BACKOFF_SECONDS = 120


class NextEmbyError(Exception):
    pass


@dataclass
class CardBatch:
    batch_id: str
    codes: list[str]


def _error_message(response: httpx.Response, fallback: str) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"{fallback}（HTTP {response.status_code}）"
    if isinstance(data, dict):
        message = data.get("detail") or data.get("message")
        if message:
            return str(message)[:200]
    return f"{fallback}（HTTP {response.status_code}）"


def parse_generate_output(text: str) -> CardBatch:
    """Parse the streamed generate response: ``BATCH_ID:<id>`` then one code per line."""
    batch_id = ""
    codes: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("BATCH_ID:"):
            batch_id = line[len("BATCH_ID:"):].strip()
        else:
            codes.append(line)
    if not batch_id or not codes:
        raise NextEmbyError("NextEmby 未返回卡密：" + (text.strip()[:200] or "空响应"))
    return CardBatch(batch_id=batch_id, codes=codes)


class NextEmbyClient:
    def __init__(self, site: Site, transport: httpx.BaseTransport | None = None):
        self.site = site
        self._lock = threading.Lock()
        self._logged_in = False
        self._login_failed_at = 0.0
        self._http = httpx.Client(
            base_url=site.base_url,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(60, connect=10),
            follow_redirects=False,
            transport=transport,
        )

    def _login(self) -> None:
        if not self.site.username or not self.site.password:
            raise NextEmbyError(f"{self.site.name} 未配置管理员账号或密码")
        wait = LOGIN_BACKOFF_SECONDS - (time.monotonic() - self._login_failed_at)
        if self._login_failed_at and wait > 0:
            raise NextEmbyError(f"{self.site.name} 登录刚失败过，请 {int(wait)} 秒后再试或检查插件配置")
        self._http.cookies.clear()
        response = self._http.post(
            "/api/admin/login",
            json={"username": self.site.username, "password": self.site.password},
        )
        if response.status_code != 200:
            self._login_failed_at = time.monotonic()
            self._logged_in = False
            raise NextEmbyError(f"{self.site.name} 管理员登录失败：" + _error_message(response, "登录失败"))
        self._login_failed_at = 0.0
        self._logged_in = True
        logger.info("NextEmby 管理员登录成功: %s", self.site.name)

    @staticmethod
    def _session_expired(response: httpx.Response) -> bool:
        if response.status_code in (401, 403):
            return True
        return response.is_redirect and "login" in response.headers.get("location", "")

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        with self._lock:
            if not self._logged_in:
                self._login()
            response = self._http.request(method, path, **kwargs)
            if self._session_expired(response):
                self._logged_in = False
                self._login()
                response = self._http.request(method, path, **kwargs)
            if self._session_expired(response):
                self._logged_in = False
                raise NextEmbyError(f"{self.site.name} 登录后仍无权访问 {path}")
            return response

    def _json(self, method: str, path: str, fallback: str, **kwargs) -> Any:
        response = self._request(method, path, **kwargs)
        if response.status_code != 200:
            raise NextEmbyError(_error_message(response, fallback))
        try:
            data = response.json()
        except ValueError as exc:
            raise NextEmbyError(f"{fallback}：返回的不是 JSON") from exc
        if isinstance(data, dict) and data.get("status") not in (None, "success"):
            raise NextEmbyError(str(data.get("message") or fallback)[:200])
        return data

    def generate(self, count: int, days: int, template: str) -> CardBatch:
        response = self._request(
            "POST",
            "/api/admin/cards/generate",
            json={"duration_days": days, "count": count, "template_name": template},
        )
        if response.status_code != 200:
            raise NextEmbyError(_error_message(response, "生成卡密失败"))
        if "application/json" in response.headers.get("content-type", ""):
            data = response.json()
            raise NextEmbyError(str(data.get("message") or data.get("detail") or "生成卡密失败")[:200])
        return parse_generate_output(response.text)

    def batches(self) -> list[dict]:
        data = self._json("GET", "/api/admin/cards/batches", "获取卡密批次失败", params={"t": int(time.time() * 1000)})
        return list(data.get("data") or [])

    def history(self) -> list[dict]:
        data = self._json("GET", "/api/admin/cards/history", "获取兑换记录失败")
        return list(data.get("data") or [])

    def revoke(self, batch_id: str) -> str:
        data = self._json("POST", "/api/admin/cards/revoke", "作废失败", json={"batch_id": batch_id})
        return str(data.get("message") or "已作废")


_clients: dict[str, NextEmbyClient] = {}
_clients_lock = threading.Lock()


def client_for(site: Site) -> NextEmbyClient:
    """Reuse one logged-in client per site until its connection settings change."""
    fingerprint = hashlib.sha256(
        "\0".join([site.base_url, site.username, site.password]).encode("utf-8")
    ).hexdigest()
    with _clients_lock:
        client = _clients.get(site.slot)
        if client is None or getattr(client, "fingerprint", None) != fingerprint:
            client = NextEmbyClient(site)
            client.fingerprint = fingerprint
            _clients[site.slot] = client
        client.site = site
        return client
