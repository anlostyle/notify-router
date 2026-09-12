import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from notifyhub.controller.schedule import register_cron_job
from notifyhub.controller.server import server
from notifyhub.plugins.common import after_setup
from notifyhub.plugins.sdk import record_monitor
from notifyhub.plugins.utils import get_plugin_config


PLUGIN_ID = "baiyun_traffic"
TZ = ZoneInfo("Asia/Shanghai")
USERINFO_RE = re.compile(r"(?:^|[,;]\s*)(upload|download|total|expire)\s*=\s*(\d+)")
logger = logging.getLogger(__name__)
_task_lock = threading.Lock()


def _data_dir():
    return Path(os.environ.get("PLUGIN_DATA_DIR") or Path(os.environ.get("WORKDIR", "/data")) / "plugin-data" / PLUGIN_ID)


class State:
    def __init__(self, path=None):
        self.path = Path(path or _data_dir() / "state.json")

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"account": "白菜机场", "daily": {}, "last": None}
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("状态文件无法解析，将从新快照开始统计")
            return {"account": "白菜机场", "daily": {}, "last": None}

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _config():
    return get_plugin_config(PLUGIN_ID) or {}


def _enabled(value):
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _url(value, label, required=False):
    value = str(value or "").strip()
    if not value and not required:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label}必须是完整的 HTTP 或 HTTPS 地址")
    return value


def parse_userinfo(header):
    values = {key: int(value) for key, value in USERINFO_RE.findall(str(header or ""))}
    missing = {"upload", "download", "total", "expire"} - values.keys()
    if missing:
        raise ValueError(f"订阅响应缺少字段：{', '.join(sorted(missing))}")
    return values


def fetch_userinfo(subscription_url):
    url = _url(subscription_url, "订阅地址", required=True)
    try:
        response = httpx.get(url, headers={"User-Agent": "notify-router-baiyun-traffic/0.1"}, timeout=30, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"订阅请求失败：{type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"订阅请求返回 HTTP {response.status_code}")
    header = response.headers.get("Subscription-Userinfo", "")
    if not header:
        raise RuntimeError("订阅响应没有 Subscription-Userinfo")
    return parse_userinfo(header)


def build_usage(values, state, timestamp):
    previous = state.get("last") or {}
    used = values["upload"] + values["download"]
    previous_used = int(previous.get("upload", 0)) + int(previous.get("download", 0))
    reset = bool(previous) and used < previous_used
    delta = 0 if reset or not previous else max(0, used - previous_used)
    day = timestamp.date().isoformat()
    daily = state.setdefault("daily", {})
    daily[day] = int(daily.get(day, 0)) + delta
    # ponytail: 90 天数据适合单个 JSON；只有需要长期查询时再换数据库。
    for old_day in sorted(daily)[:-90]:
        daily.pop(old_day, None)
    usage = {
        "account": "白菜机场",
        "upload": values["upload"],
        "download": values["download"],
        "used": used,
        "total": values["total"],
        "remaining": max(0, values["total"] - used),
        "percent": round(used / values["total"] * 100, 4) if values["total"] else None,
        "expire": values["expire"],
        "updatedAt": timestamp.isoformat(),
        "date": day,
        "todayUsed": daily[day],
        "reset": reset,
        "daily": dict(sorted(daily.items(), reverse=True)[:14]),
    }
    state["last"] = {**values, "used": used, "updatedAt": usage["updatedAt"]}
    state["lastUsage"] = usage
    return usage


def build_report_usage(usage, state):
    baseline = state.get("reportBaseline") or {}
    previous_used = baseline.get("used")
    period_used = None
    period_reset = False
    if previous_used is not None:
        previous_used = int(previous_used)
        if usage["used"] >= previous_used:
            period_used = usage["used"] - previous_used
        else:
            period_reset = True
    report = {
        **usage,
        "periodUsed": period_used,
        "periodStart": baseline.get("at"),
        "periodEnd": usage["updatedAt"],
        "periodReset": period_reset,
    }
    state["reportBaseline"] = {"used": usage["used"], "at": usage["updatedAt"]}
    state["lastReport"] = report
    return report


def fmt_bytes(value):
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or unit == "TiB":
            return f"{int(amount)} B" if unit == "B" else f"{amount:.2f} {unit}"
        amount /= 1024


def fmt_period(start, end):
    if not start or not end:
        return "等待下个完整周期"
    return " → ".join(datetime.fromisoformat(value).astimezone(TZ).strftime("%m-%d %H:%M") for value in (start, end))


def _reset_day(config):
    try:
        return min(31, max(1, int(config.get("reset_day") or 12)))
    except (TypeError, ValueError):
        return 12


def _monitor_healthy(usage):
    percent = "未知" if usage["percent"] is None else f"{usage['percent']:.2f}%"
    record_monitor(
        "subscription",
        "白菜云订阅流量",
        "healthy",
        f"已使用 {percent}，剩余 {fmt_bytes(usage['remaining'])}",
        "service",
        {"used": usage["used"], "total": usage["total"], "remaining": usage["remaining"], "percent": usage["percent"]},
    )


def collect_once(config=None, state=None, timestamp=None):
    config = config or _config()
    state = state or State()
    data = state.load()
    usage = build_usage(fetch_userinfo(config.get("subscription_token_url")), data, timestamp or datetime.now(TZ))
    state.save(data)
    return usage


def report_once(config=None, state=None, timestamp=None):
    config = config or _config()
    route_id = str(config.get("route_id") or "").strip()
    if not route_id:
        raise ValueError("请先选择通知通道")
    state = state or State()
    usage = collect_once(config, state, timestamp)
    data = state.load()
    report = build_report_usage(usage, data)
    if report["periodReset"]:
        period_used = "无法完整计算"
    elif report["periodUsed"] is None:
        period_used = "待下次报告"
    else:
        period_used = fmt_bytes(report["periodUsed"])
    expire = datetime.fromtimestamp(report["expire"], TZ).strftime("%Y-%m-%d")
    percent = "未知" if report["percent"] is None else f"{report['percent']:.2f}%"
    title = f"白菜云｜本期使用 {period_used}"
    content = "\n".join(
        (
            f"套餐用量：{fmt_bytes(report['used'])} / {fmt_bytes(report['total'])}",
            f"使用比例：{percent}",
            f"剩余流量：{fmt_bytes(report['remaining'])}",
            f"重置日期：每月 {_reset_day(config)} 日",
            f"套餐到期：{expire}",
            f"统计周期：{fmt_period(report['periodStart'], report['periodEnd'])}",
        )
    )
    image_url = _url(config.get("image_url"), "通知图片")
    link_url = _url(config.get("link_url") or image_url, "点击链接")
    server.send_notify_by_router(route_id, title, content, image_url or None, link_url or None)
    state.save(data)
    return report


def collect_task():
    config = _config()
    if not _enabled(config.get("enabled", "1")):
        return
    with _task_lock:
        try:
            usage = collect_once(config)
            _monitor_healthy(usage)
            logger.info("白菜云流量采集完成：已使用 %.2f%%，剩余 %s", usage["percent"] or 0, fmt_bytes(usage["remaining"]))
        except Exception:
            record_monitor("subscription", "白菜云订阅流量", "error", "最近一次流量采集失败", "service")
            logger.exception("白菜云流量采集失败")
            raise


def report_task():
    config = _config()
    if not _enabled(config.get("enabled", "1")):
        return
    with _task_lock:
        try:
            report = report_once(config)
            _monitor_healthy(report)
            logger.info("白菜云每日流量报告已发送")
        except Exception as exc:
            record_monitor("subscription", "白菜云订阅流量", "error", "最近一次每日报告失败", "service")
            route_id = str(config.get("route_id") or "").strip()
            if route_id:
                try:
                    server.send_notify_by_router(route_id, "白菜云流量采集失败", f"时间：{datetime.now(TZ):%Y-%m-%d %H:%M:%S}\n原因：{exc}")
                except Exception:
                    logger.exception("白菜云失败通知发送失败")
            logger.exception("白菜云每日流量报告失败")
            raise


@after_setup(PLUGIN_ID, "注册白菜云流量任务")
def start():
    register_cron_job("*/30 * * * *", "白菜云流量采集", collect_task)
    register_cron_job("0 9 * * *", "白菜云每日流量报告", report_task)
