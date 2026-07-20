import logging
from typing import Any

import httpx

from ..utils import config


logger = logging.getLogger(__name__)


class FlowLinkApi:
    """Client for FlowLink's iOS Shortcut-compatible transfer endpoint."""

    def shortcut(self, url: str) -> dict[str, Any]:
        if not config.base_url or not config.name or not config.token:
            return {"success": False, "ok": False, "message": "FlowLink 配置不完整"}
        if not url.strip():
            return {"success": False, "ok": False, "message": "缺少 url 参数"}
        try:
            response = httpx.get(
                f"{config.base_url}/api/transfer/shortcut",
                params={"name": config.name, "token": config.token, "url": url.strip()},
                headers={"User-Agent": "wx-flowlink-save/0.2.0"},
                timeout=httpx.Timeout(180, connect=10),
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                return {"success": False, "ok": False, "message": "FlowLink 返回了无效数据"}
            return result
        except httpx.TimeoutException:
            logger.warning("FlowLink shortcut request timed out")
            return {"success": False, "ok": False, "message": "FlowLink 处理超时，请稍后查看任务列表"}
        except httpx.HTTPStatusError as exc:
            logger.warning("FlowLink shortcut returned HTTP %s", exc.response.status_code)
            return {"success": False, "ok": False, "message": f"FlowLink 请求失败（HTTP {exc.response.status_code}）"}
        except (httpx.RequestError, ValueError):
            logger.warning("FlowLink shortcut request failed", exc_info=True)
            return {"success": False, "ok": False, "message": "无法连接 FlowLink 或响应无效"}


flowlink = FlowLinkApi()
