import json

from notifyhub.service_compat import parse_emby, parse_pve, parse_watchtower
from notifyhub.store import Store


def test_existing_native_service_payloads_render_bound_templates(tmp_path):
    store = Store(tmp_path)
    templates = {
        "template": [
            {"name": "watch", "type": "Watchtower.Update", "title": "{{updated_image_count}} - {{server_name}}", "content": "{{updated_image_list}}"}
        ]
    }
    store.templates_path.write_text(json.dumps(templates), encoding="utf-8")
    route = {"bind_template": ["watch"]}
    event, template_type, context = parse_watchtower(
        {
            "title": "Watchtower updates on host",
            "message": 'Found new example/app:latest image (abc)\nSession done',
            "server_name": "host",
        }
    )
    assert event == "update"
    assert store.render_event(route, template_type, context) == ("1 - host", "• example/app:latest")


def test_emby_and_pve_payload_detection():
    event, template_type, context = parse_emby(
        {"Event": "playback.start", "Item": {"Type": "Movie", "Name": "Film"}, "User": {"Name": "User"}}
    )
    assert (event, template_type, context["title"]) == ("playback.start", "Emby.PlaybackStart", "Film")

    event, template_type, context = parse_pve(
        {
            "title": "vzdump backup status (pve): OK",
            "message": "Details\n=======\n100  vm  OK  00:00:03  1 GB\nTotal running time: 3s\nTotal size: 1 GB",
        }
    )
    assert (event, template_type, context["machine_name"], context["total_size"]) == (
        "backup",
        "PVE.Backup",
        "pve",
        "1 GB",
    )
