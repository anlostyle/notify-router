"""FlowLink shortcut relay and Enterprise WeChat share receiver."""

import datetime
import logging
import re
import threading
from dataclasses import dataclass
from typing import Optional
from xml.etree.ElementTree import fromstring

import httpx
from cacheout import Cache
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt

from .api.flowlink_api import flowlink
from .utils import config


logger = logging.getLogger(__name__)
wx_flowlink_router = APIRouter(prefix="/wx-flowlink-save", tags=["wx-flowlink-save"])
APP_USER_AGENT = "wx-flowlink-save/0.4.0"
HTTP_TIMEOUT = 30
TOKEN_EXPIRE_BUFFER = 500
DEFAULT_COVER_URL = "https://s1.locimg.com/2025/01/03/13a09e2f7cb3a.png"
SHARE_LINK_PATTERN = re.compile(r"https?://(?:115\.com|115cdn\.com)/s/[^\s<>]+", re.IGNORECASE)
TRAILING_LINK_PUNCTUATION = ".,，。；;:：!！?？)]}》」』"
token_cache = Cache(maxsize=1)


@dataclass
class QywxMessage:
    content: str
    from_user: str
    to_user: str
    create_time: str
    msg_type: str
    msg_id: str


def extract_share_url(content: str) -> str:
    """Extract one 115 share URL from ordinary WeCom message text."""
    match = SHARE_LINK_PATTERN.search(content or "")
    if not match:
        return ""
    return match.group(0).rstrip(TRAILING_LINK_PUNCTUATION)


class QywxMessageSender:
    def _get_access_token(self) -> Optional[str]:
        cached = token_cache.get("access_token")
        expires_at = token_cache.get("expires_at")
        if cached and expires_at and expires_at >= datetime.datetime.now():
            return cached
        if not config.sCorpID or not config.sCorpsecret:
            return None
        try:
            response = httpx.get(
                f"{config.qywx_base_url.rstrip('/')}/cgi-bin/gettoken",
                params={"corpid": config.sCorpID, "corpsecret": config.sCorpsecret},
                headers={"User-Agent": APP_USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            data = response.json()
            if data.get("errcode") != 0 or not data.get("access_token"):
                logger.warning("FlowLink 企业微信 token 获取失败，errcode=%s", data.get("errcode"))
                return None
            ttl = max(int(data.get("expires_in", 7200)) - TOKEN_EXPIRE_BUFFER, 60)
            expires_at = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
            token_cache.set("access_token", data["access_token"], ttl=ttl)
            token_cache.set("expires_at", expires_at, ttl=ttl)
            return data["access_token"]
        except (httpx.RequestError, ValueError, KeyError) as exc:
            logger.warning("FlowLink 企业微信 token 请求失败: %s", type(exc).__name__)
            return None

    def _send(self, payload: dict) -> bool:
        access_token = self._get_access_token()
        if not access_token or not config.sAgentid:
            return False
        try:
            response = httpx.post(
                f"{config.qywx_base_url.rstrip('/')}/cgi-bin/message/send",
                params={"access_token": access_token},
                json=payload,
                headers={"User-Agent": APP_USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            data = response.json()
            if data.get("errcode") != 0:
                logger.warning("FlowLink 企业微信消息发送失败，errcode=%s", data.get("errcode"))
                return False
            return True
        except (httpx.RequestError, ValueError) as exc:
            logger.warning("FlowLink 企业微信消息请求失败: %s", type(exc).__name__)
            return False

    def send_text_message(self, text: str, to_user: str) -> bool:
        return self._send(
            {
                "touser": to_user,
                "agentid": config.sAgentid,
                "msgtype": "text",
                "text": {"content": text},
            }
        )

    def send_news_message(self, title: str, description: str, url: str, to_user: str) -> bool:
        return self._send(
            {
                "touser": to_user,
                "agentid": config.sAgentid,
                "msgtype": "news",
                "news": {
                    "articles": [
                        {
                            "title": title,
                            "description": description,
                            "url": url,
                            "picurl": config.cover_url or DEFAULT_COVER_URL,
                        }
                    ]
                },
            }
        )


class QywxProcessor:
    def __init__(self):
        self._crypto: Optional[WXBizMsgCrypt] = None

    def crypto(self) -> WXBizMsgCrypt:
        if self._crypto is None:
            if not all([config.sToken, config.sEncodingAESKey, config.sCorpID]):
                raise ValueError("企业微信加密配置不完整")
            self._crypto = WXBizMsgCrypt(config.sToken, config.sEncodingAESKey, config.sCorpID)
        return self._crypto

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        ret, echo = self.crypto().VerifyURL(msg_signature, timestamp, nonce, echostr)
        if ret != 0:
            raise ValueError("企业微信 URL 验证失败")
        return echo.decode("utf-8")

    def parse(self, xml_data: str) -> QywxMessage:
        root = fromstring(xml_data)
        data = {node.tag: node.text or "" for node in root}
        return QywxMessage(
            content=data.get("Content", ""),
            from_user=data.get("FromUserName", ""),
            to_user=data.get("ToUserName", ""),
            create_time=data.get("CreateTime", ""),
            msg_type=data.get("MsgType", ""),
            msg_id=data.get("MsgId", ""),
        )

    def handle_message(self, encrypted_msg: str, msg_signature: str, timestamp: str, nonce: str) -> None:
        ret, decrypted = self.crypto().DecryptMsg(encrypted_msg, msg_signature, timestamp, nonce)
        if ret != 0:
            raise ValueError("企业微信消息解密失败")
        message = self.parse(decrypted.decode("utf-8"))
        if message.msg_type == "text":
            QywxFlowLinkThread(message).start()


class QywxFlowLinkThread(threading.Thread):
    def __init__(self, message: QywxMessage):
        super().__init__(name="QywxFlowLinkThread", daemon=True)
        self.message = message
        self.sender = QywxMessageSender()

    def run(self) -> None:
        share_url = extract_share_url(self.message.content)
        if not share_url:
            self.sender.send_text_message(
                "请发送 115 分享链接，例如：https://115cdn.com/s/xxxx?password=xxxx",
                self.message.from_user,
            )
            return
        try:
            result = flowlink.shortcut(share_url)
            if result.get("ok") or result.get("success"):
                title = "✅ 115 转存成功"
                description = "分享已接收，并已触发 FlowLink 整理任务。"
                if not self.sender.send_news_message(title, description, share_url, self.message.from_user):
                    self.sender.send_text_message(f"{title}\n{description}", self.message.from_user)
                return
            message = str(result.get("message") or "FlowLink 返回失败")[:500]
            self.sender.send_text_message(f"❌ 115 转存失败：{message}", self.message.from_user)
        except Exception as exc:
            logger.exception("FlowLink 企业微信转存失败: %s", type(exc).__name__)
            self.sender.send_text_message("❌ FlowLink 转存失败，请检查服务日志。", self.message.from_user)


processor = QywxProcessor()


@wx_flowlink_router.get("/chat", response_class=PlainTextResponse)
async def verify_callback(request: Request):
    msg_signature = request.query_params.get("msg_signature")
    timestamp = request.query_params.get("timestamp")
    nonce = request.query_params.get("nonce")
    echostr = request.query_params.get("echostr")
    if not all([msg_signature, timestamp, nonce, echostr]):
        raise HTTPException(status_code=400, detail="缺少必要参数")
    try:
        return processor.verify_url(msg_signature, timestamp, nonce, echostr)
    except Exception as exc:
        logger.warning("FlowLink 企业微信 URL 验证失败: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="企业微信 URL 验证失败") from exc


@wx_flowlink_router.post("/chat", response_class=PlainTextResponse)
async def receive_message(request: Request):
    msg_signature = request.query_params.get("msg_signature")
    timestamp = request.query_params.get("timestamp")
    nonce = request.query_params.get("nonce")
    if not all([msg_signature, timestamp, nonce]):
        raise HTTPException(status_code=400, detail="缺少必要参数")
    try:
        processor.handle_message((await request.body()).decode("utf-8"), msg_signature, timestamp, nonce)
        return "success"
    except Exception as exc:
        logger.warning("FlowLink 企业微信消息处理失败: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="企业微信消息处理失败") from exc


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
