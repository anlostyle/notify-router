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


def test_emby_templates_cover_legacy_playback_and_library_format():
    playback = {
        "Event": "playback.start",
        "Date": "2026-07-20T12:54:21Z",
        "User": {"Name": "Rc"},
        "Server": {"Name": "Emby Home", "Id": "server-1", "Version": "4.8"},
        "Session": {
            "Client": "Senplayer",
            "DeviceName": "iPad",
            "RemoteEndPoint": "114.244.129.49",
            "PlayState": {"PositionTicks": 1_800_000_000_000, "PlayMethod": "DirectPlay", "VolumeLevel": 80},
        },
        "PlaybackInfo": {"PositionTicks": 1_800_000_000_000},
        "Item": {
            "Id": "episode/1",
            "Type": "Episode",
            "SeriesId": "series/1",
            "SeriesName": "剧集",
            "ParentIndexNumber": 1,
            "IndexNumber": 2,
            "Name": "第二集",
            "ProductionYear": 2026,
            "RunTimeTicks": 3_600_000_000_000,
            "Size": 2 * 1024**3,
            "Container": "mkv",
            "CommunityRating": 8.5,
            "Genres": ["剧情"],
            "Overview": "简介文本",
        },
    }
    event, template_type, context = parse_emby(playback, "https://emby.example")
    assert (event, template_type) == ("playback.start", "Emby.PlaybackStart")
    assert context["notification_title"] == "Rc 开始播放剧集：剧集·S01E02 (2026)"
    assert context["progress_bar"].startswith("●")
    assert "文件：剧集 | 2.00 GB | MKV | 音量 80%" in context["content"]
    assert context["item_url"].startswith("https://emby.example/web/index.html#!/item?id=episode%2F1")

    library = {
        "Event": "library.new",
        "Date": "2026-07-20T04:00:00Z",
        "Title": "将 12 项目添加到 剧集",
        "Server": {"Name": "Emby Home"},
        "Item": {
            "Type": "Series",
            "Name": "新剧",
            "ProductionYear": 2026,
            "Genres": ["Sci-Fi & Fantasy"],
        },
    }
    event, template_type, context = parse_emby(library)
    assert (event, template_type) == ("library.new", "Emby.LibraryNewSeries")
    assert context["notification_title"] == "剧集入库：新剧 (2026) | 共12集"
    assert context["content_lines"][0].startswith("入库：2026-")


def test_emby_parser_supports_all_legacy_event_branches():
    payload = {
        "Date": "2026-07-20T04:00:00Z",
        "Server": {"Name": "Emby"},
        "User": {"Name": "user"},
        "Session": {"Client": "Web", "DeviceName": "Mac", "RemoteEndPoint": "10.0.0.2"},
        "Item": {"Id": "movie", "Type": "Movie", "Name": "Film"},
    }
    expected = {
        "playback.pause": "Emby.PlaybackPause",
        "playback.unpause": "Emby.PlaybackUnpause",
        "playback.stop": "Emby.PlaybackEnd",
        "library.deleted": "Emby.LibraryDeleted",
        "user.authenticated": "Emby.UserAuthenticated",
        "user.authenticationfailed": "Emby.UserAuthenticationFailed",
        "plugins.plugininstalled": "Emby.PluginInstalled",
        "plugins.pluginuninstalled": "Emby.PluginUninstalled",
        "item.rate": "Emby.ItemRated",
        "item.markplayed": "Emby.ItemMarkedPlayed",
        "item.markunplayed": "Emby.ItemMarkedUnplayed",
        "system.updateavailable": "Emby.SystemUpdateAvailable",
        "system.serverstartup": "Emby.SystemStartup",
        "introskip.update": "Emby.IntroskipUpdate",
    }
    for event, template_type in expected.items():
        item = dict(payload["Item"])
        item["Type"] = "Episode" if event == "introskip.update" else item["Type"]
        current = dict(payload, Event=event, Item=item)
        if event == "user.authenticationfailed":
            current["Title"] = "来自 user 的登录"
            current["Description"] = "10.0.0.2 登录失败"
        if event.startswith("plugins."):
            current["PackageVersionInfo"] = {"name": "Plugin", "versionStr": "1.0"}
        if event == "system.updateavailable":
            current["PackageVersionInfo"] = {"versionStr": "4.9"}
        if event == "item.rate":
            current["Item"] = dict(item, UserData={"IsFavorite": True})
        result = parse_emby(current)
        assert result[1] == template_type
        assert result[2]["content"] or event == "system.updateavailable"


def test_fresh_store_seeds_bundled_emby_templates(tmp_path):
    store = Store(tmp_path)
    names = {template["name"] for template in store.templates}
    assert "emby_playback_start" in names
    assert "emby_library_new_movie" in names
    assert "emby_system_startup" in names

    event, template_type, context = parse_emby(
        {"Event": "playback.start", "User": {"Name": "User"}, "Item": {"Type": "Movie", "Name": "Film"}}
    )
    rendered = store.render_event({"bind_template": ["emby_playback_start"]}, template_type, context)
    assert rendered == ("User 开始播放电影：Film", "文件：电影")
