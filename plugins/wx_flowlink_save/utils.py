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
    def base_url(self) -> str:
        return str(self.get("base_url") or self.get("flowlink_url")).rstrip("/")

    @property
    def name(self) -> str:
        return str(self.get("name") or self.get("task_name", "115sub")).strip() or "115sub"

    @property
    def token(self) -> str:
        return str(self.get("token") or self.get("flowlink_token"))

    @property
    def qywx_base_url(self) -> str:
        return str(self.get("qywx_base_url") or "https://qyapi.weixin.qq.com").rstrip("/")

    @property
    def sCorpID(self) -> str:
        return str(self.get("sCorpID") or "").strip()

    @property
    def sCorpsecret(self) -> str:
        return str(self.get("sCorpsecret") or "").strip()

    @property
    def sAgentid(self) -> str:
        return str(self.get("sAgentid") or "").strip()

    @property
    def sToken(self) -> str:
        return str(self.get("sToken") or "").strip()

    @property
    def sEncodingAESKey(self) -> str:
        return str(self.get("sEncodingAESKey") or "").strip()

    @property
    def cover_url(self) -> str:
        return str(self.get("cover_url") or "").strip()


config = FlowLinkPluginConfig()
