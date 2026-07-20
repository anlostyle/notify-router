import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .api.flowlink_api import flowlink


logger = logging.getLogger(__name__)
wx_flowlink_router = APIRouter(prefix="/wx-flowlink-save", tags=["wx-flowlink-save"])


async def _shortcut(request: Request):
    """Optional Notify relay; the iOS Shortcut may call FlowLink directly."""
    url = request.query_params.get("url", "").strip()
    if not url and request.method == "POST":
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            url = str(payload.get("url") or "").strip()
    if not url:
        return JSONResponse({"success": False, "ok": False, "message": "缺少 url 参数"}, status_code=400)
    return JSONResponse(flowlink.shortcut(url))


@wx_flowlink_router.get("/shortcut")
async def shortcut_get(request: Request):
    return await _shortcut(request)


@wx_flowlink_router.post("/shortcut")
async def shortcut_post(request: Request):
    return await _shortcut(request)


@wx_flowlink_router.api_route("/chat", methods=["GET", "POST"])
async def legacy_chat_endpoint():
    """Explain the migration for an old Enterprise WeChat callback URL."""
    return JSONResponse(
        {
            "success": False,
            "ok": False,
            "message": "此插件已改用 FlowLink 快捷方式接口，请调用 /shortcut?url=...，不再使用企业微信回调。",
        },
        status_code=410,
    )
