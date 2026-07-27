import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from .channels import send_qywx
from .plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt


logger = logging.getLogger(__name__)

MANIFESTS = [
    {
        "id": "chatbot",
        "name": "企业微信智能聊天机器人",
        "description": "OpenAI 兼容接口驱动的企业微信聊天机器人",
        "version": "0.0.1-compatible",
        "path": "/chatbot",
        "configField": [
            {"fieldName": name, "fieldType": kind, "label": label, "defaultValue": default}
            for name, kind, label, default in (
                ("base_url", "string", "API基础URL", "https://api.openai.com"),
                ("api_key", "string", "API密钥", ""),
                ("model", "string", "模型名称", ""),
                ("proxy", "string", "代理地址", ""),
                ("context_num", "number", "上下文数量", 10),
                ("custom_prompt", "text", "自定义提示词", ""),
                ("qywx_base_url", "string", "企业微信API地址", "https://qyapi.weixin.qq.com"),
                ("sCorpID", "string", "企业微信CorpID", ""),
                ("sCorpsecret", "string", "企业微信Secret", ""),
                ("sAgentid", "string", "企业微信AgentID", ""),
                ("sToken", "string", "企业微信Token", ""),
                ("sEncodingAESKey", "string", "企业微信EncodingAESKey", ""),
            )
        ],
        "helpTextField": [
            {"fieldType": "title", "value": "企业微信回调地址"},
            {"fieldType": "code", "value": "{site_url}/api/plugins/chatbot/chat"},
            {"fieldType": "text", "value": "在企业微信应用中配置接收消息，验证 URL 和接收消息都使用上面的地址。"},
        ],
    },
    {
        "id": "qywx_receive",
        "name": "企业微信回调工具",
        "description": "企业微信接收消息服务器回调验证工具",
        "version": "0.0.1-compatible",
        "path": "/qywx_receive",
        "configField": [
            {"fieldName": "corpid", "fieldType": "string", "label": "CorpID", "defaultValue": ""},
            {"fieldName": "token", "fieldType": "string", "label": "Token", "defaultValue": ""},
            {"fieldName": "encodingAesKey", "fieldType": "string", "label": "EncodingAESKey", "defaultValue": ""},
        ],
        "helpTextField": [
            {"fieldType": "title", "value": "企业微信回调地址"},
            {"fieldType": "code", "value": "{site_url}/api/plugins/qywx_receive/verify"},
            {"fieldType": "text", "value": "在企业微信应用中配置服务器 URL，使用上面的地址完成回调验证。"},
        ],
    },
]


def register_builtin_plugins(app, store):
    router = APIRouter(prefix="/api/plugins")

    @router.get("/qywx_receive/verify", response_class=PlainTextResponse)
    def verify_qywx(msg_signature: str, timestamp: str, nonce: str, echostr: str):
        config = store.get_plugin_config("qywx_receive")
        return _verify(config, msg_signature, timestamp, nonce, echostr)

    @router.get("/chatbot/chat", response_class=PlainTextResponse)
    def verify_chatbot(msg_signature: str, timestamp: str, nonce: str, echostr: str):
        config = store.get_plugin_config("chatbot")
        return _verify(_chat_crypto_config(config), msg_signature, timestamp, nonce, echostr)

    @router.post("/chatbot/chat", response_class=PlainTextResponse)
    async def chatbot(request: Request, background: BackgroundTasks, msg_signature: str, timestamp: str, nonce: str):
        config = store.get_plugin_config("chatbot")
        crypt = _crypt(_chat_crypto_config(config))
        code, message = crypt.DecryptMsg(await request.body(), msg_signature, timestamp, nonce)
        if code != 0 or not message:
            raise HTTPException(400, "invalid callback signature")
        root = ET.fromstring(message)
        if root.findtext("MsgType") == "text" and root.findtext("Content"):
            background.add_task(_chat_reply, store, config, root.findtext("FromUserName") or "", root.findtext("Content"))
        return "success"

    app.include_router(router)
    return MANIFESTS


def _chat_crypto_config(config):
    return {"corpid": config.get("sCorpID"), "token": config.get("sToken"), "encodingAesKey": config.get("sEncodingAESKey")}


def _crypt(config):
    try:
        return WXBizMsgCrypt(config.get("token") or "", config.get("encodingAesKey") or "", config.get("corpid") or "")
    except ValueError as exc:
        raise HTTPException(400, "plugin callback configuration is incomplete") from exc


def _verify(config, signature, timestamp, nonce, echostr):
    code, echo = _crypt(config).VerifyURL(signature, timestamp, nonce, echostr)
    if code != 0 or echo is None:
        raise HTTPException(400, "invalid callback signature")
    return echo.decode()


def _chat_reply(store, config, user, content):
    try:
        if content.strip() in {"重来", "重置", "重新开始"}:
            history = []
            reply = "对话已重置。"
        else:
            history = _history(store, user)
            messages = []
            if config.get("custom_prompt"):
                messages.append({"role": "system", "content": str(config["custom_prompt"])})
            messages.extend(history)
            messages.append({"role": "user", "content": content})
            base = str(config.get("base_url") or "https://api.openai.com").rstrip("/")
            url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
            with httpx.Client(timeout=60, proxy=config.get("proxy") or None) as client:
                response = client.post(
                    url,
                    headers={"Authorization": f"Bearer {config.get('api_key') or ''}"},
                    json={"model": config.get("model"), "messages": messages},
                )
                response.raise_for_status()
                reply = response.json()["choices"][0]["message"]["content"]
            limit = max(1, int(config.get("context_num") or 10)) * 2
            history = (history + [{"role": "user", "content": content}, {"role": "assistant", "content": reply}])[-limit:]
        _save_history(store, user, history)
        send_qywx(
            {
                "server_url": config.get("qywx_base_url") or "https://qyapi.weixin.qq.com",
                "corpid": config.get("sCorpID"),
                "corpsecret": config.get("sCorpsecret"),
                "agentid": config.get("sAgentid"),
                "touser": user,
            },
            {"title": "", "content": reply, "push_img_url": None, "push_link_url": None},
        )
    except Exception as exc:
        logger.error("chatbot reply failed for user=%s: %s", user, exc)


def _history(store, user):
    with store.connect() as db:
        row = db.execute("SELECT value FROM cache WHERE key=?", (f"chatbot:{user}",)).fetchone()
    try:
        value = json.loads(row[0]) if row else []
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _save_history(store, user, history):
    now = datetime.now(timezone.utc).isoformat()
    with store.connect() as db:
        db.execute(
            """INSERT INTO cache (namespace, key, value, created_at, updated_at)
               VALUES ('chatbot', ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (f"chatbot:{user}", json.dumps(history, ensure_ascii=False), now, now),
        )
