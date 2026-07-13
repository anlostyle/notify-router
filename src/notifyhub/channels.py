import json
import smtplib
import ssl
import threading
import time
import urllib.parse
from email.message import EmailMessage

import httpx


_tokens = {}
_tokens_lock = threading.Lock()


def _config(channel):
    return channel.get("config") or {}


def _pick(config, *names, default=""):
    for name in names:
        value = config.get(name)
        if value not in (None, ""):
            return value
    return default


def _response_json(response):
    response.raise_for_status()
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"channel returned non-JSON HTTP {response.status_code}") from exc


def _truncate_utf8(text, limit):
    return str(text).encode()[:limit].decode("utf-8", "ignore")


def send(channel, item):
    channel_type = str(channel.get("type") or "").lower()
    handlers = {
        "qywx": send_qywx,
        "bark": send_bark,
        "telegram": send_telegram,
        "discord": send_discord,
        "dingtalk": send_dingtalk,
        "pushdeer": send_pushdeer,
        "feishu": send_feishu,
        "serverchan3": send_serverchan3,
        "email": send_email,
        "webhook": send_webhook,
    }
    handler = handlers.get(channel_type)
    if not handler:
        raise ValueError(f"unsupported channel type: {channel_type}")
    handler(_config(channel), item)


def _qywx_token(config, refresh=False):
    base = str(_pick(config, "server_url", "base_url", default="https://qyapi.weixin.qq.com")).rstrip("/")
    corpid = str(_pick(config, "corpid", "sCorpID"))
    secret = str(_pick(config, "corpsecret", "sCorpsecret"))
    if not corpid or not secret:
        raise ValueError("qywx corpid/corpsecret missing")
    key = (base, corpid, secret)
    with _tokens_lock:
        cached = _tokens.get(key)
        if not refresh and cached and cached[1] > time.time():
            return base, cached[0]
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        result = _response_json(client.get(f"{base}/cgi-bin/gettoken", params={"corpid": corpid, "corpsecret": secret}))
    if result.get("errcode") != 0 or not result.get("access_token"):
        raise RuntimeError(f"qywx gettoken failed: {result.get('errcode')} {result.get('errmsg')}")
    token = result["access_token"]
    with _tokens_lock:
        _tokens[key] = (token, time.time() + int(result.get("expires_in", 7200)) - 60)
    return base, token


def _qywx_payload(config, item):
    base = {
        "touser": str(_pick(config, "touser", default="@all")),
        "agentid": int(_pick(config, "agentid", "sAgentid")),
    }
    if item.get("push_img_url") or item.get("push_link_url") or config.get("is_news") is True:
        base.update(
            {
                "msgtype": "news",
                "news": {
                    "articles": [
                        {
                            "title": _truncate_utf8(item["title"], 128),
                            "description": _truncate_utf8(item["content"], 500),
                            "url": item.get("push_link_url") or "",
                            "picurl": item.get("push_img_url") or "",
                        }
                    ]
                },
            }
        )
    else:
        text = "\n".join(x for x in (str(item.get("title") or ""), str(item.get("content") or "")) if x)
        base.update({"msgtype": "text", "text": {"content": text}})
    return base


def send_qywx(config, item):
    token = None
    for attempt in range(2):
        base, token = _qywx_token(config, refresh=attempt > 0)
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            result = _response_json(
                client.post(
                    f"{base}/cgi-bin/message/send",
                    params={"access_token": token},
                    json=_qywx_payload(config, item),
                )
            )
        if result.get("errcode") == 0:
            return
        if result.get("errcode") not in {40014, 42001}:
            break
    raise RuntimeError(f"qywx send failed: {result.get('errcode')} {result.get('errmsg')}")


def send_bark(config, item):
    base = str(_pick(config, "push_url", "url")).rstrip("/")
    if not base:
        raise ValueError("bark push_url missing")
    url = f"{base}/{urllib.parse.quote(item['title'], safe='')}/{urllib.parse.quote(item['content'], safe='')}"
    params = {"url": item.get("push_link_url") or "", "icon": item.get("push_img_url") or ""}
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        client.get(url, params={k: v for k, v in params.items() if v}).raise_for_status()


def send_telegram(config, item):
    token = str(_pick(config, "bot_token", "token"))
    chat_id = str(_pick(config, "chat_id", "chatid"))
    if not token or not chat_id:
        raise ValueError("telegram bot_token/chat_id missing")
    text = f"<b>{item['title']}</b>\n{item['content']}"
    if item.get("push_link_url"):
        text += f"\n<a href=\"{item['push_link_url']}\">打开链接</a>"
    method = "sendPhoto" if item.get("push_img_url") else "sendMessage"
    payload = {"chat_id": chat_id, "parse_mode": "HTML"}
    payload["caption" if method == "sendPhoto" else "text"] = text
    if method == "sendPhoto":
        payload["photo"] = item["push_img_url"]
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        result = _response_json(client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload))
    if not result.get("ok"):
        raise RuntimeError(f"telegram send failed: {result}")


def send_discord(config, item):
    url = str(_pick(config, "webhook_url", "url"))
    if not url:
        raise ValueError("discord webhook_url missing")
    embed = {"title": item["title"], "description": item["content"]}
    if item.get("push_link_url"):
        embed["url"] = item["push_link_url"]
    if item.get("push_img_url"):
        embed["thumbnail"] = {"url": item["push_img_url"]}
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        client.post(url, json={"embeds": [embed]}).raise_for_status()


def send_dingtalk(config, item):
    url = str(_pick(config, "webhook_url", "url"))
    token = str(_pick(config, "access_token", "token"))
    if not url:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={urllib.parse.quote(token)}"
    text = f"### {item['title']}\n\n{item['content']}"
    if item.get("push_link_url"):
        text += f"\n\n[查看详情]({item['push_link_url']})"
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        result = _response_json(client.post(url, json={"msgtype": "markdown", "markdown": {"title": item["title"], "text": text}}))
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"dingtalk send failed: {result}")


def send_pushdeer(config, item):
    url = str(_pick(config, "server_url", default="https://api2.pushdeer.com/message/push"))
    pushkey = str(_pick(config, "push_key", "pushkey"))
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        result = _response_json(client.post(url, data={"pushkey": pushkey, "text": item["title"], "desp": item["content"], "type": "markdown"}))
    if result.get("code", 0) != 0:
        raise RuntimeError(f"pushdeer send failed: {result}")


def send_feishu(config, item):
    app_id = str(_pick(config, "app_id", "appid"))
    app_secret = str(_pick(config, "app_secret", "appsecret"))
    receive_id = str(_pick(config, "receive_id"))
    receive_id_type = str(_pick(config, "receive_id_type", default="open_id"))
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        token = _response_json(client.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", json={"app_id": app_id, "app_secret": app_secret}))
        if token.get("code", 0) != 0:
            raise RuntimeError(f"feishu gettoken failed: {token}")
        result = _response_json(
            client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token['tenant_access_token']}"},
                json={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": f"{item['title']}\n{item['content']}"}, ensure_ascii=False)},
            )
        )
    if result.get("code", 0) != 0:
        raise RuntimeError(f"feishu send failed: {result}")


def send_serverchan3(config, item):
    sendkey = str(_pick(config, "send_key", "sendkey"))
    url = str(_pick(config, "server_url", default=f"https://sctapi.ftqq.com/{sendkey}.send"))
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        result = _response_json(client.post(url, data={"title": item["title"], "desp": item["content"]}))
    if result.get("code", 0) != 0:
        raise RuntimeError(f"serverchan3 send failed: {result}")


def send_email(config, item):
    message = EmailMessage()
    message["Subject"] = item["title"]
    message["From"] = str(_pick(config, "from_email", "sender"))
    message["To"] = str(_pick(config, "to_email", "receiver"))
    message.set_content(item["content"])
    host = str(_pick(config, "smtp_host", "host"))
    port = int(_pick(config, "smtp_port", "port", default=465))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as smtp:
        username = str(_pick(config, "username", "smtp_user"))
        password = str(_pick(config, "password", "smtp_password"))
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def send_webhook(config, item):
    url = str(_pick(config, "url", "webhook_url"))
    if not url:
        raise ValueError("webhook url missing")
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        client.post(url, json=item).raise_for_status()
