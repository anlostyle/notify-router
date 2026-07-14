import hmac
import json
import logging
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import __version__
from .builtin_plugins import register_builtin_plugins
from .controller.schedule import start_scheduler, stop_scheduler
from .controller.server import Server
from .plugin_loader import PluginLoader
from .plugins.common import run_after_setup_hooks
from .service_compat import parse_emby, parse_pve, parse_watchtower
from .store import Store, enabled, redact_secret_text
from .worker import DeliveryWorker


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
security = HTTPBasic(auto_error=False)
MASK = "••••••"
SESSION_COOKIE = "notify_session"


@asynccontextmanager
async def lifespan(_app):
    worker.start()
    plugin_tasks = enabled(os.environ.get("PLUGIN_TASKS_ENABLED", "1"))
    if plugin_tasks:
        start_scheduler()
        await run_after_setup_hooks(logger)
    else:
        logger.info("plugin background tasks disabled")
    yield
    if plugin_tasks:
        stop_scheduler()
    worker.stop()


app = FastAPI(title="Notify Router", version=__version__, lifespan=lifespan)


class NotifyRequest(BaseModel):
    route_id: str
    title: str
    content: str
    push_img_url: str | None = None
    push_link_url: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TestNotification(BaseModel):
    title: str = "Notify 测试通知"
    content: str = "通知渠道连接正常。"
    push_img_url: str | None = None
    push_link_url: str | None = None


def api_auth(authorization: str | None = Header(default=None)):
    token = os.environ.get("NOTIFY_API_TOKEN", "")
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "invalid API token")


def _valid_admin(username, password):
    expected_user = os.environ.get("NH_USER", "admin")
    expected_password = os.environ.get("NH_PASSWORD", "")
    return hmac.compare_digest(username or "", expected_user) and hmac.compare_digest(password or "", expected_password)


def _session_token(username, expires=None):
    expires = expires or int(time.time()) + 86400 * 30
    payload = urlsafe_b64encode(f"{username}:{expires}".encode()).decode().rstrip("=")
    key = os.environ.get("SESSION_SECRET") or os.environ.get("NH_PASSWORD", "")
    signature = hmac.new(key.encode(), payload.encode(), "sha256").hexdigest()
    return f"{payload}.{signature}"


def _valid_session(token):
    try:
        payload, signature = token.split(".", 1)
        key = os.environ.get("SESSION_SECRET") or os.environ.get("NH_PASSWORD", "")
        expected = hmac.new(key.encode(), payload.encode(), "sha256").hexdigest()
        if not key or not hmac.compare_digest(signature, expected):
            return False
        raw = urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode()
        username, expires = raw.rsplit(":", 1)
        return username == os.environ.get("NH_USER", "admin") and int(expires) > time.time()
    except (AttributeError, ValueError, TypeError):
        return False


def admin_auth(credentials: HTTPBasicCredentials | None = Depends(security), notify_session: str | None = Cookie(default=None)):
    if _valid_session(notify_session):
        return
    if credentials and _valid_admin(credentials.username, credentials.password):
        return
    raise HTTPException(401, "authentication required")


def _secret_key(key):
    key = str(key).lower().replace("-", "_")
    return key in {"key", "authorization", "webhook_url"} or any(
        part in key for part in ("secret", "token", "password", "api_key", "apikey", "aeskey")
    )


def _redact(value, key=""):
    if _secret_key(key) and value not in (None, ""):
        return MASK
    if isinstance(value, dict):
        result = {name: _redact(item, name) for name, item in value.items()}
        channel_type = str(value.get("type") or "").lower()
        if channel_type in {"webhook", "discord", "dingtalk", "bark"} and isinstance(result.get("config"), dict):
            for name in {"url", "webhook_url", "push_url"}:
                if result["config"].get(name):
                    result["config"][name] = MASK
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _merge_masked(value, current):
    if value == MASK:
        return current
    if isinstance(value, dict):
        previous = current if isinstance(current, dict) else {}
        return {key: _merge_masked(item, previous.get(key)) for key, item in value.items()}
    if isinstance(value, list):
        previous = current if isinstance(current, list) else []
        identity = next(
            (key for key in ("name", "route_id", "id", "plugin_id") if any(isinstance(item, dict) and key in item for item in value)),
            None,
        )
        by_identity = {
            item.get(identity): item for item in previous if identity and isinstance(item, dict) and identity in item
        }
        return [
            _merge_masked(
                item,
                by_identity.get(item.get(identity), {})
                if identity and isinstance(item, dict)
                else (previous[index] if index < len(previous) else None),
            )
            for index, item in enumerate(value)
        ]
    return value


def enqueue(payload):
    route = active_route(payload.route_id)
    if not route:
        return notify_error(f"未找到或未激活的通道: {payload.route_id}")
    try:
        store.enqueue_router(
            payload.route_id,
            payload.title,
            payload.content,
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


def enqueue_event(route_id, event, template_type, context, message, push_img_url=None, push_link_url=None):
    route = active_route(route_id)
    if not route:
        return notify_error(f"未找到或未激活的通道: {route_id}")
    try:
        title, content = store.render_event(route, template_type, context)
        store.enqueue_router(route_id, title, content, push_img_url, push_link_url)
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
def admin_login(payload: LoginRequest, response: Response):
    if not _valid_admin(payload.username, payload.password):
        raise HTTPException(401, "用户名或密码错误")
    response.set_cookie(
        SESSION_COOKIE,
        _session_token(payload.username),
        max_age=86400 * 30,
        httponly=True,
        samesite="lax",
        secure=enabled(os.environ.get("COOKIE_SECURE", "0")),
    )
    return {"authenticated": True, "username": payload.username}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"authenticated": False}


@app.get("/api/admin/session")
def admin_session(notify_session: str | None = Cookie(default=None)):
    return {"authenticated": _valid_session(notify_session), "username": os.environ.get("NH_USER", "admin")}


@app.post("/api/service/notify", dependencies=[Depends(api_auth)])
def notify(payload: object = Body(...)):
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    if not isinstance(payload, dict):
        return notify_error("请求体不是合法的JSON格式")
    route_id = payload.get("route_id")
    if route_id and not active_route(route_id):
        return notify_error(f"未找到或未激活的通道: {route_id}")
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
        event, template_type, context = parse_emby(payload)
    except (ValueError, TypeError) as exc:
        return notify_error(str(exc))
    item = payload.get("Item") or {}
    image_id = item.get("SeriesId") if item.get("Type") in {"Episode", "Season"} else item.get("Id")
    image_id = image_id or item.get("Id")
    emby_url = str(request.query_params.get("emby_url") or "").rstrip("/")
    push_img_url = payload.get("push_img_url")
    if not push_img_url and image_id and emby_url.startswith(("http://", "https://")):
        push_img_url = f"{emby_url}/emby/Items/{quote(str(image_id), safe='')}/Images/Primary"
    return enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "Emby事件通知已进入发送队列",
        push_img_url,
        payload.get("push_link_url"),
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
    return enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "Watchtower事件通知已进入发送队列",
        payload.get("push_img_url"),
        payload.get("push_link_url"),
    )


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
    return enqueue_event(route_id, event, template_type, context, "PVE事件通知已进入发送队列")


@app.get("/api/admin/status", dependencies=[Depends(admin_auth)])
def admin_status():
    return {
        "version": __version__,
        "channels": len(store.channels),
        "routes": len(store.routes),
        "plugins": len(plugin_manifests),
        "plugin_tasks": enabled(os.environ.get("PLUGIN_TASKS_ENABLED", "1")),
        "stats": store.dashboard_stats(),
        "deliveries": store.delivery_status(25),
    }


@app.get("/api/admin/config", dependencies=[Depends(admin_auth)])
def admin_config():
    return _redact(store.config)


@app.put("/api/admin/config", dependencies=[Depends(admin_auth)])
def save_config(payload: dict = Body(...)):
    try:
        store.save_config(_merge_masked(payload, store.config))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"code": 0, "message": "saved"}


@app.get("/api/admin/templates", dependencies=[Depends(admin_auth)])
def templates():
    return {"template": store.templates}


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
def deliveries(limit: int = 100, status: str | None = None):
    if status not in {None, "pending", "processing", "retry", "sent", "failed"}:
        raise HTTPException(400, "invalid delivery status")
    return store.delivery_status(max(1, min(limit, 500)), status)


@app.post("/api/admin/deliveries/{delivery_id}/retry", dependencies=[Depends(admin_auth)])
def retry_delivery(delivery_id: int):
    if not store.retry_failed(delivery_id):
        raise HTTPException(404, "failed delivery not found")
    return {"code": 0, "message": "queued"}


@app.post("/api/admin/channels/{channel_name}/test", dependencies=[Depends(admin_auth)])
def test_channel(channel_name: str, payload: TestNotification):
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


@app.get("/api/admin/logs", dependencies=[Depends(admin_auth)])
def logs(limit: int = 200):
    return list(LOG_BUFFER)[-max(1, min(limit, 500)):]


@app.get("/api/admin/plugins", dependencies=[Depends(admin_auth)])
def plugins():
    return [
        {
            **manifest,
            "has_frontend": (store.plugins_dir / str(manifest.get("id") or "") / "frontend").is_dir(),
        }
        for manifest in plugin_manifests
    ]


@app.get("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def plugin_config(plugin_id: str):
    return _redact(store.get_plugin_config(plugin_id))


@app.put("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def save_plugin_config(plugin_id: str, payload: dict = Body(...)):
    manifest = next((x for x in plugin_manifests if x.get("id") == plugin_id), None)
    if not manifest:
        raise HTTPException(404, "plugin not found")
    store.save_plugin_config(
        plugin_id,
        manifest.get("name") or plugin_id,
        _merge_masked(payload, store.get_plugin_config(plugin_id)),
        1,
    )
    return {"code": 0, "message": "saved"}


STATIC_DIR = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


plugin_manifests = register_builtin_plugins(app, store) + PluginLoader(app, store).load()


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5400")))


if __name__ == "__main__":
    main()
