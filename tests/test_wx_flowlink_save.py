import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from plugins.wx_flowlink_save.app import QywxMessage, extract_share_input, process_chat_message
from plugins.wx_flowlink_save.api.flowlink_api import FlowLinkApi
from plugins.wx_flowlink_save.utils import config


def test_extract_share_input_preserves_pickup_code():
    assert (
        extract_share_input("帮我转存 https://115.com/s/abc123 提取码：A1b2")
        == "https://115.com/s/abc123 提取码: A1b2"
    )


def test_extract_share_input_keeps_password_query():
    assert (
        extract_share_input("https://115cdn.com/s/abc123?password=9876#")
        == "https://115cdn.com/s/abc123?password=9876"
    )


def test_flowlink_client_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(
        config,
        "_cache",
        {"flowlink_url": "http://flowlink", "flowlink_token": "secret", "task_name": "115sub"},
    )
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    seen = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"receive_title": "demo", "recv_file_count": 1}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("plugins.wx_flowlink_save.api.flowlink_api.httpx.post", fake_post)
    result = FlowLinkApi().receive_share("https://115.com/s/abc123")
    assert result["success"] is True
    assert seen["url"] == "http://flowlink/api/transfer/share/receive"
    assert seen["json"] == {"share_url": "https://115.com/s/abc123", "task_name": "115sub"}
    assert seen["headers"]["X-Api-Token"] == "secret"


def test_success_is_sent_as_news(monkeypatch):
    monkeypatch.setattr(config, "_cache", {"task_name": "115sub"})
    monkeypatch.setattr(config, "_fetched_at", float("inf"))
    monkeypatch.setattr(
        "plugins.wx_flowlink_save.app.flowlink.receive_share",
        lambda _value: {
            "success": True,
            "receive_title": "Demo Movie",
            "recv_file_count": 2,
            "recv_folder_count": 1,
            "organizer": "flowlink_tmdb",
            "transfer_queue_added": True,
        },
    )

    class Sender:
        def __init__(self):
            self.news = None

        def send_text(self, *_args):
            raise AssertionError("success must use news")

        def send_news(self, *args):
            self.news = args
            return True

    sender = Sender()
    process_chat_message(QywxMessage("https://115.com/s/abc123", "user", "corp", "1", "text", "2"), sender)
    assert sender.news is not None
    assert sender.news[0] == "✅ FlowLink 转存整理已启动"
    assert "TMDB" in sender.news[1]
    assert "STRM" in sender.news[1]
