from notifyhub.store import Store


def legacy_config():
    return {
        "app": {"app_name": "NotifyHub", "site_url": "https://notify.example.com"},
        "channels": [
            {
                "name": "短信转发器",
                "type": "qywx",
                "config": {"corpid": "corp", "corpsecret": "secret", "agentid": "1", "touser": "@all"},
                "enabled": True,
            }
        ],
        "routes": [
            {
                "route_id": "route_sms",
                "route_name": "VoHive短信",
                "channel_name": ["短信转发器"],
                "push_img": "https://example.com/sms.png",
                "bind_template": [],
                "active": True,
            }
        ],
    }


def test_legacy_config_enqueues_and_records(tmp_path):
    store = Store(tmp_path)
    store.save_config(legacy_config())
    outbox_id = store.enqueue_router("route_sms", "title", "content", push_link_url="https://example.com")
    item = store.claim_delivery()
    assert item["outbox_id"] == outbox_id
    assert item["channel_name"] == "短信转发器"
    assert item["push_img_url"] == "https://example.com/sms.png"
    store.complete_delivery(item)
    assert store.delivery_status()[0]["status"] == "sent"
    record = store.recent_records()[0]
    assert record["route_id"] == "route_sms"
    assert record["status"] == 1
    assert " " in record["push_time"] and "+" not in record["push_time"]


def test_plugin_config_uses_existing_table_shape(tmp_path):
    store = Store(tmp_path)
    store.save_plugin_config("demo", "Demo", {"token": "value"})
    assert store.get_plugin_config("demo") == {"token": "value"}
    with store.connect() as db:
        raw = db.execute("SELECT config FROM plugins WHERE plugin_id='demo'").fetchone()[0]
    assert raw == "{'token': 'value'}"


def test_plugin_config_reads_legacy_python_literal(tmp_path):
    store = Store(tmp_path)
    now = "2026-01-01T00:00:00+00:00"
    with store.connect() as db:
        db.execute(
            "INSERT INTO plugins (plugin_id, plugin_name, config, status, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
            ("legacy", "Legacy", "{'enabled': True, 'items': ['a']}", now, now),
        )
    assert store.get_plugin_config("legacy") == {"enabled": True, "items": ["a"]}


def test_config_rejects_routes_with_missing_channels(tmp_path):
    store = Store(tmp_path)
    config = legacy_config()
    config["routes"][0]["channel_name"] = ["missing"]
    try:
        store.save_config(config)
    except ValueError as exc:
        assert "missing channels" in str(exc)
    else:
        raise AssertionError("invalid config was saved")


def test_processing_delivery_is_recovered_after_restart(tmp_path):
    store = Store(tmp_path)
    store.save_config(legacy_config())
    store.enqueue_router("route_sms", "title", "content")
    assert store.claim_delivery()
    assert store.delivery_status()[0]["status"] == "processing"
    assert Store(tmp_path).delivery_status()[0]["status"] == "retry"
