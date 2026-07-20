import datetime
import logging
import re
import threading
from dataclasses import dataclass
from xml.etree.ElementTree import fromstring

import httpx
from cacheout import Cache
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from notifyhub.common.response import json_500
from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt

from .api.flowlink_api import flowlink
from .utils import config


logger = logging.getLogger(__name__)
wx_flowlink_router = APIRouter(prefix="/wx-flowlink-save", tags=["wx-flowlink-save"])
token_cache = Cache(maxsize=2)

SHARE_URL_RE = re.compile(
    r"https?://(?:115\.com|115cdn\.com)/s/[A-Za-z0-9]+(?:\?[^\s#。，；！]*)?(?:#[^\s。，；！]*)?",
    re.IGNORECASE,
)
PICKUP_CODE_RE = re.compile(r"(?:提取码|访问码|密码)\s*[:：]?\s*([A-Za-z0-9]{4})", re.IGNORECASE)


def extract_share_input(content: str) -> str | None:
    """Extract a 115 URL and preserve a separately supplied pickup code."""
    match = SHARE_URL_RE.search(content or "")
    if not match:
        return None
    share_url = match.group(0).rstrip("#")
    code_match = PICKUP_CODE_RE.search((content or "")[match.end() :])
    if code_match and "password=" not in share_url.lower():
        return f"{share_url} 提取码: {code_match.group(1)}"
    return share_url


@dataclass
class QywxMessage:
    content: str
    from_user: str
    to_user: str
    create_time: str
    msg_type: str
    msg_id: str


class QywxMessageSender:
    def get_access_token(self) -> str | None:
        cached = token_cache.get("access_token")
        if cached:
            return str(cached)
        if not config.corp_id or not config.corp_secret:
            return None
        try:
            response = httpx.get(
                f"{config.qywx_base_url}/cgi-bin/gettoken",
                params={"corpid": config.corp_id, "corpsecret": config.corp_secret},
                headers={"User-Agent": "wx-flowlink-save/0.1.0"},
                timeout=30,
            )
            result = response.json()
            if result.get("errcode") != 0:
                logger.warning("Enterprise WeChat token request failed: code=%s", result.get("errcode"))
                return None
            expires_in = max(int(result.get("expires_in", 7200)) - 300, 60)
            token_cache.set("access_token", result["access_token"], ttl=expires_in)
            return str(result["access_token"])
        except (httpx.HTTPError, ValueError, KeyError):
            logger.warning("Enterprise WeChat token request failed", exc_info=True)
            return None

    def _send(self, payload: dict) -> bool:
        access_token = self.get_access_token()
        if not access_token:
            return False
        try:
            response = httpx.post(
                f"{config.qywx_base_url}/cgi-bin/message/send",
                params={"access_token": access_token},
                json={"touser": payload.pop("touser"), "agentid": config.agent_id, **payload},
                headers={"User-Agent": "wx-flowlink-save/0.1.0"},
                timeout=30,
            )
            result = response.json()
            if result.get("errcode") == 0:
                return True
            logger.warning("Enterprise WeChat send failed: code=%s", result.get("errcode"))
        except (httpx.HTTPError, ValueError):
            logger.warning("Enterprise WeChat send failed", exc_info=True)
        return False

    def send_text(self, text: str, to_user: str) -> bool:
        return self._send({"touser": to_user, "msgtype": "text", "text": {"content": text}})

    def send_news(self, title: str, description: str, url: str, to_user: str) -> bool:
        return self._send(
            {
                "touser": to_user,
                "msgtype": "news",
                "news": {
                    "articles": [
                        {
                            "title": title,
                            "description": description,
                            "url": url,
                            "picurl": config.cover_url,
                        }
                    ]
                },
            }
        )


def process_chat_message(message: QywxMessage, sender: QywxMessageSender | None = None) -> None:
    sender = sender or QywxMessageSender()
    share_input = extract_share_input(message.content)
    if not share_input:
        sender.send_text(
            "请发送 115 分享链接，支持链接自带密码，也支持在链接后输入“提取码: 1234”。",
            message.from_user,
        )
        return

    result = flowlink.receive_share(share_input)
    share_url = SHARE_URL_RE.search(share_input).group(0)
    if not result.get("success"):
        sender.send_text(f"❌ FlowLink 转存失败：{result.get('message', '未知错误')}", message.from_user)
        return

    title = str(result.get("receive_title") or "115 分享内容")
    file_count = int(result.get("recv_file_count") or 0)
    folder_count = int(result.get("recv_folder_count") or 0)
    organizer = str(result.get("organizer") or "")
    lines = [
        f"已接收：{title}",
        f"文件：{file_count} 个，目录：{folder_count} 个",
        f"任务：{config.task_name}",
    ]
    if organizer == "flowlink_tmdb":
        lines.append("已进入 TMDB 识别、重命名和影剧分类队列")
    elif organizer == "direct":
        lines.append("已进入直接整理队列")
    if result.get("transfer_queue_added"):
        lines.append("后续 STRM 增量任务已入队")
    sender.send_news("✅ FlowLink 转存整理已启动", "\n".join(lines), share_url, message.from_user)


class QywxCallbackHandler:
    def __init__(self):
        self._crypto: WXBizMsgCrypt | None = None
        self._crypto_fingerprint: tuple[str, str, str] | None = None

    def _get_crypto(self) -> WXBizMsgCrypt:
        fingerprint = (config.callback_token, config.encoding_aes_key, config.corp_id)
        if not all(fingerprint):
            raise ValueError("企业微信回调配置不完整")
        if self._crypto is None or fingerprint != self._crypto_fingerprint:
            self._crypto = WXBizMsgCrypt(*fingerprint)
            self._crypto_fingerprint = fingerprint
        return self._crypto

    @staticmethod
    def _parse(xml_data: str) -> QywxMessage:
        root = fromstring(xml_data)
        values = {node.tag: node.text or "" for node in root}
        return QywxMessage(
            content=values.get("Content", ""),
            from_user=values.get("FromUserName", ""),
            to_user=values.get("ToUserName", ""),
            create_time=values.get("CreateTime", str(int(datetime.datetime.now().timestamp()))),
            msg_type=values.get("MsgType", "text"),
            msg_id=values.get("MsgId", "0"),
        )

    def verify(self, signature: str, timestamp: str, nonce: str, echo: str) -> str:
        code, value = self._get_crypto().VerifyURL(signature, timestamp, nonce, echo)
        if code != 0:
            raise ValueError("企业微信回调验证失败")
        return value.decode("utf-8")

    def receive(self, encrypted_xml: str, signature: str, timestamp: str, nonce: str) -> str:
        crypto = self._get_crypto()
        code, decrypted = crypto.DecryptMsg(encrypted_xml, signature, timestamp, nonce)
        if code != 0:
            raise ValueError("企业微信消息解密失败")
        message = self._parse(decrypted.decode("utf-8"))
        threading.Thread(target=process_chat_message, args=(message,), daemon=True).start()
        reply = (
            "<xml>"
            f"<ToUserName><![CDATA[{message.from_user}]]></ToUserName>"
            f"<FromUserName><![CDATA[{message.to_user}]]></FromUserName>"
            f"<CreateTime>{int(datetime.datetime.now().timestamp())}</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[已提交至 FlowLink，正在转存整理…]]></Content>"
            "</xml>"
        )
        code, encrypted_reply = crypto.EncryptMsg(reply, nonce, timestamp)
        if code != 0:
            raise ValueError("企业微信回复加密失败")
        return encrypted_reply


callback_handler = QywxCallbackHandler()


@wx_flowlink_router.get("/chat")
async def verify_callback(request: Request):
    values = [request.query_params.get(key) for key in ("msg_signature", "timestamp", "nonce", "echostr")]
    if not all(values):
        raise HTTPException(status_code=400, detail="缺少必要的验证参数")
    try:
        return Response(content=callback_handler.verify(*values), media_type="text/plain")
    except ValueError:
        raise HTTPException(status_code=500, detail="企业微信回调验证失败")


@wx_flowlink_router.post("/chat")
async def receive_message(request: Request):
    values = [request.query_params.get(key) for key in ("msg_signature", "timestamp", "nonce")]
    if not all(values):
        raise HTTPException(status_code=400, detail="缺少必要的验证参数")
    try:
        result = callback_handler.receive((await request.body()).decode("utf-8"), *values)
        return Response(content=result, media_type="text/plain")
    except ValueError:
        return json_500("企业微信消息处理失败")
