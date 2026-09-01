import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import signal
import threading
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import uvicorn
import httpx
from .channels import send
from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from .builtin_plugins import register_builtin_plugins
from .controller.schedule import start_scheduler, stop_scheduler
from .controller.server import Server
from .plugin_supervisor import PluginSupervisor
from .plugin_store import PluginStore, _validate_remote_url
from .plugins.common import run_after_setup_hooks
from .service_compat import normalize_escaped_line_breaks, parse_emby, parse_pve, parse_watchtower, registered_event_types
from .store import Store, enabled, redact_secret_text
from .worker import DeliveryWorker
from .modules.monitor.api import build_monitor_router
from .modules.tasks.api import build_task_router


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("notifyhub")
LOG_BUFFER = deque(maxlen=500)


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        LOG_BUFFER.append(
            {
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "logger": record.name,
                "message": redact_secret_text(self.format(record)),
            }
        )


if not any(isinstance(handler, MemoryLogHandler) for handler in logging.getLogger().handlers):
    logging.getLogger().addHandler(MemoryLogHandler())

DATA_DIR = Path(os.environ.get("WORKDIR", "/data"))
os.environ.setdefault("WORKDIR", str(DATA_DIR))
store = Store(DATA_DIR)
Server.configure(store)
worker = DeliveryWorker(store)
plugin_store = PluginStore(store)
plugin_supervisor = PluginSupervisor(store)
security = HTTPBasic(auto_error=False)
SESSION_COOKIE = "notify_session"
LOGIN_FAILURES = deque(maxlen=1000)
LOGIN_LOCK = threading.Lock()
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "password"
PASSWORD_HASH_ITERATIONS = 310_000
SECURITY_LOCK = threading.RLock()


@asynccontextmanager
async def lifespan(_app):
    if not os.environ.get("NH_PASSWORD") or os.environ.get("NH_PASSWORD") in {DEFAULT_ADMIN_PASSWORD, "change-me"}:
        logger.warning("NH_PASSWORD is missing or still uses the default value; change it in the management console")
    if not os.environ.get("SESSION_SECRET"):
        logger.warning("SESSION_SECRET is unset; session signing falls back to NH_PASSWORD")
    worker.start()
    plugin_tasks = enabled(os.environ.get("PLUGIN_TASKS_ENABLED", "1"))
    if plugin_tasks:
        start_scheduler()
        await run_after_setup_hooks(logger)
    else:
        logger.info("plugin background tasks disabled")
    await asyncio.to_thread(plugin_supervisor.start_all)
    yield
    await asyncio.to_thread(plugin_supervisor.stop_all)
    if plugin_tasks:
        stop_scheduler()
    worker.stop()


app = FastAPI(title="Notify Router", version=__version__, lifespan=lifespan)
LEGACY_COVER_URL = "https://nanako-1253183981.cos.ap-guangzhou.myqcloud.com/project/notifyhub/coverimg"


class NotifyRequest(BaseModel):
    route_id: str
    title: str
    content: str
    push_img_url: str | None = None
    push_link_url: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class TestNotification(BaseModel):
    title: str = "Notify 测试通知"
    content: str = "通知渠道连接正常。"
    push_img_url: str | None = None
    push_link_url: str | None = None
    probe: bool = False


class PluginSourcesRequest(BaseModel):
    sources: list[str]


class PluginInstallRequest(BaseModel):
    source_url: str
    plugin_id: str


def api_auth(authorization: str | None = Header(default=None)):
    token = os.environ.get("NOTIFY_API_TOKEN", "")
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "invalid API token")


def _security_path():
    return store.conf_dir / "security.json"


def _read_security():
    path = _security_path()
    with SECURITY_LOCK:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}


def _save_security(value):
    path = _security_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with SECURITY_LOCK:
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, path)
            path.chmod(0o600)
        finally:
            temporary.unlink(missing_ok=True)


def _hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password, encoded):
    try:
        algorithm, iterations, salt_hex, digest_hex = str(encoded).split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations)
        if not 10_000 <= iterations <= 1_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _admin_user():
    return os.environ.get("NH_USER") or DEFAULT_ADMIN_USER


def _admin_password():
    return os.environ.get("NH_PASSWORD") or DEFAULT_ADMIN_PASSWORD


def _password_change_required():
    security_data = _read_security()
    if security_data.get("password_hash"):
        return False
    return _admin_password() in {DEFAULT_ADMIN_PASSWORD, "change-me"}


def _session_version():
    try:
        return max(0, int(_read_security().get("session_version", 0)))
    except (TypeError, ValueError):
        return 0


def _session_signing_key():
    configured = os.environ.get("SESSION_SECRET", "").strip()
    if configured:
        return configured
    persisted = str(_read_security().get("session_secret") or "").strip()
    return persisted or _admin_password()


def _persist_admin_password(password):
    security_data = _read_security()
    security_data["password_hash"] = _hash_password(password)
    security_data["password_changed_at"] = int(time.time())
    security_data["session_version"] = _session_version() + 1
    if not os.environ.get("SESSION_SECRET") and not security_data.get("session_secret"):
        security_data["session_secret"] = secrets.token_hex(32)
    _save_security(security_data)


def _valid_admin(username, password):
    if not hmac.compare_digest(username or "", _admin_user()):
        return False
    persisted_hash = _read_security().get("password_hash")
    if persisted_hash:
        return _verify_password(password or "", persisted_hash)
    return hmac.compare_digest(password or "", _admin_password())


def _login_blocked(client):
    now = time.monotonic()
    with LOGIN_LOCK:
        recent = [(host, stamp) for host, stamp in LOGIN_FAILURES if stamp > now - 300]
        LOGIN_FAILURES.clear()
        LOGIN_FAILURES.extend(recent)
        return sum(host == client for host, _ in recent) >= 10


def _login_failed(client):
    with LOGIN_LOCK:
        LOGIN_FAILURES.append((client, time.monotonic()))


def _login_succeeded(client):
    with LOGIN_LOCK:
        recent = [(host, stamp) for host, stamp in LOGIN_FAILURES if host != client]
        LOGIN_FAILURES.clear()
        LOGIN_FAILURES.extend(recent)


def _session_token(username, expires=None):
    expires = expires or int(time.time()) + 86400 * 30
    payload = urlsafe_b64encode(f"{username}:{expires}:{_session_version()}".encode()).decode().rstrip("=")
    key = _session_signing_key()
    signature = hmac.new(key.encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}.{signature}"


def _valid_session(token):
    try:
        payload, signature = token.split(".", 1)
        key = _session_signing_key()
        expected = hmac.new(key.encode(), payload.encode(), "sha256").hexdigest()
        if not key or not hmac.compare_digest(signature, expected):
            return False
        raw = urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        parts = raw.rsplit(":", 2)
        if len(parts) == 3:
            username, expires, version = parts
            if int(version) != _session_version():
                return False
        else:
            username, expires = raw.rsplit(":", 1)
            if _session_version() != 0:
                return False
        return username == _admin_user() and int(expires) > time.time()
    except (AttributeError, ValueError, TypeError, OverflowError):
        return False


def admin_auth(credentials: HTTPBasicCredentials | None = Depends(security), notify_session: str | None = Cookie(default=None)):
    if _valid_session(notify_session):
        return
    if credentials and _valid_admin(credentials.username, credentials.password):
        return
    raise HTTPException(401, "authentication required")


def enqueue(payload):
    route = active_route(payload.route_id)
    if not route:
        return notify_error(f"未找到或未激活的通道: {payload.route_id}")
    title = payload.title
    offline_suffix = " 又有设备离线啦～"
    if route.get("route_name") == "哪吒监控" and title.endswith(offline_suffix):
        if title.startswith("[事件] "):
            title = f"🔴 设备离线｜{title.removeprefix('[事件] ').removesuffix(offline_suffix)}"
        elif title.startswith("[恢复] "):
            title = f"✅ 设备恢复｜{title.removeprefix('[恢复] ').removesuffix(offline_suffix)}"
        monitor_status = "up" if title.startswith("✅") else "down"
        monitor_name = title.split("｜", 1)[-1]
        entity = "nezha:" + hashlib.sha256(payload.route_id.encode()).hexdigest()[:12]
        store.update_monitor("nezha", entity, monitor_name, "host", monitor_status, title)
    try:
        store.enqueue_router(
            payload.route_id,
            title,
            normalize_escaped_line_breaks(payload.content),
            payload.push_img_url,
            payload.push_link_url,
        )
    except KeyError as exc:
        return notify_error(f"未找到或未激活的通道: {payload.route_id}")
    except ValueError as exc:
        return notify_error(str(exc))
    return {
        "success": True,
        "errorCode": 0,
        "message": "通知已进入发送队列",
        "data": {"route_id": payload.route_id, "channels": list(route.get("channel_name") or [])},
    }


def notify_error(message):
    return JSONResponse({"success": False, "errorCode": 1, "message": message}, status_code=400)


def active_route(route_id):
    route = store.route(route_id)
    return route if route and enabled(route.get("active", True)) else None


def classify_pve_status(value):
    normalized = str(value or "").strip().lower()
    failed_words = ("failed", "failure", "error", "aborted", "timeout")
    success_words = ("successful", "success", "completed", "complete", " ok", "ok ")
    if any(word in normalized for word in failed_words):
        return "error"
    if normalized == "ok" or any(word in normalized for word in success_words):
        return "healthy"
    return "warning"


def enqueue_event(route_id, event, template_type, context, message, push_img_url=None, push_link_url=None, fallback_img_url=None):
    route = active_route(route_id)
    if not route:
        return notify_error(f"未找到或未激活的通道: {route_id}")
    try:
        title, content = store.render_event(route, template_type, context)
        image = (route.get("push_img") or fallback_img_url) if push_img_url is None else push_img_url
        store.enqueue_router(route_id, title, content, image, push_link_url)
    except ValueError as exc:
        return notify_error(str(exc))
    return {
        "success": True,
        "errorCode": 0,
        "message": message,
        "data": {
            "route_id": route_id,
            "event": event,
            "template_type": template_type,
            "channels": list(route.get("channel_name") or []),
        },
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


@app.post("/api/admin/login")
def admin_login(payload: LoginRequest, response: Response, request: Request):
    client = request.client.host if request.client else "unknown"
    if _login_blocked(client):
        raise HTTPException(429, "登录尝试过多，请5分钟后重试", headers={"Retry-After": "300"})
    if not _valid_admin(payload.username, payload.password):
        _login_failed(client)
        raise HTTPException(401, "用户名或密码错误")
    _login_succeeded(client)
    response.set_cookie(
        SESSION_COOKIE,
        _session_token(payload.username),
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
        secure=enabled(os.environ.get("COOKIE_SECURE", "0")),
    )
    return {
        "authenticated": True,
        "username": payload.username,
        "password_change_required": _password_change_required(),
    }


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@app.get("/api/admin/session")
def admin_session(notify_session: str | None = Cookie(default=None)):
    return {
        "authenticated": _valid_session(notify_session),
        "username": _admin_user(),
        "password_change_required": _password_change_required(),
    }


@app.post("/api/admin/password", dependencies=[Depends(admin_auth)])
def change_admin_password(payload: PasswordChangeRequest):
    if not _valid_admin(_admin_user(), payload.current_password):
        raise HTTPException(400, "当前密码错误")
    if len(payload.new_password) < 8:
        raise HTTPException(400, "新密码至少需要 8 个字符")
    if payload.new_password != payload.confirm_password:
        raise HTTPException(400, "两次输入的新密码不一致")
    if hmac.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(400, "新密码不能与当前密码相同")
    _persist_admin_password(payload.new_password)
    LOGIN_FAILURES.clear()
    return {
        "code": 0,
        "message": "管理员密码已更新",
        "password_change_required": False,
        "session_invalidated": True,
    }


@app.post("/api/service/notify", dependencies=[Depends(api_auth)])
def notify(
    payload: object = Body(default=None),
    route_id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    push_img_url: str | None = None,
    push_link_url: str | None = None,
):
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return notify_error("请求体不是合法的JSON格式")
    query_values = {
        "route_id": route_id,
        "title": title,
        "content": content,
        "push_img_url": push_img_url,
        "push_link_url": push_link_url,
    }
    payload = {**{key: value for key, value in query_values.items() if value is not None}, **payload}
    resolved_route_id = payload.get("route_id")
    if resolved_route_id and not active_route(resolved_route_id):
        return notify_error(f"未找到或未激活的通道: {resolved_route_id}")
    try:
        return enqueue(NotifyRequest.model_validate(payload))
    except ValidationError:
        return notify_error("请求体不是合法的JSON格式")


@app.get("/api/service/notify", dependencies=[Depends(api_auth)])
def notify_query(route_id: str, title: str, content: str, push_img_url: str | None = None, push_link_url: str | None = None):
    return enqueue(NotifyRequest(route_id=route_id, title=title, content=content, push_img_url=push_img_url, push_link_url=push_link_url))


@app.api_route("/api/service/notify/{route_id}/{title}/{content}", methods=["GET", "POST"], dependencies=[Depends(api_auth)])
async def bark_compatible(route_id: str, title: str, content: str, request: Request):
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
    return enqueue(
        NotifyRequest(
            route_id=route_id,
            title=title,
            content=content,
            push_img_url=body.get("push_img_url"),
            push_link_url=body.get("push_link_url"),
        )
    )


@app.api_route("/api/service/emby/notify/{route_id}", methods=["GET", "POST"], dependencies=[Depends(api_auth)])
async def emby_compatible(route_id: str, request: Request):
    if request.method == "GET":
        return None
    if not active_route(route_id):
        return notify_error(f"未找到或未激活的通道: {route_id}")
    try:
        payload = await request.json()
        payload_data = payload if isinstance(payload, dict) else {}
        emby_url = str(request.query_params.get("emby_url") or payload_data.get("emby_url") or "").rstrip("/")
        event, template_type, context = parse_emby(payload, emby_url=emby_url)
    except (ValueError, TypeError) as exc:
        return notify_error(str(exc))
    item = payload.get("Item") or {}
    image_id = item.get("SeriesId") if item.get("Type") in {"Episode", "Season"} else item.get("Id")
    image_id = image_id or item.get("Id")
    emby_url = str(request.query_params.get("emby_url") or "").rstrip("/")
    push_img_url = payload.get("push_img_url")
    if not push_img_url and image_id and emby_url.startswith(("http://", "https://")):
        push_img_url = f"{emby_url}/emby/Items/{quote(str(image_id), safe='')}/Images/Primary"
    push_link_url = payload.get("push_link_url") or context.get("item_url") or context.get("server_url")
    return enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "Emby事件通知已进入发送队列",
        push_img_url,
        push_link_url,
        f"{LEGACY_COVER_URL}/EmbyNotify.png",
    )


@app.api_route("/api/service/watchtower/notify/{route_id}", methods=["GET", "POST"], dependencies=[Depends(api_auth)])
async def watchtower_compatible(route_id: str, request: Request):
    if request.method == "GET":
        return None
    if not active_route(route_id):
        return notify_error(f"未找到或未激活的通道: {route_id}")
    try:
        payload = await request.json()
        event, template_type, context = parse_watchtower(payload)
    except (ValueError, TypeError) as exc:
        return notify_error(str(exc))
    result = enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "Watchtower事件通知已进入发送队列",
        payload.get("push_img_url"),
        payload.get("push_link_url"),
        f"{LEGACY_COVER_URL}/Watchtower.png",
    )
    entity = "watchtower:" + hashlib.sha256(route_id.encode()).hexdigest()[:12]
    server_name = str(context.get("server_name") or "默认实例")
    store.update_monitor("watchtower", entity, f"Watchtower · {server_name}", "container", "healthy", "Watchtower 已上报容器镜像检查结果")
    return result


@app.api_route("/api/service/pve/notify/{route_id}", methods=["GET"], dependencies=[Depends(api_auth)])
@app.api_route("/api/service/pve/notify/{route_id}/message", methods=["GET", "POST"], dependencies=[Depends(api_auth)])
async def pve_compatible(route_id: str, request: Request):
    if request.method == "GET":
        return None
    if not active_route(route_id):
        return notify_error(f"未找到或未激活的通道: {route_id}")
    payload = {}
    try:
        payload = await request.json()
        event, template_type, context = parse_pve(payload)
    except (ValueError, TypeError) as exc:
        if isinstance(payload, dict) and (payload.get("title") or payload.get("message")):
            return enqueue(
                NotifyRequest(
                    route_id=route_id,
                    title=str(payload.get("title") or "PVE"),
                    content=str(payload.get("message") or payload.get("title") or ""),
                )
            )
        return notify_error(str(exc))
    result = enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "PVE事件通知已进入发送队列",
        fallback_img_url=f"{LEGACY_COVER_URL}/PVEBackup.png",
    )
    task_status = str(context.get("task_status") or "").strip()
    status = classify_pve_status(task_status)
    entity = "pve-backup:" + hashlib.sha256(route_id.encode()).hexdigest()[:12]
    store.update_monitor("pve", entity, str(context.get("machine_name") or "PVE 任务"), "backup", status, f"最近任务状态：{task_status or 'unknown'}")
    return result


@app.get("/api/admin/status", dependencies=[Depends(admin_auth)])
def admin_status():
    return {
        "version": __version__,
        "channels": len(store.channels),
        "routes": len(store.routes),
        "plugins": len(_all_plugin_manifests()),
        "plugin_tasks": enabled(os.environ.get("PLUGIN_TASKS_ENABLED", "1")),
        "admin_restart": enabled(os.environ.get("ADMIN_RESTART_ENABLED", "0")),
        "password_change_required": _password_change_required(),
        "stats": store.dashboard_stats(),
        "deliveries": store.delivery_status(25),
    }


@app.get("/api/admin/config", dependencies=[Depends(admin_auth)])
def admin_config():
    return store.config


@app.put("/api/admin/config", dependencies=[Depends(admin_auth)])
def save_config(payload: dict = Body(...)):
    try:
        store.save_config(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"code": 0, "message": "saved"}


@app.get("/api/admin/templates", dependencies=[Depends(admin_auth)])
def templates():
    return {"template": store.templates}


@app.get("/api/admin/event-types", dependencies=[Depends(admin_auth)])
def event_types():
    return {"event_types": registered_event_types()}


@app.put("/api/admin/templates", dependencies=[Depends(admin_auth)])
def save_templates(payload: dict = Body(...)):
    try:
        store.save_templates(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"code": 0, "message": "saved"}


@app.get("/api/admin/records", dependencies=[Depends(admin_auth)])
def records(limit: int = 100):
    return store.recent_records(max(1, min(limit, 500)))


@app.get("/api/admin/deliveries", dependencies=[Depends(admin_auth)])
def deliveries(limit: int = 100, status: str | None = None, route_id: str | None = None, channel_name: str | None = None, error: str | None = None, date_from: str | None = None, date_to: str | None = None):
    if status not in {None, "pending", "processing", "retry", "sent", "failed"}:
        raise HTTPException(400, "invalid delivery status")
    return store.delivery_status(max(1, min(limit, 500)), status, route_id, channel_name, error, date_from, date_to)


@app.post("/api/admin/deliveries/{delivery_id}/retry", dependencies=[Depends(admin_auth)])
def retry_delivery(delivery_id: int):
    if not store.retry_failed(delivery_id):
        raise HTTPException(404, "failed delivery not found")
    return {"code": 0, "message": "queued"}


@app.post("/api/admin/channels/{channel_name}/test", dependencies=[Depends(admin_auth)])
def test_channel(channel_name: str, payload: TestNotification):
    channel = store.channel(channel_name)
    if not channel:
        raise HTTPException(404, "channel not found")
    if payload.probe:
        started = time.perf_counter()
        try:
            send(channel, {"title": payload.title, "content": payload.content, "push_img_url": payload.push_img_url, "push_link_url": payload.push_link_url})
            return {"code": 0, "message": "connection ok", "elapsed_ms": round((time.perf_counter() - started) * 1000), "status": 200}
        except Exception as exc:
            return JSONResponse({"code": 1, "message": "connection failed", "elapsed_ms": round((time.perf_counter() - started) * 1000), "error": redact_secret_text(exc)}, status_code=502)
    try:
        outbox_id = store.enqueue_channel(
            channel_name,
            payload.title,
            payload.content,
            payload.push_img_url,
            payload.push_link_url,
        )
    except KeyError as exc:
        raise HTTPException(404, "channel not found") from exc
    return {"code": 0, "message": "queued", "outbox_id": outbox_id}


@app.get("/api/admin/export", dependencies=[Depends(admin_auth)])
def export_config():
    return {
        "version": 1,
        "config": store.config,
        "templates": {"template": store.templates},
        "plugins": store.list_plugin_configs(),
    }


@app.put("/api/admin/import", dependencies=[Depends(admin_auth)])
def import_config(payload: dict = Body(...)):
    config = payload.get("config")
    templates = payload.get("templates")
    if not isinstance(config, dict) or not isinstance(templates, dict):
        raise HTTPException(400, "导入文件必须包含 config 和 templates")
    plugins = payload.get("plugins")
    try:
        Store.validate_config(config)
        Store.validate_templates(templates)
        Store.validate_plugin_configs(plugins)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    original_config = store.config_path.read_bytes()
    original_templates = store.templates_path.read_bytes()
    try:
        store.save_config(config)
        store.save_templates(templates)
        store.save_plugin_configs(plugins)
    except Exception:
        # Both files are restored if a later write fails, so an import cannot
        # leave the instance with only half of the uploaded bundle applied.
        store.config_path.write_bytes(original_config)
        store.templates_path.write_bytes(original_templates)
        raise
    return {"code": 0, "message": "imported"}


@app.get("/api/admin/logs", dependencies=[Depends(admin_auth)])
def logs(limit: int = 200):
    return list(LOG_BUFFER)[-max(1, min(limit, 500)):]


@app.get("/api/admin/plugins", dependencies=[Depends(admin_auth)])
def plugins():
    return [
        {
            **manifest,
            "has_frontend": (store.plugins_dir / str(manifest.get("id") or "") / "frontend").is_dir(),
            "runtime": "builtin" if manifest in builtin_plugin_manifests else "worker",
            "running": True if manifest in builtin_plugin_manifests else plugin_supervisor.status(str(manifest.get("id") or ""))["running"],
        }
        for manifest in _all_plugin_manifests()
    ]


def _plugin_sources():
    return list(store.config.get("app", {}).get("plugin_sources") or [])


@app.get("/api/admin/plugin-store", dependencies=[Depends(admin_auth)])
def plugin_store_catalog():
    return plugin_store.catalog(_plugin_sources())


@app.put("/api/admin/plugin-store/sources", dependencies=[Depends(admin_auth)])
def save_plugin_sources(payload: PluginSourcesRequest):
    sources = []
    for source in payload.sources:
        source = str(source or "").strip()
        if not source or source in sources:
            continue
        try:
            _validate_remote_url(source)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        sources.append(source)
    if len(sources) > 10:
        raise HTTPException(400, "最多可添加 10 个插件源")
    config = store.config
    config["app"] = {**config.get("app", {}), "plugin_sources": sources}
    store.save_config(config)
    return {"code": 0, "message": "saved", "sources": sources}


@app.post("/api/admin/plugin-store/install", dependencies=[Depends(admin_auth)])
async def install_plugin(payload: PluginInstallRequest):
    if payload.source_url not in _plugin_sources():
        raise HTTPException(400, "请先添加并保存该插件源")
    try:
        result = await asyncio.to_thread(plugin_store.install, payload.source_url, payload.plugin_id)
        try:
            hot = await asyncio.to_thread(plugin_supervisor.reload, payload.plugin_id)
        except Exception as exc:
            if result.get("backup"):
                await asyncio.to_thread(plugin_store.restore, payload.plugin_id, result["backup"])
            else:
                await asyncio.to_thread(plugin_store.uninstall, payload.plugin_id)
            logger.exception("plugin hot update failed and was rolled back: %s", payload.plugin_id)
            raise HTTPException(400, f"插件热更新失败，已自动回滚: {exc}") from exc
        return {**result, **hot, "backup": result.get("backup")}
    except KeyError as exc:
        raise HTTPException(404, "插件源中没有找到该插件") from exc
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/admin/plugin-store/plugins/{plugin_id}", dependencies=[Depends(admin_auth)])
async def uninstall_plugin(plugin_id: str):
    try:
        result = await asyncio.to_thread(plugin_store.uninstall, plugin_id)
        await asyncio.to_thread(plugin_supervisor.stop, plugin_id)
        return {**result, "hot_applied": True, "restart_required": False}
    except KeyError as exc:
        raise HTTPException(404, "插件未安装") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _restart_process():
    time.sleep(0.75)
    os.kill(os.getpid(), signal.SIGTERM)


@app.post("/api/admin/restart", dependencies=[Depends(admin_auth)], status_code=202)
def restart_service():
    if not enabled(os.environ.get("ADMIN_RESTART_ENABLED", "0")):
        raise HTTPException(403, "当前部署未启用管理后台重启")
    threading.Thread(target=_restart_process, name="admin-restart", daemon=True).start()
    return {"code": 0, "message": "restarting"}


@app.get("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def plugin_config(plugin_id: str):
    return store.get_plugin_config(plugin_id)


@app.put("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def save_plugin_config(plugin_id: str, payload: dict = Body(...)):
    manifest = next((x for x in _all_plugin_manifests() if x.get("id") == plugin_id), None)
    if not manifest:
        raise HTTPException(404, "plugin not found")
    store.save_plugin_config(
        plugin_id,
        manifest.get("name") or plugin_id,
        payload,
        1,
    )
    return {"code": 0, "message": "saved"}


builtin_plugin_manifests = register_builtin_plugins(app, store)
app.include_router(build_monitor_router(store, admin_auth))
app.include_router(build_task_router(store, admin_auth))


@app.api_route("/api/plugins/{plugin_id}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def plugin_proxy(plugin_id: str, path: str, request: Request):
    return await plugin_supervisor.proxy(plugin_id, path, request)


STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


def _all_plugin_manifests():
    return builtin_plugin_manifests + plugin_supervisor.manifests


def main():
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5400")),
        access_log=enabled(os.environ.get("ACCESS_LOG", "0")),
    )


if __name__ == "__main__":
    main()
