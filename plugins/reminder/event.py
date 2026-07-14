import logging
import calendar
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from notifyhub.controller.server import server

from .config import list_reminder_configs, update_reminder_config, list_subscribe_configs

logger = logging.getLogger(__name__)


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        v = value.strip().lower()
        return v in {"enabled", "enable", "true", "on", "1", "yes"}
    return False


def _parse_int(token: str) -> Optional[int]:
    try:
        return int(token)
    except Exception:
        return None


def _expand_cron_field(field: str, min_v: int, max_v: int) -> Set[int]:
    field = field.strip()
    results: Set[int] = set()

    if field == "*":
        return set(range(min_v, max_v + 1))

    parts = field.split(",")
    for part in parts:
        part = part.strip()
        if part == "*":
            results.update(range(min_v, max_v + 1))
            continue
        if part.startswith("*/"):
            step = _parse_int(part[2:])
            if step and step > 0:
                results.update([i for i in range(min_v, max_v + 1) if (i - min_v) % step == 0])
            continue
        # range with optional step: a-b or a-b/n
        if "-" in part:
            range_part, step_part = part, None
            if "/" in part:
                range_part, step_part = part.split("/", 1)
            start_s, end_s = range_part.split("-", 1)
            start = _parse_int(start_s)
            end = _parse_int(end_s)
            step = _parse_int(step_part) if step_part else 1
            if start is not None and end is not None and step and step > 0:
                if start > end:
                    continue
                start = max(start, min_v)
                end = min(end, max_v)
                results.update(range(start, end + 1, step))
            continue
        # single number
        num = _parse_int(part)
        if num is not None and min_v <= num <= max_v:
            results.add(num)
    return results


def _cron_matches_now(expr: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    fields = [f.strip() for f in expr.split()] if expr else []
    if len(fields) != 5:
        return False

    minute_s, hour_s, dom_s, month_s, dow_s = fields

    minutes = _expand_cron_field(minute_s, 0, 59)
    hours = _expand_cron_field(hour_s, 0, 23)
    doms = _expand_cron_field(dom_s, 1, 31)
    months = _expand_cron_field(month_s, 1, 12)

    # Map Python weekday (Mon=0..Sun=6) to cron (Sun=0..Sat=6)
    cron_dow_now = (now.weekday() + 1) % 7
    # Accept 7 as Sunday in expressions → normalize to 0
    dows_raw = _expand_cron_field(dow_s.replace("7", "0"), 0, 6)
    dows = set()
    for d in dows_raw:
        dows.add(0 if d == 7 else d)

    return (
        (now.minute in minutes)
        and (now.hour in hours)
        and (now.day in doms)
        and (now.month in months)
        and (cron_dow_now in dows)
    )


def _onetime_matches_now(time_str: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    patterns = [
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y.%m.%d %H:%M",
    ]
    for fmt in patterns:
        try:
            dt = datetime.strptime(time_str.strip(), fmt)
            if (
                dt.year == now.year
                and dt.month == now.month
                and dt.day == now.day
                and dt.hour == now.hour
                and dt.minute == now.minute
            ):
                return True
        except Exception:
            continue
    return False


def _send_notify_to_route(route_id: str, title: str, content: str):
    server.send_notify_by_router(route_id, title, content)

def _calculate_next_bill_date(start_date_str: str, bill_cycle: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """计算下一次账单日期
    
    Args:
        start_date_str: 开始日期，格式 YYYY-MM-DD
        bill_cycle: 账单周期（月、季、半年、年、两年、三年）
        now: 当前时间，默认为 datetime.now()
    
    Returns:
        下一次账单日期，如果无法计算则返回 None
    
    示例：
        start_date=2024-10-31, bill_cycle="月", now=2024-11-01
        下一个账单日 = 2024-11-30 (10月31日 + 1个月，但11月没有31日，所以是30日)
    """
    now = now or datetime.now()
    
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    except Exception:
        logger.warning("[subscribe] invalid start_date format: %s", start_date_str)
        return None
    
    # 计算周期对应的月数
    cycle_months = {
        "月": 1,
        "季": 3,
        "半年": 6,
        "年": 12,
        "两年": 24,
        "三年": 36,
    }
    
    months = cycle_months.get(bill_cycle)
    if not months:
        logger.warning("[subscribe] invalid bill_cycle: %s", bill_cycle)
        return None
    
    # 计算从开始日期到现在的总月数（考虑日期）
    # 如果当前日期小于开始日期的日期部分，则总月数减1
    total_months = (now.year - start_date.year) * 12 + (now.month - start_date.month)
    if now.day < start_date.day:
        total_months -= 1
    
    # 计算已经过了多少个完整周期
    cycles_passed = total_months // months
    
    # 计算下一次账单日期（下一个周期的开始日期）
    # 从开始日期开始，加上 (cycles_passed + 1) 个周期
    next_cycle_count = cycles_passed + 1
    next_cycle_months = next_cycle_count * months
    
    # 计算目标年月
    year_offset = next_cycle_months // 12
    month_offset = next_cycle_months % 12
    new_year = start_date.year + year_offset
    new_month = start_date.month + month_offset
    
    # 处理月份溢出
    if new_month > 12:
        new_year += 1
        new_month -= 12
    
    # 处理日期溢出（例如 10月31日 + 1个月 = 11月31日，需要调整为11月最后一天）
    try:
        next_bill_date = datetime(new_year, new_month, start_date.day)
    except ValueError:
        # 如果日期无效（如11月31日），使用该月最后一天
        last_day = calendar.monthrange(new_year, new_month)[1]
        next_bill_date = datetime(new_year, new_month, last_day)
    
    # 如果计算出的日期小于等于当前日期，说明需要再加一个周期
    # 这种情况可能发生在当前日期正好是账单日或之后
    if next_bill_date <= now.replace(hour=0, minute=0, second=0, microsecond=0):
        # 再加一个周期
        new_month += months
        if new_month > 12:
            new_year += 1
            new_month -= 12
        
        try:
            next_bill_date = datetime(new_year, new_month, start_date.day)
        except ValueError:
            last_day = calendar.monthrange(new_year, new_month)[1]
            next_bill_date = datetime(new_year, new_month, last_day)
    
    return next_bill_date


def _calculate_reminder_date(next_bill_date: datetime, lead_time_days: int) -> datetime:
    """计算提醒日期（下一次账单日期减去提前天数）"""
    return next_bill_date - timedelta(days=lead_time_days)


def _is_date_in_range(check_date: datetime, start_date: datetime, end_date: datetime) -> bool:
    """判断日期是否在指定范围内（包含头尾）
    
    Args:
        check_date: 要检查的日期
        start_date: 开始日期（包含）
        end_date: 结束日期（包含）
    
    Returns:
        如果 check_date 在 [start_date, end_date] 范围内则返回 True
    """
    # 只比较年月日，忽略时分秒
    check = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return start <= check <= end


class RunCronJob:

    def run_reminder(self):
        """执行 reminder 任务检查"""
        now = datetime.now()
        items: List[Dict[str, Any]] = list_reminder_configs()
        for item in items:
            if not isinstance(item, dict):
                continue
            status = item.get("status")
            if not _is_enabled(status):
                continue

            reminder_type = (item.get("reminder_type") or "").strip().lower()
            reminder_time = (item.get("reminder_time") or "").strip()
            if not reminder_type or not reminder_time:
                continue

            matched = False
            if reminder_type == "onetime":
                matched = _onetime_matches_now(reminder_time, now)
            elif reminder_type == "circle":
                matched = _cron_matches_now(reminder_time, now)
            else:
                continue

            if matched:
                logger.info(
                    "[reminder] matched type=%s time=%s id=%s",
                    reminder_type, reminder_time, item.get("id", ""),
                )
                route_id = item.get("notify_route")
                title = item.get("title")
                content = item.get("content")
                _send_notify_to_route(route_id, title, content)
                # 一次性任务执行后自动禁用
                if reminder_type == "onetime":
                    update_reminder_config(item.get("id"), {"status": False})
                    logger.info("[reminder] disabled onetime task id=%s", item.get("id", ""))
    
    def run_subscribe(self):
        """执行 subscribe 任务检查"""
        now = datetime.now()
        items: List[Dict[str, Any]] = list_subscribe_configs()
        
        for item in items:
            if not isinstance(item, dict):
                continue
            
            item_id = item.get("id", "")
            
            # 1. 获取 status 为 True 的任务
            status = item.get("status")
            if not _is_enabled(status):
                continue
            
            # 获取必要字段
            bill_cycle = (item.get("bill_cycle") or "").strip()
            start_date_str = (item.get("start_date") or "").strip()
            lead_time_str = (item.get("lead_time") or "").strip()
            
            if not bill_cycle or not start_date_str or not lead_time_str:
                logger.warning("[subscribe] missing required fields id=%s", item_id)
                continue
            
            # 2. 计算下一次账单日期
            next_bill_date = _calculate_next_bill_date(start_date_str, bill_cycle, now)
            if not next_bill_date:
                logger.warning("[subscribe] failed to calculate next bill date id=%s", item_id)
                continue
            
            # 3. 计算提醒日期（下一次账单日期的前 lead_time 天）
            try:
                lead_time_days = int(lead_time_str)
            except (ValueError, TypeError):
                logger.warning("[subscribe] invalid lead_time id=%s lead_time=%s", item_id, lead_time_str)
                continue
            
            if lead_time_days <= 0:
                logger.warning("[subscribe] invalid lead_time id=%s lead_time=%s", item_id, lead_time_str)
                continue
            
            reminder_date = _calculate_reminder_date(next_bill_date, lead_time_days)
            
            # 4. 判断当前日期是否在提醒日期和账单日期之间（包含头尾）
            if _is_date_in_range(now, reminder_date, next_bill_date):
                logger.info(
                    "[subscribe] matched title=%s reminder_date=%s bill_date=%s current_date=%s",
                    item.get("title", ""), reminder_date.strftime("%Y-%m-%d"),
                    next_bill_date.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"),
                )
                
                # 构建通知内容
                subscribe_title = item.get('title', '')
                title = "订阅到期提醒: " + subscribe_title
                price = item.get("price", 0)
                currency = item.get("currency", "")
                category = item.get("category", "")
                
                # 计算距离账单日期的剩余天数
                days_until_bill = (next_bill_date - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
                
                content = f"订阅{subscribe_title}将于{days_until_bill}天后到期\n"
                content += f"这是第{lead_time_days - days_until_bill + 1}次提醒\n"
                content += f"💰 金额：{price} {currency} / {bill_cycle}\n"
                content += f"📅 账单日期：{next_bill_date.strftime('%Y-%m-%d')}\n"
                if category:
                    content += f"📂 分类：{category}"
                
                route_id = item.get("notify_route")
                if route_id:
                    _send_notify_to_route(route_id, title, content)
                else:
                    logger.warning("[subscribe] no notify_route configured id=%s", item_id)


run_cron_job = RunCronJob()