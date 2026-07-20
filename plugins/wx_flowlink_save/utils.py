import time
from typing import Any

from notifyhub.plugins.utils import get_plugin_config


class FlowLinkPluginConfig:
    PLUGIN_ID = "wx-flowlink-save"

    def __init__(self):
        self._cache: dict[str, Any] | None = None
        self._fetched_at = 0.0

    def _values(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cache is None or now - self._fetched_at >= 15:
            self._cache = get_plugin_config(self.PLUGIN_ID) or {}
            self._fetched_at = now
        return self._cache

    def get(self, key: str, default: Any = "") -> Any:
        return self._values().get(key, default)

    @property
    def qywx_base_url(self) -> str:
        return str(self.get("qywx_base_url", "https://qyapi.weixin.qq.com")).rstrip("/")

    @property
    def corp_id(self) -> str:
        return str(self.get("sCorpID"))

    @property
    def corp_secret(self) -> str:
        return str(self.get("sCorpsecret"))

    @property
    def agent_id(self) -> str:
        return str(self.get("sAgentid"))

    @property
    def callback_token(self) -> str:
        return str(self.get("sToken"))

    @property
    def encoding_aes_key(self) -> str:
        return str(self.get("sEncodingAESKey"))

    @property
    def flowlink_url(self) -> str:
        return str(self.get("flowlink_url")).rstrip("/")

    @property
    def flowlink_token(self) -> str:
        return str(self.get("flowlink_token"))

    @property
    def task_name(self) -> str:
        return str(self.get("task_name", "115sub")).strip() or "115sub"

    @property
    def cover_url(self) -> str:
        return str(
            self.get(
                "cover_url",
                "https://s1.locimg.com/2025/01/03/13a09e2f7cb3a.png",
            )
        ).strip()


config = FlowLinkPluginConfig()
