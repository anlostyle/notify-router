import os
import json
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from notifyhub.controller.server import server

class ReminderConfig(BaseModel):
    id: str
    title: str
    content: str
    reminder_type: str
    reminder_time: str
    status: bool
    notify_route: str

class SubscribeConfig(BaseModel):
    id: str
    title: str
    price: float
    currency: str
    bill_cycle: str
    start_date: str
    category: str
    lead_time: str
    status: bool
    notify_route: str


config_file = os.path.join(os.environ.get("WORKDIR"), "conf", "reminder", "config.json")

# 默认配置结构
DEFAULT_CONFIG = {"reminder": [], "subscribe": []}


def _init_config_file() -> None:
    """初始化配置文件：检查文件存在，不存在则新建，存在则检查格式并迁移"""
    # 确保目录存在
    if not os.path.exists(os.path.dirname(config_file)):
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
    
    # 如果文件不存在，创建默认配置
    if not os.path.exists(config_file):
        _write_config(DEFAULT_CONFIG)
        return
    
    # 文件存在，检查并迁移格式
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 如果已经是新格式，直接返回
        if isinstance(data, dict) and "reminder" in data and "subscribe" in data:
            return
        
        # 如果是旧格式（list），进行迁移
        if isinstance(data, list):
            migrated_config = {
                "reminder": data if isinstance(data, list) else [],
                "subscribe": []
            }
            _write_config(migrated_config)
    except Exception:
        # 如果读取失败，创建默认配置
        _write_config(DEFAULT_CONFIG)


def _read_config() -> Dict[str, Any]:
    """读取配置文件，返回配置字典"""
    if not os.path.exists(config_file):
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "reminder" in data and "subscribe" in data:
                return data
            # 如果不是新格式，返回默认配置
            return DEFAULT_CONFIG.copy()
    except Exception:
        return DEFAULT_CONFIG.copy()


def _write_config(config: Dict[str, Any]) -> None:
    """写入配置文件"""
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# 启动时初始化配置文件
_init_config_file()


def _read_all_reminders() -> List[Dict[str, Any]]:
    """读取所有 reminder 配置"""
    config = _read_config()
    return config.get("reminder", [])


def _write_all_reminders(items: List[Dict[str, Any]]) -> None:
    """写入所有 reminder 配置"""
    config = _read_config()
    config["reminder"] = items
    _write_config(config)


def _read_all_subscribes() -> List[Dict[str, Any]]:
    """读取所有 subscribe 配置"""
    config = _read_config()
    return config.get("subscribe", [])


def _write_all_subscribes(items: List[Dict[str, Any]]) -> None:
    """写入所有 subscribe 配置"""
    config = _read_config()
    config["subscribe"] = items
    _write_config(config)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes", "enabled", "enable"}
    return False


def _coerce_to_reminder_model(raw: Dict[str, Any]) -> ReminderConfig:
    """将原始数据转换为 ReminderConfig 模型"""
    data: Dict[str, Any] = {
        "id": (raw.get("id") or uuid.uuid4().hex),
        "title": (raw.get("title") or "").strip(),
        "content": (raw.get("content") or "").strip(),
        "reminder_type": (raw.get("reminder_type") or "").strip().lower(),
        "reminder_time": (raw.get("reminder_time") or "").strip(),
        "status": _to_bool(raw.get("status")),
        "notify_route": (raw.get("notify_route") or "").strip(),
    }
    return ReminderConfig(**data)


def _coerce_to_subscribe_model(raw: Dict[str, Any]) -> SubscribeConfig:
    """将原始数据转换为 SubscribeConfig 模型"""
    data: Dict[str, Any] = {
        "id": (raw.get("id") or uuid.uuid4().hex),
        "title": (raw.get("title") or "").strip(),
        "price": float(raw.get("price") or 0),
        "currency": (raw.get("currency") or "").strip(),
        "bill_cycle": (raw.get("bill_cycle") or "").strip(),
        "start_date": (raw.get("start_date") or "").strip(),
        "category": (raw.get("category") or "").strip(),
        "lead_time": (raw.get("lead_time") or "").strip(),
        "status": _to_bool(raw.get("status")),
        "notify_route": (raw.get("notify_route") or "").strip(),
    }
    return SubscribeConfig(**data)


# ==================== Reminder 相关函数 ====================

def list_reminder_configs() -> List[Dict[str, Any]]:
    """获取所有 reminder 配置"""
    items = _read_all_reminders()
    models: List[ReminderConfig] = []
    for it in items:
        if isinstance(it, dict):
            try:
                models.append(_coerce_to_reminder_model(it))
            except Exception:
                continue
    return [m.model_dump() for m in models]


def get_reminder_config_by_id(config_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取 reminder 配置"""
    for item in _read_all_reminders():
        if isinstance(item, dict) and item.get("id") == config_id:
            try:
                return _coerce_to_reminder_model(item).model_dump()
            except Exception:
                return None
    return None


def add_reminder_config(config_item: Dict[str, Any]) -> Dict[str, Any]:
    """添加 reminder 配置"""
    items = _read_all_reminders()
    if not isinstance(config_item, dict):
        raise ValueError("config_item must be a dict")
    model = _coerce_to_reminder_model(config_item)
    items.append(model.model_dump())
    _write_all_reminders(items)
    return model.model_dump()


def update_reminder_config(config_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新 reminder 配置"""
    items = _read_all_reminders()
    updated_item: Optional[Dict[str, Any]] = None
    new_items: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") == config_id:
            merged_raw = {**item, **(updates or {}), "id": config_id}
            try:
                model = _coerce_to_reminder_model(merged_raw)
            except Exception:
                return None
            updated_item = model.model_dump()
            new_items.append(updated_item)
        else:
            new_items.append(item)
    if updated_item is None:
        return None
    _write_all_reminders(new_items)
    return updated_item


def remove_reminder_config(config_id: str) -> bool:
    """删除 reminder 配置"""
    items = _read_all_reminders()
    new_items = [item for item in items if not (isinstance(item, dict) and item.get("id") == config_id)]
    if len(new_items) == len(items):
        return False
    _write_all_reminders(new_items)
    return True


def replace_reminder_configs(config_items: List[Dict[str, Any]]) -> None:
    """替换所有 reminder 配置"""
    if not isinstance(config_items, list):
        raise ValueError("config_items must be a list of dicts")
    _write_all_reminders(config_items)


# ==================== Subscribe 相关函数 ====================

def list_subscribe_configs() -> List[Dict[str, Any]]:
    """获取所有 subscribe 配置"""
    items = _read_all_subscribes()
    models: List[SubscribeConfig] = []
    for it in items:
        if isinstance(it, dict):
            try:
                models.append(_coerce_to_subscribe_model(it))
            except Exception:
                continue
    return [m.model_dump() for m in models]


def get_subscribe_config_by_id(config_id: str) -> Optional[Dict[str, Any]]:
    """根据 ID 获取 subscribe 配置"""
    for item in _read_all_subscribes():
        if isinstance(item, dict) and item.get("id") == config_id:
            try:
                return _coerce_to_subscribe_model(item).model_dump()
            except Exception:
                return None
    return None


def add_subscribe_config(config_item: Dict[str, Any]) -> Dict[str, Any]:
    """添加 subscribe 配置"""
    items = _read_all_subscribes()
    if not isinstance(config_item, dict):
        raise ValueError("config_item must be a dict")
    model = _coerce_to_subscribe_model(config_item)
    items.append(model.model_dump())
    _write_all_subscribes(items)
    return model.model_dump()


def update_subscribe_config(config_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新 subscribe 配置"""
    items = _read_all_subscribes()
    updated_item: Optional[Dict[str, Any]] = None
    new_items: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and item.get("id") == config_id:
            merged_raw = {**item, **(updates or {}), "id": config_id}
            try:
                model = _coerce_to_subscribe_model(merged_raw)
            except Exception:
                return None
            updated_item = model.model_dump()
            new_items.append(updated_item)
        else:
            new_items.append(item)
    if updated_item is None:
        return None
    _write_all_subscribes(new_items)
    return updated_item


def remove_subscribe_config(config_id: str) -> bool:
    """删除 subscribe 配置"""
    items = _read_all_subscribes()
    new_items = [item for item in items if not (isinstance(item, dict) and item.get("id") == config_id)]
    if len(new_items) == len(items):
        return False
    _write_all_subscribes(new_items)
    return True


def replace_subscribe_configs(config_items: List[Dict[str, Any]]) -> None:
    """替换所有 subscribe 配置"""
    if not isinstance(config_items, list):
        raise ValueError("config_items must be a list of dicts")
    _write_all_subscribes(config_items)


def get_notify_route_list() -> List[Dict[str, Any]]:
    return server.router_list