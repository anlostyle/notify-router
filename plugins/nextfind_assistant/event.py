import asyncio
import datetime
import html
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlsplit
from xml.etree.ElementTree import fromstring

import httpx
from cacheout import Cache
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from tenacity import retry, stop_after_attempt, wait_random_exponential

from notifyhub.common.response import json_500
from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt

from .nextfind import handle_command
from .utils import PluginState, config

LOG_PREFIX = "「NextFind 企业微信助手」"
HTTP_TIMEOUT = 30
TOKEN_EXPIRE_BUFFER = 500
logger = logging.getLogger(__name__)
token_cache = Cache(maxsize=1)
nextfind_assistant_router = APIRouter(prefix="/nextfind_assistant", tags=["nextfind_assistant"])
subscribe_log_pattern = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*?"
    r"\[OpenAPI\] 添加订阅: (?P<title>.+?) "
    r"\(TMDB ID: (?P<tmdb_id>\d+), 类型: (?P<media_type>\w+), 用户名: (?P<username>.*?)\)"
)
web_subscribe_log_pattern = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ .*?"
    r"用户添加订阅: (?P<title>.+?) "
    r"\(TMDB ID: (?P<tmdb_id>\d+), 类型: (?P<media_type>\w+), 来源: (?P<source>\w+)\)"
)


@dataclass
class QywxMessage:
    content: str
    from_user: str
    to_user: str
    create_time: str
    msg_type: str
    msg_id: str


class QywxMessageSender:
    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=20))
    def get_access_token(self) -> Optional[str]:
        cached_token = token_cache.get("access_token")
        expires_time = token_cache.get("expires_time")
        if expires_time and expires_time >= datetime.datetime.now() and cached_token:
            return cached_token
        if not all([config.qywx_base_url, config.sCorpID, config.sCorpsecret]):
            return None
        res = httpx.get(
            f"{config.qywx_base_url.strip('/')}/cgi-bin/gettoken",
            params={"corpid": config.sCorpID, "corpsecret": config.sCorpsecret},
            timeout=HTTP_TIMEOUT,
        )
        data = res.json()
        if data.get("errcode") != 0:
            logger.error("%s 获取企业微信 token 失败: %s", LOG_PREFIX, data)
            return None
        ttl = int(data["expires_in"]) - TOKEN_EXPIRE_BUFFER
        expires_at = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
        token_cache.set("access_token", data["access_token"], ttl=ttl)
        token_cache.set("expires_time", expires_at, ttl=ttl)
        return data["access_token"]

    def send_text_message(self, text: str, to_user: str) -> bool:
        token = self.get_access_token()
        if not token:
            return False
        payload = {
            "touser": to_user,
            "agentid": config.sAgentid,
            "msgtype": "text",
            "text": {"content": text},
        }
        data = httpx.post(
            f"{config.qywx_base_url.strip('/')}/cgi-bin/message/send",
            params={"access_token": token},
            json=payload,
            timeout=HTTP_TIMEOUT,
        ).json()
        if data.get("errcode") != 0:
            logger.error("%s 发送企业微信消息失败: %s", LOG_PREFIX, data)
            return False
        return True

    def send_news_message(self, article: Dict[str, str], to_user: str) -> bool:
        token = self.get_access_token()
        if not token:
            return False
        payload = {
            "touser": to_user,
            "agentid": config.sAgentid,
            "msgtype": "news",
            "news": {"articles": [article]},
        }
        data = httpx.post(
            f"{config.qywx_base_url.strip('/')}/cgi-bin/message/send",
            params={"access_token": token},
            json=payload,
            timeout=HTTP_TIMEOUT,
        ).json()
        if data.get("errcode") != 0:
            logger.error("%s 发送企业微信 news 消息失败: %s", LOG_PREFIX, data)
            return False
        return True


class QywxProcessor:
    def __init__(self):
        self._crypto = None

    def crypto(self):
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
        data: Dict[str, str] = {node.tag: node.text or "" for node in root}
        return QywxMessage(
            content=data.get("Content", ""),
            from_user=data.get("FromUserName", ""),
            to_user=data.get("ToUserName", ""),
            create_time=data.get("CreateTime", ""),
            msg_type=data.get("MsgType", ""),
            msg_id=data.get("MsgId", ""),
        )

    def handle_message(self, encrypted_msg: str, msg_signature: str, timestamp: str, nonce: str):
        ret, decrypted = self.crypto().DecryptMsg(encrypted_msg, msg_signature, timestamp, nonce)
        if ret != 0:
            raise ValueError("企业微信消息解密失败")
        message = self.parse(decrypted.decode("utf-8"))
        if message.msg_type == "text":
            NextFindThread(message).start()


class NextFindThread(threading.Thread):
    def __init__(self, message: QywxMessage):
        super().__init__(name="NextFindAssistantThread")
        self.message = message
        self.sender = QywxMessageSender()

    def split_text(self, text: str):
        max_len = 768
        return [text[i : i + max_len] for i in range(0, len(text), max_len)] or [text]

    def run(self):
        try:
            result = asyncio.run(handle_command(self.message.from_user, self.message.content))
            for segment in self.split_text(result):
                self.sender.send_text_message(segment, self.message.from_user)
        except Exception as e:
            logger.error("%s 处理失败: %s", LOG_PREFIX, e, exc_info=True)
            self.sender.send_text_message("处理失败：" + str(e), self.message.from_user)


class NextFindLogNotifier(threading.Thread):
    def __init__(self):
        super().__init__(name="NextFindLogNotifier", daemon=True)
        self.sender = QywxMessageSender()
        self.state = PluginState()
        self.ready = False

    def username(self, match) -> str:
        return (match.groupdict().get("username") or "").strip() or "管理员"

    def tmdb_url(self, match) -> str:
        media_path = "movie" if match["media_type"] == "movie" else "tv"
        return f"https://www.themoviedb.org/{media_path}/{match['tmdb_id']}"

    def media_info(self, match) -> Dict:
        try:
            res = httpx.get(
                f"{config.nextfind_base_url}/search",
                params={"query": match["title"], "type": "all"},
                headers={"X-API-Key": config.nextfind_api_key},
                timeout=HTTP_TIMEOUT,
            )
            data = res.json()
        except Exception as e:
            logger.warning("%s 获取订阅媒体信息失败: %s", LOG_PREFIX, e)
            return {}
        for item in data.get("data") or data.get("results") or []:
            if str(item.get("id") or item.get("tmdb_id") or "") == match["tmdb_id"]:
                return item
        return {}

    def normalize_poster_url(self, value) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        if value.startswith(("http://", "https://")):
            return value
        if value.startswith("//"):
            return "https:" + value
        if value.startswith("/api/"):
            base = urlsplit(config.nextfind_base_url)
            return f"{base.scheme}://{base.netloc}{value}" if base.scheme and base.netloc else value
        if value.startswith("/"):
            return "https://image.tmdb.org/t/p/w500" + value
        return value

    def poster_url(self, item) -> str:
        for key in ("poster", "poster_path", "poster_url", "cover", "image", "picurl"):
            url = self.normalize_poster_url(item.get(key))
            if url:
                return url
        return ""

    def tmdb_overview(self, match) -> str:
        try:
            res = httpx.get(
                self.tmdb_url(match),
                params={"language": "zh-CN"},
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=HTTP_TIMEOUT,
            )
        except Exception as e:
            logger.warning("%s 获取 TMDB 简介失败: %s", LOG_PREFIX, e)
            return ""
        meta = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', res.text)
        meta = meta or re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', res.text)
        return html.unescape(meta.group(1)).strip() if meta else ""

    def overview(self, item, match) -> str:
        text = next((str(item.get(k) or "").strip() for k in ("overview", "description", "summary", "plot") if item.get(k)), "")
        text = text or self.tmdb_overview(match)
        return text[:220] + ("..." if len(text) > 220 else "") if text else "暂无简介"

    def format_message(self, match, source="NextFind OpenAPI"):
        media_type = "电影" if match["media_type"] == "movie" else "电视剧"
        username = self.username(match)
        return (
            "📌 NextEmby 新增订阅\n\n"
            f"用户：{username}\n"
            f"片名：{match['title']}\n"
            f"类型：{media_type}\n"
            f"TMDB：{match['tmdb_id']}\n"
            f"时间：{match['time']}\n"
            f"来源：{source}"
        )

    def format_article(self, match, source="NextFind OpenAPI") -> Dict[str, str]:
        media_type = "电影" if match["media_type"] == "movie" else "电视剧"
        item = self.media_info(match)
        year = str(item.get("year") or "").strip()
        title = f"{match['title']} ({year})" if year else match["title"]
        return {
            "title": f"新增订阅：{title}",
            "description": (
                f"用户：{self.username(match)}\n"
                f"类型：{media_type}\n"
                f"TMDB：{match['tmdb_id']}\n"
                f"时间：{match['time']}\n"
                f"来源：{source}\n"
                f"简介：{self.overview(item, match)}"
            ),
            "url": self.tmdb_url(match),
            "picurl": self.poster_url(item),
        }

    def poll(self, send=True):
        if not all([config.nextfind_base_url, config.nextfind_api_key, config.nextfind_log_notify_users]):
            return
        res = httpx.get(
            f"{config.nextfind_base_url}/logs",
            params={"lines": config.nextfind_log_lines},
            headers={"X-API-Key": config.nextfind_api_key},
            timeout=HTTP_TIMEOUT,
        )
        data = res.json()
        for line in data.get("data") or []:
            match = subscribe_log_pattern.search(line)
            source = "NextFind OpenAPI"
            if not match:
                match = web_subscribe_log_pattern.search(line)
                source = "NextFind 网页端"
                if not match or match["source"] == "rss":
                    continue
            if self.state.seen_log(line):
                continue
            if send and self.ready:
                sent = self.sender.send_news_message(self.format_article(match, source), config.nextfind_log_notify_users)
                if not sent:
                    self.sender.send_text_message(self.format_message(match, source), config.nextfind_log_notify_users)
        self.ready = True

    def run(self):
        while True:
            try:
                self.poll()
            except Exception as e:
                logger.error("%s 订阅日志通知检查失败: %s", LOG_PREFIX, e, exc_info=True)
            time.sleep(config.nextfind_log_poll_seconds)


processor = QywxProcessor()
notifier = NextFindLogNotifier()
notifier.start()


@nextfind_assistant_router.get("/chat")
async def verify_callback(request: Request):
    try:
        msg_signature = request.query_params.get("msg_signature")
        timestamp = request.query_params.get("timestamp")
        nonce = request.query_params.get("nonce")
        echostr = request.query_params.get("echostr")
        if not all([msg_signature, timestamp, nonce, echostr]):
            raise HTTPException(status_code=400, detail="缺少必要参数")
        return int(processor.verify_url(msg_signature, timestamp, nonce, echostr))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("%s URL 验证失败: %s", LOG_PREFIX, e, exc_info=True)
        return json_500("URL 验证失败")


@nextfind_assistant_router.post("/chat")
async def receive_message(request: Request):
    try:
        msg_signature = request.query_params.get("msg_signature")
        timestamp = request.query_params.get("timestamp")
        nonce = request.query_params.get("nonce")
        if not all([msg_signature, timestamp, nonce]):
            raise HTTPException(status_code=400, detail="缺少必要参数")
        body = (await request.body()).decode("utf-8")
        processor.handle_message(body, msg_signature, timestamp, nonce)
        return Response(content="success", media_type="text/plain")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("%s 消息处理失败: %s", LOG_PREFIX, e, exc_info=True)
        return json_500("消息处理失败")
