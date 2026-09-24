"""Parse Enterprise WeChat text commands and run them against NextEmby."""

import datetime
import logging
import re
import string
from dataclasses import dataclass

from .api.nextemby_api import NextEmbyError, client_for
from .utils import Site, config


logger = logging.getLogger(__name__)
CST = datetime.timezone(datetime.timedelta(hours=8))
MAX_DAYS = 3650
LIST_LIMIT = 10
DEFAULT_CARD_TEMPLATE = (
    "🎬 {site} 邀请码\n"
    "有效期：{days} 天\n"
    "注册地址：{register_url}\n"
    "邀请码：{code}\n"
    "Emby 服务器：{emby_url}\n"
    "打开注册地址，点「注册」，填写用户名、密码和邀请码即可。"
)
ACTIONS = {
    "卡密": "generate",
    "发卡": "generate",
    "生成": "generate",
    "库存": "stock",
    "批次": "stock",
    "记录": "history",
    "兑换记录": "history",
    "作废": "revoke",
    "帮助": "help",
    "help": "help",
    "菜单": "help",
}
COMMAND_PATTERN = re.compile(
    r"^(" + "|".join(sorted(map(re.escape, ACTIONS), key=len, reverse=True)) + r")\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
DAYS_PATTERN = re.compile(r"^(\d+)\s*(?:天|d)$", re.IGNORECASE)
COUNT_PATTERN = re.compile(r"^(\d+)\s*张$")
SITE_NUMBER_PATTERN = re.compile(r"\d{1,2}")


@dataclass
class Command:
    action: str
    site: Site | None = None
    count: int = 1
    days: int = 0
    template: str = ""
    batch_id: str = ""
    error: str = ""


def _find_site(token: str, sites: list[Site]) -> Site | None:
    key = token.strip().lower()
    for index, site in enumerate(sites, 1):
        if key in {site.name.lower(), site.slot, f"站点{index}"}:
            return site
    return None


def _match_template(token: str, site: Site) -> str | None:
    for template in site.templates:
        if template.lower() == token.lower():
            return template
    return None


def parse_command(text: str) -> Command:
    text = (text or "").strip()
    sites = config.sites
    match = COMMAND_PATTERN.match(text)
    if match:
        action = ACTIONS[match.group(1).lower()]
        tokens = match.group(2).split()
    elif SITE_NUMBER_PATTERN.fullmatch(text):
        action, tokens = "generate", [text]
    else:
        return Command("help")
    if action == "help":
        return Command("help")
    if not sites:
        return Command(action, error="插件还没有配置 NextEmby 站点")

    # A bare number right after the command picks the site: 卡密1, 卡密 2, 库存2.
    site = None
    rest = []
    for token in tokens:
        if site is None and SITE_NUMBER_PATTERN.fullmatch(token):
            index = int(token)
            if not 1 <= index <= len(sites):
                return Command(action, error=f"没有站点{index}，可用：" + "、".join(f"{i}={s.name}" for i, s in enumerate(sites, 1)))
            site = sites[index - 1]
            continue
        found = _find_site(token, sites)
        if found and site is None:
            site = found
        else:
            rest.append(token)
    command = Command(action, site=site or sites[0])

    if action == "revoke":
        if len(rest) != 1:
            command.error = "用法：作废 批次号 [站点]"
        else:
            command.batch_id = rest[0]
        return command
    if action != "generate":
        if rest:
            command.error = "无法识别：" + " ".join(rest)
        return command

    count = days = None
    template = None
    unknown = []
    for token in rest:
        if day_match := DAYS_PATTERN.match(token):
            days = int(day_match.group(1))
        elif count_match := COUNT_PATTERN.match(token):
            count = int(count_match.group(1))
        elif token.isdigit():
            command.error = f"无法识别：{token}；张数写成 2张，天数写成 180天"
            return command
        elif command.site.templates and _match_template(token, command.site):
            template = _match_template(token, command.site)
        elif not command.site.templates and template is None:
            template = token
        else:
            unknown.append(token)
    if unknown:
        hint = f"；{command.site.name} 可用模板：{'、'.join(command.site.templates)}" if command.site.templates else ""
        command.error = "无法识别：" + " ".join(unknown) + hint
        return command
    command.count = count if count is not None else 1
    command.days = days if days is not None else config.default_days
    command.template = template if template is not None else command.site.default_template
    if not 1 <= command.count <= config.max_count:
        command.error = f"张数需要在 1 到 {config.max_count} 之间"
    elif not 1 <= command.days <= MAX_DAYS:
        command.error = f"天数需要在 1 到 {MAX_DAYS} 之间"
    return command


def render_card(template: str, values: dict[str, str]) -> str:
    """Fill a card template, dropping lines whose placeholders are empty."""
    lines = []
    for line in template.splitlines():
        names = [name for _, name, _, _ in string.Formatter().parse(line) if name]
        if any(not str(values.get(name, "")).strip() for name in names if name in values):
            continue
        try:
            lines.append(line.format_map(_KeepUnknown(values)))
        except (ValueError, IndexError):
            lines.append(line)
    return "\n".join(lines).strip()


class _KeepUnknown(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _format_time(value) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(value), CST).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError):
        return str(value or "-")


def help_text() -> str:
    sites = config.sites
    site_lines = "\n".join(f"卡密{index} → {site.name}" for index, site in enumerate(sites, 1)) or "未配置站点"
    return (
        "🎫 NextEmby 卡密助手\n\n"
        f"{site_lines}\n"
        "卡密1 2张 180天 → 指定张数、天数\n"
        "卡密1 模板名 → 指定模板\n"
        "库存1 / 记录1 → 未用完批次 / 最近兑换\n"
        "作废 批次号 → 作废该批次未使用的卡密（站点2 写成 作废2 批次号）\n\n"
        f"不写数字时默认站点1；默认 {config.default_days} 天，单次最多 {config.max_count} 张"
    )


def _generate(command: Command) -> list[str]:
    site = command.site
    batch = client_for(site).generate(command.count, command.days, command.template)
    template = config.card_template or DEFAULT_CARD_TEMPLATE
    messages = [
        render_card(
            template,
            {
                "site": site.name,
                "days": str(command.days),
                "template": command.template,
                "code": code,
                "register_url": site.register_url,
                "emby_url": site.emby_url,
                "batch_id": batch.batch_id,
            },
        )
        for code in batch.codes
    ]
    detail = f"{command.days} 天" + (f" · {command.template}" if command.template else "")
    index = next(i for i, item in enumerate(config.sites, 1) if item.slot == site.slot)
    summary = f"✅ {site.name} 已生成 {len(batch.codes)} 张卡密（{detail}）\n批次：{batch.batch_id}\n作废请发：作废{index} {batch.batch_id}"
    if len(batch.codes) != command.count:
        summary += f"\n⚠️ 请求 {command.count} 张，实际返回 {len(batch.codes)} 张"
    _record("cards.generated", site, batch.batch_id, f"生成 {len(batch.codes)} 张卡密（{detail}）")
    logger.info("NextEmby 卡密已生成: site=%s batch=%s count=%s", site.name, batch.batch_id, len(batch.codes))
    return messages + [summary]


def _stock(command: Command) -> list[str]:
    batches = [item for item in client_for(command.site).batches() if int(item.get("remaining") or 0) > 0]
    if not batches:
        return [f"📦 {command.site.name} 没有未用完的卡密批次"]
    lines = [f"📦 {command.site.name} 未用完批次（共剩 {sum(int(item.get('remaining') or 0) for item in batches)} 张）"]
    for item in batches[:LIST_LIMIT]:
        extra = " · ".join(
            part
            for part in (
                f"{item['duration_days']}天" if item.get("duration_days") else "",
                str(item.get("template_name") or ""),
            )
            if part
        )
        lines.append(f"{item.get('batch_id')}  剩 {item.get('remaining')}/{item.get('total')}" + (f"  {extra}" if extra else ""))
    if len(batches) > LIST_LIMIT:
        lines.append(f"…另有 {len(batches) - LIST_LIMIT} 个批次")
    return ["\n".join(lines)]


def _history(command: Command) -> list[str]:
    records = client_for(command.site).history()
    if not records:
        return [f"🧾 {command.site.name} 暂无兑换记录"]
    lines = [f"🧾 {command.site.name} 最近兑换"]
    for item in records[:LIST_LIMIT]:
        lines.append(f"{_format_time(item.get('used_at'))}  {item.get('used_by') or '-'}  {item.get('card_code') or '-'}")
    return ["\n".join(lines)]


def _revoke(command: Command) -> list[str]:
    message = client_for(command.site).revoke(command.batch_id)
    _record("cards.revoked", command.site, command.batch_id, message)
    logger.info("NextEmby 卡密批次已作废: site=%s batch=%s", command.site.name, command.batch_id)
    return [f"🗑️ {command.site.name} 批次 {command.batch_id}：{message}"]


def _record(event_type: str, site: Site, batch_id: str, summary: str) -> None:
    try:
        from notifyhub.plugins.sdk import record_event

        record_event(event_type, f"{site.slot}:{batch_id}", f"NextEmby {site.name} 卡密", summary)
    except Exception as exc:
        logger.debug("记录卡密事件失败: %s", type(exc).__name__)


HANDLERS = {"generate": _generate, "stock": _stock, "history": _history, "revoke": _revoke}


def handle_command(text: str) -> list[str]:
    command = parse_command(text)
    if command.action == "help":
        return [help_text()]
    if command.error:
        return ["❌ " + command.error]
    try:
        return HANDLERS[command.action](command)
    except NextEmbyError as exc:
        return [f"❌ {exc}"]
