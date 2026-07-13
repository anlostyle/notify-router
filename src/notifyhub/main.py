import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ValidationError

from . import __version__
from .builtin_plugins import register_builtin_plugins
from .controller.schedule import start_scheduler, stop_scheduler
from .controller.server import Server
from .plugin_loader import PluginLoader
from .plugins.common import run_after_setup_hooks
from .service_compat import parse_emby, parse_pve, parse_watchtower
from .store import Store, enabled
from .worker import DeliveryWorker


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("notifyhub")

DATA_DIR = Path(os.environ.get("WORKDIR", "/data"))
os.environ.setdefault("WORKDIR", str(DATA_DIR))
store = Store(DATA_DIR)
Server.configure(store)
worker = DeliveryWorker(store)
security = HTTPBasic(auto_error=False)


@asynccontextmanager
async def lifespan(_app):
    worker.start()
    start_scheduler()
    await run_after_setup_hooks(logger)
    yield
    stop_scheduler()
    worker.stop()


app = FastAPI(title="Notify Router", version=__version__, lifespan=lifespan)


class NotifyRequest(BaseModel):
    route_id: str
    title: str
    content: str
    push_img_url: str | None = None
    push_link_url: str | None = None


def api_auth(authorization: str | None = Header(default=None)):
    token = os.environ.get("NOTIFY_API_TOKEN", "")
    if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "invalid API token")


def admin_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    username = os.environ.get("NH_USER", "admin")
    password = os.environ.get("NH_PASSWORD", "")
    valid = credentials and hmac.compare_digest(credentials.username, username) and hmac.compare_digest(credentials.password, password)
    if not valid:
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Basic"})


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


@app.post("/api/service/notify", dependencies=[Depends(api_auth)])
def notify(payload: object = Body(...)):
    if not isinstance(payload, dict):
        return notify_error("请求体不是合法的JSON格式")
    route_id = payload.get("route_id")
    if route_id and not active_route(route_id):
        return notify_error(f"未找到或未激活的通道: {route_id}")
    try:
        return enqueue(NotifyRequest.model_validate(payload))
    except ValidationError:
        return notify_error("请求体不是合法的JSON格式")


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
    return enqueue_event(
        route_id,
        event,
        template_type,
        context,
        "Emby事件通知已进入发送队列",
        payload.get("push_img_url"),
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
    try:
        payload = await request.json()
        event, template_type, context = parse_pve(payload)
    except (ValueError, TypeError) as exc:
        return notify_error(str(exc))
    return enqueue_event(route_id, event, template_type, context, "PVE事件通知已进入发送队列")


@app.get("/api/admin/status", dependencies=[Depends(admin_auth)])
def admin_status():
    return {
        "version": __version__,
        "channels": len(store.channels),
        "routes": len(store.routes),
        "plugins": len(plugin_manifests),
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


@app.post("/api/admin/deliveries/{delivery_id}/retry", dependencies=[Depends(admin_auth)])
def retry_delivery(delivery_id: int):
    if not store.retry_failed(delivery_id):
        raise HTTPException(404, "failed delivery not found")
    return {"code": 0, "message": "queued"}


@app.get("/api/admin/plugins", dependencies=[Depends(admin_auth)])
def plugins():
    return plugin_manifests


@app.get("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def plugin_config(plugin_id: str):
    return store.get_plugin_config(plugin_id)


@app.put("/api/admin/plugins/{plugin_id}/config", dependencies=[Depends(admin_auth)])
def save_plugin_config(plugin_id: str, payload: dict = Body(...)):
    manifest = next((x for x in plugin_manifests if x.get("id") == plugin_id), None)
    if not manifest:
        raise HTTPException(404, "plugin not found")
    store.save_plugin_config(plugin_id, manifest.get("name") or plugin_id, payload, 1)
    return {"code": 0, "message": "saved"}


STATIC_DIR = Path(__file__).with_name("static")


@app.get("/")
def index(_=Depends(admin_auth)):
    return FileResponse(STATIC_DIR / "index.html")


plugin_manifests = register_builtin_plugins(app, store) + PluginLoader(app, store).load()


def main():
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5400")))


if __name__ == "__main__":
    main()
