"""Enterprise WeChat receiver for NextEmby activation cards."""

import datetime
import logging
import threading
from dataclasses import dataclass
from typing import Optional
from xml.etree.ElementTree import fromstring

import httpx
from cacheout import Cache
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt

from .commands import handle_command
from .utils import config


logger = logging.getLogger(__name__)
wx_nextemby_card_router = APIRouter(prefix="/wx-nextemby-card", tags=["wx-nextemby-card"])
APP_USER_AGENT = "wx-nextemby-card/0.3.1"
HTTP_TIMEOUT = 30
TOKEN_EXPIRE_BUFFER = 500
MAX_TEXT_BYTES = 2000
token_cache = Cache(maxsize=1)
# Enterprise WeChat retries a callback it thinks timed out; generating cards is
# not idempotent, so remember recent message ids and drop the retries.
seen_messages = Cache(maxsize=512, ttl=600)
seen_lock = threading.Lock()
# One command at a time keeps each command's replies together in the chat.
command_lock = threading.Lock()


@dataclass
class QywxMessage:
    content: str
    from_user: str
    to_user: str
    create_time: str
    msg_type: str
    msg_id: str


def split_text(text: str, limit: int = MAX_TEXT_BYTES) -> list[str]:
    """Split on line boundaries so each WeCom text stays under its byte limit."""
    parts: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if current and len((current + line).encode("utf-8")) > limit:
            parts.append(current)
            current = ""
        while len(line.encode("utf-8")) > limit:
            cut = limit // 4
            while len(line[: cut + 1].encode("utf-8")) <= limit:
                cut += 1
            parts.append(line[:cut])
            line = line[cut:]
        current += line
    if current:
        parts.append(current)
    return [part.strip() for part in parts if part.strip()] or [text]


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
                f"{config.qywx_base_url}/cgi-bin/gettoken",
                params={"corpid": config.sCorpID, "corpsecret": config.sCorpsecret},
                headers={"User-Agent": APP_USER_AGENT},
                timeout=HTTP_TIMEOUT,
            )
            data = response.json()
            if data.get("errcode") != 0 or not data.get("access_token"):
                logger.warning("NextEmby 卡密企业微信 token 获取失败，errcode=%s", data.get("errcode"))
                return None
            ttl = max(int(data.get("expires_in", 7200)) - TOKEN_EXPIRE_BUFFER, 60)
            expires_at = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
            token_cache.set("access_token", data["access_token"], ttl=ttl)
            token_cache.set("expires_at", expires_at, ttl=ttl)
            return data["access_token"]
        except (httpx.RequestError, ValueError, KeyError) as exc:
            logger.warning("NextEmby 卡密企业微信 token 请求失败: %s", type(exc).__name__)
            return None

    def send_text_message(self, text: str, to_user: str) -> bool:
        access_token = self._get_access_token()
        if not access_token or not config.sAgentid:
            logger.warning("NextEmby 卡密企业微信配置不完整，无法回复")
            return False
        ok = True
        for part in split_text(text):
            try:
                response = httpx.post(
                    f"{config.qywx_base_url}/cgi-bin/message/send",
                    params={"access_token": access_token},
                    json={"touser": to_user, "agentid": config.sAgentid, "msgtype": "text", "text": {"content": part}},
                    headers={"User-Agent": APP_USER_AGENT},
                    timeout=HTTP_TIMEOUT,
                )
                data = response.json()
                if data.get("errcode") != 0:
                    logger.warning("NextEmby 卡密企业微信消息发送失败，errcode=%s", data.get("errcode"))
                    ok = False
            except (httpx.RequestError, ValueError) as exc:
                logger.warning("NextEmby 卡密企业微信消息请求失败: %s", type(exc).__name__)
                ok = False
        return ok


def authorize(user: str) -> Optional[str]:
    """Return a rejection message for users outside the allow list."""
    allowed = config.allowed_users
    if not allowed:
        return f"⛔ 插件还没有配置授权 UserID。\n你的 UserID：{user}\n请把它填到插件配置「授权 UserID」后再试。"
    if user not in allowed:
        return f"⛔ 没有权限使用卡密助手（UserID：{user}）"
    return None


def first_delivery(msg_id: str) -> bool:
    if not msg_id:
        return True
    with seen_lock:
        if seen_messages.get(msg_id):
            return False
        seen_messages.set(msg_id, True)
        return True


class QywxProcessor:
    def __init__(self):
        self._crypto: Optional[WXBizMsgCrypt] = None
        self._crypto_key: tuple = ()

    def crypto(self) -> WXBizMsgCrypt:
        key = (config.sToken, config.sEncodingAESKey, config.sCorpID)
        if not all(key):
            raise ValueError("企业微信加密配置不完整")
        if self._crypto is None or self._crypto_key != key:
            self._crypto = WXBizMsgCrypt(*key)
            self._crypto_key = key
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
        if message.msg_type == "text" and first_delivery(message.msg_id):
            QywxCardThread(message).start()


class QywxCardThread(threading.Thread):
    def __init__(self, message: QywxMessage, sender: Optional[QywxMessageSender] = None):
        super().__init__(name="QywxNextEmbyCardThread", daemon=True)
        self.message = message
        self.sender = sender or QywxMessageSender()

    def run(self) -> None:
        user = self.message.from_user
        rejection = authorize(user)
        if rejection:
            logger.info("NextEmby 卡密助手拒绝未授权用户: %s", user)
            self.sender.send_text_message(rejection, user)
            return
        with command_lock:
            try:
                replies = handle_command(self.message.content)
            except Exception as exc:
                logger.exception("NextEmby 卡密命令处理失败: %s", type(exc).__name__)
                replies = ["❌ 处理失败，请查看插件日志"]
            for reply in replies:
                self.sender.send_text_message(reply, user)


processor = QywxProcessor()


@wx_nextemby_card_router.get("/chat", response_class=PlainTextResponse)
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
        logger.warning("NextEmby 卡密企业微信 URL 验证失败: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="企业微信 URL 验证失败") from exc


@wx_nextemby_card_router.post("/chat", response_class=PlainTextResponse)
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
        logger.warning("NextEmby 卡密企业微信消息处理失败: %s", type(exc).__name__)
        raise HTTPException(status_code=400, detail="企业微信消息处理失败") from exc
