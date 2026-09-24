import time
from dataclasses import dataclass
from typing import Any

from notifyhub.plugins.utils import get_plugin_config


SITE_SLOTS = ("site1", "site2")
MAX_COUNT_LIMIT = 20


@dataclass(frozen=True)
class Site:
    slot: str
    name: str
    base_url: str
    username: str
    password: str
    templates: tuple[str, ...]
    register_url: str
    emby_url: str

    @property
    def default_template(self) -> str:
        return self.templates[0] if self.templates else ""


def _split(value: Any) -> list[str]:
    text = str(value or "").replace("，", ",").replace("|", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def _int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class NextEmbyCardConfig:
    PLUGIN_ID = "wx-nextemby-card"

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
        value = self._values().get(key, default)
        return default if value is None else value

    def _str(self, key: str, default: str = "") -> str:
        return str(self.get(key) or default).strip()

    @property
    def allowed_users(self) -> list[str]:
        return _split(self.get("allowed_users"))

    @property
    def default_days(self) -> int:
        return max(1, _int(self.get("default_days"), 365))

    @property
    def max_count(self) -> int:
        return min(MAX_COUNT_LIMIT, max(1, _int(self.get("max_count"), 10)))

    @property
    def card_template(self) -> str:
        return str(self.get("card_template") or "").strip()

    def site(self, slot: str) -> Site | None:
        base_url = self._str(f"{slot}_base_url").rstrip("/")
        if not base_url:
            return None
        return Site(
            slot=slot,
            name=self._str(f"{slot}_name") or slot,
            base_url=base_url,
            username=self._str(f"{slot}_username"),
            password=str(self.get(f"{slot}_password") or ""),
            templates=tuple(_split(self.get(f"{slot}_templates"))),
            register_url=self._str(f"{slot}_register_url") or f"{base_url}/login",
            emby_url=self._str(f"{slot}_emby_url"),
        )

    @property
    def sites(self) -> list[Site]:
        return [site for site in (self.site(slot) for slot in SITE_SLOTS) if site]

    @property
    def qywx_base_url(self) -> str:
        return self._str("qywx_base_url", "https://qyapi.weixin.qq.com").rstrip("/")

    @property
    def sCorpID(self) -> str:
        return self._str("sCorpID")

    @property
    def sCorpsecret(self) -> str:
        return self._str("sCorpsecret")

    @property
    def sAgentid(self) -> str:
        return self._str("sAgentid")

    @property
    def sToken(self) -> str:
        return self._str("sToken")

    @property
    def sEncodingAESKey(self) -> str:
        return self._str("sEncodingAESKey")


config = NextEmbyCardConfig()
