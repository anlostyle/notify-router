"""Client for NextEmby's admin card (卡密) endpoints.

NextEmby accepts its system API key as ``Authorization: Bearer <key>`` on the
admin API, including the card endpoints its web UI uses.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..utils import Site


logger = logging.getLogger(__name__)
USER_AGENT = "wx-nextemby-card/0.3.1"


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
        self._transport = transport

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.site.api_key:
            raise NextEmbyError(f"{self.site.name} 未配置 API 密钥")
        with httpx.Client(
            base_url=self.site.base_url,
            headers={"User-Agent": USER_AGENT, "Authorization": f"Bearer {self.site.api_key}"},
            timeout=httpx.Timeout(60, connect=10),
            transport=self._transport,
        ) as client:
            response = client.request(method, path, **kwargs)
        if response.status_code in (401, 403):
            raise NextEmbyError(f"{self.site.name} API 密钥无效或无权限：" + _error_message(response, "鉴权失败"))
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


def client_for(site: Site) -> NextEmbyClient:
    return NextEmbyClient(site)
