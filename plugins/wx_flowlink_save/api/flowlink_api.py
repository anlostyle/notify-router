import logging
from typing import Any

import httpx

from ..utils import config


logger = logging.getLogger(__name__)


class FlowLinkApi:
    """Minimal client for FlowLink's one-click share transfer pipeline."""

    def receive_share(self, share_input: str) -> dict[str, Any]:
        if not config.flowlink_url or not config.flowlink_token:
            return {"success": False, "message": "FlowLink 配置不完整"}

        try:
            response = httpx.post(
                f"{config.flowlink_url}/api/transfer/share/receive",
                json={"share_url": share_input, "task_name": config.task_name},
                headers={
                    "X-Api-Token": config.flowlink_token,
                    "User-Agent": "wx-flowlink-save/0.1.0",
                },
                timeout=httpx.Timeout(180, connect=10),
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("FlowLink 返回了无效数据")
            return {"success": True, **result}
        except httpx.TimeoutException:
            logger.warning("FlowLink share receive timed out")
            return {"success": False, "message": "FlowLink 处理超时，请稍后查看任务列表"}
        except httpx.HTTPStatusError as exc:
            logger.warning("FlowLink share receive returned HTTP %s", exc.response.status_code)
            return {
                "success": False,
                "message": f"FlowLink 请求失败（HTTP {exc.response.status_code}）",
            }
        except (httpx.RequestError, ValueError):
            logger.warning("FlowLink share receive failed", exc_info=True)
            return {"success": False, "message": "无法连接 FlowLink 或响应无效"}


flowlink = FlowLinkApi()
