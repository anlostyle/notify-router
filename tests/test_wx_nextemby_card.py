import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from plugins.wx_nextemby_card import app, commands
from plugins.wx_nextemby_card.api import nextemby_api
from plugins.wx_nextemby_card.api.nextemby_api import NextEmbyClient, NextEmbyError, parse_generate_output
from plugins.wx_nextemby_card.utils import config


BASE_CONFIG = {
    "allowed_users": "boss, other",
    "default_days": 365,
    "max_count": 10,
    "site1_name": "aemby",
    "site1_base_url": "https://nextemby.aemby.test/",
    "site1_username": "root",
    "site1_password": "secret",
    "site1_templates": "viiiip,sviiip",
    "site1_emby_url": "https://aemby.test",
    "site2_name": "avavv",
    "site2_base_url": "https://nextemby.avavv.test",
    "site2_username": "root",
    "site2_password": "secret2",
    "site2_templates": "viiiip",
}


@pytest.fixture(autouse=True)
def plugin_config(monkeypatch):
    values = dict(BASE_CONFIG)
    monkeypatch.setattr(config, "_cache", values)
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    return values


def test_parse_defaults_to_first_site_and_first_template():
    command = commands.parse_command("卡密 2")
    assert command.error == ""
    assert (command.site.name, command.count, command.days, command.template) == ("aemby", 2, 365, "viiiip")
    assert command.site.register_url == "https://nextemby.aemby.test/login"


def test_parse_site_days_and_template_in_any_order():
    command = commands.parse_command("发卡 sviiip 180天 aemby 3张")
    assert (command.site.slot, command.count, command.days, command.template) == ("site1", 3, 180, "sviiip")

    command = commands.parse_command("卡密 avavv 2 30")
    assert (command.site.slot, command.count, command.days, command.template) == ("site2", 2, 30, "viiiip")


def test_parse_bare_number_generates_cards():
    command = commands.parse_command("3")
    assert (command.action, command.count) == ("generate", 3)


def test_parse_rejects_unknown_template_and_limits():
    assert "可用模板：viiiip、sviiip" in commands.parse_command("卡密 2 vip").error
    assert "1 到 10" in commands.parse_command("卡密 50").error
    assert "天数" in commands.parse_command("卡密 1 99999").error
    assert commands.parse_command("作废").error.startswith("用法")
    assert commands.parse_command("你好").action == "help"


def test_render_card_drops_lines_with_empty_values():
    text = commands.render_card(
        commands.DEFAULT_CARD_TEMPLATE,
        {"site": "aemby", "days": "365", "code": "ABC", "register_url": "https://x/login", "emby_url": "", "template": ""},
    )
    assert "邀请码：ABC" in text
    assert "Emby 服务器" not in text
    assert commands.render_card("{unknown} {code}", {"code": "X"}) == "{unknown} X"


def test_parse_generate_output():
    batch = parse_generate_output("BATCH_ID:LOT1\nAAAA-1111\n\nBBBB-2222\n")
    assert batch.batch_id == "LOT1"
    assert batch.codes == ["AAAA-1111", "BBBB-2222"]
    with pytest.raises(NextEmbyError):
        parse_generate_output("")


def _client(handler):
    return NextEmbyClient(config.site("site1"), transport=httpx.MockTransport(handler))


def test_client_logs_in_then_generates_cards():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        if request.url.path == "/api/admin/login":
            return httpx.Response(200, json={"redirect": "/#/statistics"}, headers={"set-cookie": "sid=abc; Path=/"})
        assert request.headers.get("cookie") == "sid=abc"
        return httpx.Response(200, text="BATCH_ID:LOT9\nCODE-1\nCODE-2\n", headers={"content-type": "text/plain"})

    batch = _client(handler).generate(2, 365, "viiiip")
    assert batch.codes == ["CODE-1", "CODE-2"]
    assert calls[0][1] == "/api/admin/login"
    assert json.loads(calls[0][2]) == {"username": "root", "password": "secret"}
    assert json.loads(calls[1][2]) == {"duration_days": 365, "count": 2, "template_name": "viiiip"}


def test_client_relogs_in_once_when_session_expires():
    state = {"logins": 0, "batches": 0}

    def handler(request):
        if request.url.path == "/api/admin/login":
            state["logins"] += 1
            return httpx.Response(200, json={})
        state["batches"] += 1
        if state["batches"] == 1:
            return httpx.Response(307, headers={"location": "/login"})
        return httpx.Response(200, json={"status": "success", "data": [{"batch_id": "L", "total": 2, "remaining": 1}]})

    assert _client(handler).batches()[0]["batch_id"] == "L"
    assert state == {"logins": 2, "batches": 2}


def test_client_backs_off_after_failed_login():
    logins = []

    def handler(request):
        logins.append(request.url.path)
        return httpx.Response(401, json={"detail": "用户名或密码错误"})

    client = _client(handler)
    with pytest.raises(NextEmbyError, match="用户名或密码错误"):
        client.history()
    with pytest.raises(NextEmbyError, match="秒后再试"):
        client.history()
    assert logins == ["/api/admin/login"]


def test_generate_json_error_is_reported():
    def handler(request):
        if request.url.path == "/api/admin/login":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"status": "error", "message": "模板不存在"})

    with pytest.raises(NextEmbyError, match="模板不存在"):
        _client(handler).generate(1, 30, "x")


class FakeClient:
    def __init__(self):
        self.calls = []

    def generate(self, count, days, template):
        self.calls.append((count, days, template))
        return nextemby_api.CardBatch("LOT7", [f"CODE-{i}" for i in range(1, count + 1)])

    def batches(self):
        return [{"batch_id": "A", "total": 5, "remaining": 2, "duration_days": 365, "template_name": "viiiip"}, {"batch_id": "B", "total": 1, "remaining": 0}]

    def history(self):
        return [{"used_at": 1758700000.0, "used_by": "friend", "card_code": "CODE-X"}]

    def revoke(self, batch_id):
        return "已作废 2 张"


@pytest.fixture
def fake_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(commands, "client_for", lambda site: fake)
    return fake


def test_handle_generate_returns_one_message_per_card_and_summary(fake_client):
    replies = commands.handle_command("卡密 avavv 2")
    assert fake_client.calls == [(2, 365, "viiiip")]
    assert len(replies) == 3
    assert "邀请码：CODE-1" in replies[0]
    assert "注册地址：https://nextemby.avavv.test/login" in replies[0]
    assert "Emby 服务器" not in replies[0]
    assert "批次：LOT7" in replies[2]
    assert replies[2].endswith("作废 LOT7 avavv")


def test_handle_stock_history_and_revoke(fake_client):
    stock = commands.handle_command("库存")[0]
    assert "A  剩 2/5  365天 · viiiip" in stock
    assert "B " not in stock
    assert "friend  CODE-X" in commands.handle_command("记录")[0]
    assert "已作废 2 张" in commands.handle_command("作废 A")[0]


def test_authorize(plugin_config):
    assert app.authorize("boss") is None
    assert "UserID：stranger" in app.authorize("stranger")
    plugin_config["allowed_users"] = ""
    assert "你的 UserID：boss" in app.authorize("boss")


def test_duplicate_message_ids_are_dropped():
    app.seen_messages.clear()
    assert app.first_delivery("m1") is True
    assert app.first_delivery("m1") is False
    assert app.first_delivery("") is True


def test_card_thread_rejects_unauthorized_without_calling_nextemby(monkeypatch):
    sent = []

    class Sender:
        def send_text_message(self, text, to_user):
            sent.append((to_user, text))
            return True

    monkeypatch.setattr(app, "handle_command", lambda text: pytest.fail("should not run"))
    message = app.QywxMessage("卡密 1", "stranger", "corp", "0", "text", "m2")
    app.QywxCardThread(message, sender=Sender()).run()
    assert sent and sent[0][0] == "stranger" and "没有权限" in sent[0][1]


def test_split_text_respects_byte_limit():
    parts = app.split_text("\n".join(["邀请码" * 50] * 10), limit=400)
    assert len(parts) > 1
    assert all(len(part.encode("utf-8")) <= 400 for part in parts)
