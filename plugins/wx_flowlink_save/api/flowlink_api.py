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

        # Newer FlowLink versions separate receiving a share from the later
        # directory-organizer scan.  Keep the first request free of ``name``
        # so that a share is only saved, then explicitly enqueue the named
        # organizer task.  Older versions require ``name`` on the shortcut
        # request; in that case fall back to their legacy one-step behavior.
        try:
            response = httpx.get(
                f"{config.base_url}/api/transfer/shortcut",
                params={"token": config.token, "url": url.strip()},
                headers={"User-Agent": "wx-flowlink-save/0.3.0"},
                timeout=httpx.Timeout(180, connect=10),
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                return {"success": False, "ok": False, "message": "FlowLink 返回了无效数据"}

            # FlowLink <= 1.1.x answers this when the two-phase shortcut is
            # not available.  Preserve compatibility with the deployed
            # image while allowing the newer API to use the intended flow.
            message = str(result.get("message") or result.get("error") or "")
            if not _result_ok(result) and "必须指定对应的转存任务配置" in message:
                return self._legacy_shortcut(url)
            if not _result_ok(result):
                return result

            scan = httpx.post(
                f"{config.base_url}/api/transfer/transfer/scan",
                json={"task_name": config.name},
                headers={
                    "User-Agent": "wx-flowlink-save/0.3.0",
                    "X-Api-Token": config.token,
                },
                timeout=httpx.Timeout(30, connect=10),
            )
            scan.raise_for_status()
            scan_result = scan.json()
            if not isinstance(scan_result, dict) or not _result_ok(scan_result):
                scan_message = (
                    scan_result.get("message")
                    if isinstance(scan_result, dict)
                    else "响应无效"
                )
                return {
                    **result,
                    "success": False,
                    "ok": False,
                    "message": f"分享已保存，但整理扫描触发失败：{scan_message}",
                }
            return {
                **result,
                "organizer_scan": scan_result,
                "message": f"{result.get('message', '分享已保存')}；已触发「{config.name}」整理扫描",
            }
        except httpx.TimeoutException:
            logger.warning("FlowLink shortcut request timed out")
            return {"success": False, "ok": False, "message": "FlowLink 处理超时，请稍后查看任务列表"}
        except httpx.HTTPStatusError as exc:
            logger.warning("FlowLink shortcut returned HTTP %s", exc.response.status_code)
            return {"success": False, "ok": False, "message": f"FlowLink 请求失败（HTTP {exc.response.status_code}）"}
        except (httpx.RequestError, ValueError):
            logger.warning("FlowLink shortcut request failed", exc_info=True)
            return {"success": False, "ok": False, "message": "无法连接 FlowLink 或响应无效"}

    def _legacy_shortcut(self, url: str) -> dict[str, Any]:
        """Use the one-step API exposed by FlowLink 1.1.x."""
        response = httpx.get(
            f"{config.base_url}/api/transfer/shortcut",
            params={"name": config.name, "token": config.token, "url": url.strip()},
            headers={"User-Agent": "wx-flowlink-save/0.3.0"},
            timeout=httpx.Timeout(180, connect=10),
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            return {"success": False, "ok": False, "message": "FlowLink 返回了无效数据"}
        return result


def _result_ok(result: dict[str, Any]) -> bool:
    return bool(result.get("ok", result.get("success", False)))


flowlink = FlowLinkApi()
