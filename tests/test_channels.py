from notifyhub.channels import _qywx_payload, _truncate_utf8


def test_qywx_news_payload_uses_custom_card_fields():
    payload = _qywx_payload(
        {"agentid": "1000021", "touser": "@all", "is_news": False},
        {
            "title": "📨 你收到新短信啦～",
            "content": "📱 设备：上海移动\n💬 短信内容：test",
            "push_img_url": "https://example.com/sms.png",
            "push_link_url": "https://notify.example.com/sms",
        },
    )
    assert payload["msgtype"] == "news"
    assert payload["agentid"] == 1000021
    assert payload["news"]["articles"][0]["picurl"].endswith("sms.png")


def test_utf8_truncation_never_splits_character():
    assert _truncate_utf8("中文", 4) == "中"
