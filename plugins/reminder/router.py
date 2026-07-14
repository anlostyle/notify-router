from fastapi import APIRouter
from typing import Any, Dict, Optional
from datetime import datetime

from notifyhub.common.response import data_to_json, json_with_status

from .config import (
    # Reminder 相关
    list_reminder_configs,
    add_reminder_config,
    update_reminder_config,
    remove_reminder_config,
    get_reminder_config_by_id,
    # Subscribe 相关
    list_subscribe_configs,
    add_subscribe_config,
    update_subscribe_config,
    remove_subscribe_config,
    get_subscribe_config_by_id,
    # 通用
    get_notify_route_list,
)


reminder_router = APIRouter(prefix="/reminder", tags=["reminder"])


def _to_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return int(val) == 1
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "on", "yes", "enabled", "enable"}
    return False


def _validate_onetime_not_past(time_str: str) -> bool:
    patterns = ["%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M"]
    now = datetime.now()
    for fmt in patterns:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt >= now.replace(second=0, microsecond=0)
        except Exception:
            continue
    return False


def _validate_cron(expr: str) -> bool:
    parts = [p for p in (expr or "").split() if p]
    return len(parts) == 5


def _validate_date(date_str: str) -> bool:
    """验证日期格式 YYYY-MM-DD"""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def _validate_bill_cycle(bill_cycle: str) -> bool:
    """验证账单周期是否有效"""
    valid_cycles = {"月", "季", "半年", "年", "两年", "三年"}
    return bill_cycle in valid_cycles


def _validate_lead_time(lead_time: str) -> bool:
    """验证提前提醒时间格式（X天）"""
    if not lead_time:
        return False
    return lead_time.isdigit()


def _normalize_payload(payload: Dict[str, Any], is_update: bool = False) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    reminder_type = (payload.get("reminder_type") or "").strip().lower()
    reminder_time = (payload.get("reminder_time") or "").strip()
    status = _to_bool(payload.get("status"))
    notify_route = (payload.get("notify_route") or "").strip()

    if not title or not content or not reminder_type or not reminder_time or not notify_route:
        return None
    if reminder_type == "onetime":
        if not _validate_onetime_not_past(reminder_time):
            return None
    elif reminder_type == "circle":
        if not _validate_cron(reminder_time):
            return None
    else:
        return None

    # 校验通知通道是否存在
    try:
        route_values = {str(i.get("value")) for i in (get_notify_route_list() or [])}
    except Exception:
        route_values = set()
    if route_values and (notify_route not in route_values):
        return None

    normalized: Dict[str, Any] = {
        "title": title,
        "content": content,
        "status": status,
        "reminder_type": reminder_type,
        "reminder_time": reminder_time,
        "notify_route": notify_route,
    }
    # 允许透传 id（仅更新时使用）
    if is_update and payload.get("id"):
        normalized["id"] = payload.get("id")
    return normalized


def _normalize_subscribe_payload(payload: Dict[str, Any], is_update: bool = False) -> Optional[Dict[str, Any]]:
    """规范化 subscribe 任务 payload"""
    if not isinstance(payload, dict):
        return None
    
    title = (payload.get("title") or "").strip()
    price = payload.get("price")
    currency = (payload.get("currency") or "").strip()
    bill_cycle = (payload.get("bill_cycle") or "").strip()
    start_date = (payload.get("start_date") or "").strip()
    category = (payload.get("category") or "").strip()
    lead_time = (payload.get("lead_time") or "").strip()
    status = _to_bool(payload.get("status"))
    notify_route = (payload.get("notify_route") or "").strip()
    
    # 验证必填字段
    if not title or not currency or not bill_cycle or not start_date or not category or not lead_time or not notify_route:
        return None
    
    # 验证 price
    try:
        price_float = float(price) if price is not None else 0.0
        if price_float < 0:
            return None
    except (ValueError, TypeError):
        return None
    
    # 验证账单周期
    if not _validate_bill_cycle(bill_cycle):
        return None
    
    # 验证开始日期
    if not _validate_date(start_date):
        return None
    
    # 验证提前提醒时间
    if not _validate_lead_time(lead_time):
        return None
    
    # 校验通知通道是否存在
    try:
        route_values = {str(i.get("value")) for i in (get_notify_route_list() or [])}
    except Exception:
        route_values = set()
    if route_values and (notify_route not in route_values):
        return None
    
    normalized: Dict[str, Any] = {
        "title": title,
        "price": price_float,
        "currency": currency,
        "bill_cycle": bill_cycle,
        "start_date": start_date,
        "category": category,
        "lead_time": lead_time,
        "status": status,
        "notify_route": notify_route,
    }
    # 允许透传 id（仅更新时使用）
    if is_update and payload.get("id"):
        normalized["id"] = payload.get("id")
    return normalized


@reminder_router.get("/notify_route")
async def get_notify_route():
    return data_to_json(data=get_notify_route_list())


@reminder_router.get("/reminder")
async def list_reminders():
    return data_to_json(data=list_reminder_configs())


@reminder_router.get("/reminder/{reminder_id}")
async def get_reminder(reminder_id: str):
    item = get_reminder_config_by_id(reminder_id)
    if not item:
        return json_with_status(404, message="reminder not found")
    return data_to_json(data=item)


@reminder_router.post("/reminder")
async def create_reminder(payload: Dict[str, Any]):
    normalized = _normalize_payload(payload, is_update=False)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    created = add_reminder_config(normalized)
    return data_to_json(data=created)


@reminder_router.put("/reminder/{reminder_id}")
async def update_reminder(reminder_id: str, payload: Dict[str, Any]):
    if not get_reminder_config_by_id(reminder_id):
        return json_with_status(404, message="reminder not found")
    payload = dict(payload or {})
    payload["id"] = reminder_id
    normalized = _normalize_payload(payload, is_update=True)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    updated = update_reminder_config(reminder_id, normalized)
    if not updated:
        return json_with_status(500, message="update failed")
    return data_to_json(data=updated)


@reminder_router.delete("/reminder/{reminder_id}")
async def delete_reminder(reminder_id: str):
    if not get_reminder_config_by_id(reminder_id):
        return json_with_status(404, message="reminder not found")
    ok = remove_reminder_config(reminder_id)
    if not ok:
        return json_with_status(500, message="delete failed")
    return data_to_json(data={"id": reminder_id})


# ==================== Subscribe 相关路由 ====================

@reminder_router.get("/subscribe")
async def list_subscribes():
    """获取所有 subscribe 任务列表"""
    return data_to_json(data=list_subscribe_configs())


@reminder_router.get("/subscribe/{subscribe_id}")
async def get_subscribe(subscribe_id: str):
    """获取单个 subscribe 任务"""
    item = get_subscribe_config_by_id(subscribe_id)
    if not item:
        return json_with_status(404, message="subscribe not found")
    return data_to_json(data=item)


@reminder_router.post("/subscribe")
async def create_subscribe(payload: Dict[str, Any]):
    """创建 subscribe 任务"""
    normalized = _normalize_subscribe_payload(payload, is_update=False)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    created = add_subscribe_config(normalized)
    return data_to_json(data=created)


@reminder_router.put("/subscribe/{subscribe_id}")
async def update_subscribe(subscribe_id: str, payload: Dict[str, Any]):
    """更新 subscribe 任务"""
    if not get_subscribe_config_by_id(subscribe_id):
        return json_with_status(404, message="subscribe not found")
    payload = dict(payload or {})
    payload["id"] = subscribe_id
    normalized = _normalize_subscribe_payload(payload, is_update=True)
    if not normalized:
        return json_with_status(400, message="invalid payload")
    updated = update_subscribe_config(subscribe_id, normalized)
    if not updated:
        return json_with_status(500, message="update failed")
    return data_to_json(data=updated)


@reminder_router.delete("/subscribe/{subscribe_id}")
async def delete_subscribe(subscribe_id: str):
    """删除 subscribe 任务"""
    if not get_subscribe_config_by_id(subscribe_id):
        return json_with_status(404, message="subscribe not found")
    ok = remove_subscribe_config(subscribe_id)
    if not ok:
        return json_with_status(500, message="delete failed")
    return data_to_json(data={"id": subscribe_id})