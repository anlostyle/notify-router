import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


EVENT_LABELS = {
    "playback.start": "开始播放",
    "playback.pause": "暂停播放",
    "playback.unpause": "恢复播放",
    "playback.stop": "停止播放",
    "library.new": "入库",
    "library.deleted": "删除媒体库",
    "user.authenticated": "登录成功",
    "user.authenticationfailed": "登录失败",
    "plugins.plugininstalled": "已安装",
    "plugins.pluginuninstalled": "卸载",
    "item.rate": "最爱",
    "item.markunplayed": "未播放",
    "item.markplayed": "已播放",
    "system.updateavailable": "新版本",
    "system.serverstartup": "启动",
    "introskip.update": "标记更新",
}


# PlaybackEnd is the name used by the original NotifyHub-compatible API.
# Keep it for stop events so existing routes do not need to be reconfigured.
EMBY_EVENTS = {
    "playback.start": "Emby.PlaybackStart",
    "playback.pause": "Emby.PlaybackPause",
    "playback.unpause": "Emby.PlaybackUnpause",
    "playback.stop": "Emby.PlaybackEnd",
    "library.deleted": "Emby.LibraryDeleted",
    "user.authenticated": "Emby.UserAuthenticated",
    "user.authenticationfailed": "Emby.UserAuthenticationFailed",
    "plugins.plugininstalled": "Emby.PluginInstalled",
    "plugins.pluginuninstalled": "Emby.PluginUninstalled",
    "item.rate": "Emby.ItemRated",
    "item.markunplayed": "Emby.ItemMarkedUnplayed",
    "item.markplayed": "Emby.ItemMarkedPlayed",
    "system.updateavailable": "Emby.SystemUpdateAvailable",
    "system.serverstartup": "Emby.SystemStartup",
    "introskip.update": "Emby.IntroskipUpdate",
}

ITEM_TYPE_LABELS = {
    "Movie": "电影",
    "Episode": "剧集",
    "Series": "剧集",
    "Season": "季",
    "Audio": "音乐",
    "MusicAlbum": "专辑",
}

PLAY_METHOD_LABELS = {
    "DirectPlay": "直接播放",
    "DirectStream": "直接串流",
    "Transcode": "转码播放",
}

_TICKS_PER_SECOND = 10_000_000
_LOCAL_TIMEZONE = timezone(timedelta(hours=8))
_LABEL_LINE = re.compile(r"^\s*[^:\r\n]{1,64}[：:]\s*.*$")


def normalize_escaped_line_breaks(value):
    """Decode only line-oriented ``\\n`` payloads, leaving command text intact."""
    text = str(value or "")
    if "\\n" not in text and "\\r" not in text:
        return text
    parts = re.split(r"\\r\\n|\\n|\\r", text)
    if len(parts) < 2 or not all(_LABEL_LINE.match(part) for part in parts):
        return text
    return "\n".join(parts)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _seconds(ticks):
    return max(0, int(_number(ticks) // _TICKS_PER_SECOND))


def _duration(seconds):
    minutes, seconds = divmod(int(seconds or 0), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _size(value):
    value = _number(value)
    if value <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return ""


def _clip(value, limit=506):
    text = str(value or "")
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[: limit - 3].decode("utf-8", errors="ignore") + "..."


def _line(head, values, separator=" | ", end=""):
    values = [str(value) for value in values if value is not None and str(value) != ""]
    return f"{head}：{separator.join(values)}{end}" if values else ""


def _compact_title(value):
    return re.sub(r"\s+", "", str(value or "").title())


def _format_date(value, short=False):
    if not value:
        return ""
    text = str(value).strip()
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(_LOCAL_TIMEZONE)
        if short:
            return parsed.strftime("%Y-%m-%d")
        weekdays = "星期一 星期二 星期三 星期四 星期五 星期六 星期日".split()
        return parsed.strftime(f"%Y-%m-%d {weekdays[parsed.weekday()]} %H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        return text


def _names(values, limit=None):
    if isinstance(values, (str, bytes)):
        values = [values]
    result = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("Name") or value.get("name") or ""
        value = str(value or "").strip()
        if value:
            result.append(value)
        if limit and len(result) >= limit:
            break
    return result


def _genres(values):
    result = "·".join(_names(values))
    return result.replace("Sci-Fi & Fantasy", "科幻·奇幻").replace("动作冒险", "动作·冒险")


def _item_type_name(item_type):
    return ITEM_TYPE_LABELS.get(item_type, item_type or "媒体")


def _item_name(item, item_type):
    if item_type == "Episode":
        series = item.get("SeriesName") or item.get("Series") or ""
        season = item.get("ParentIndexNumber")
        episode = item.get("IndexNumber")
        try:
            season = int(season)
        except (TypeError, ValueError):
            season = 0
        try:
            episode = int(episode)
        except (TypeError, ValueError):
            episode = 0
        suffix = f"S{season:02d}E{episode:02d}" if season or episode else ""
        return f"{series}·{suffix}" if series and suffix else str(item.get("Name") or series or suffix)
    if item_type == "Audio":
        artists = _names(item.get("Artists"))
        artists_text = "|".join(artists[:3]) + ("等" if len(artists) > 3 else "")
        song = str(item.get("Name") or "")
        return f"{artists_text}·{song}" if artists_text and song else song or artists_text
    return str(item.get("Name") or "")


def _streams(item):
    streams = item.get("MediaStreams") or []
    if streams:
        return streams
    sources = item.get("MediaSources") or []
    if sources and isinstance(sources[0], dict):
        return sources[0].get("MediaStreams") or []
    return []


def _first_stream(item):
    streams = _streams(item)
    return streams[0] if streams else {}


def _media_info(stream, item_type):
    if not stream:
        return ""
    bit_depth = stream.get("BitDepth")
    bit_depth = f"{bit_depth} Bit" if bit_depth else ""
    bitrate = _size(stream.get("BitRate"))
    bitrate = f"{bitrate}ps" if bitrate else ""
    if item_type == "Audio":
        channels = stream.get("Channels")
        channel_text = "单声道" if channels == 1 else "立体声" if channels == 2 else "多声道" if channels else ""
        sample_rate = _number(stream.get("SampleRate"))
        resolution = f"{round(sample_rate / 1000, 1)} khz" if sample_rate else ""
        color = channel_text
    else:
        color = str(stream.get("VideoRange") or "")
        color = color.upper().replace("DOLBYVISION", "杜比视界").replace("DOLBY VISION", "杜比视界")
        resolution = str(stream.get("DisplayTitle") or "")
        resolution = resolution.upper().replace("DOLBYVISION", "杜比视界").replace("DOLBY VISION", "杜比视界")
    return _line("媒体", [bit_depth, bitrate, color, resolution])


def _item_url(emby_url, item_id, server_id):
    if not emby_url or not item_id:
        return ""
    return (
        f"{emby_url.rstrip('/')}/web/index.html#!/item?id={quote(str(item_id), safe='')}"
        f"&serverId={quote(str(server_id or ''), safe='')}"
    )


def _image_url(emby_url, item_id):
    if not emby_url or not item_id:
        return ""
    return f"{emby_url.rstrip('/')}/emby/Items/{quote(str(item_id), safe='')}/Images/Primary"


def _content(context, *values):
    lines = [str(value) for value in values if value is not None and str(value) != ""]
    context["content_lines"] = lines
    context["content"] = _clip("\n".join(lines))


def _item_context(context, item):
    item_type = context["item_type"]
    context.update(
        {
            "item_type_name": _item_type_name(item_type),
            "item_name": _item_name(item, item_type),
            "year": item.get("ProductionYear") or "",
            "premiere_date": _format_date(item.get("PremiereDate"), short=True),
            "score_origin": item.get("CommunityRating") or "",
            "official_rating": item.get("OfficialRating") or "",
            "genres": "、".join(_names(item.get("Genres"))),
            "genres_text": _genres(item.get("Genres")),
            "people": " | ".join(_names(item.get("People"), 5)),
            "overview": _clip(str(item.get("Overview") or "").lstrip()),
            "container": str(item.get("Container") or "").upper(),
            "size": _size(item.get("Size")),
            "media_info": _media_info(_first_stream(item), item_type),
        }
    )
    context["year_label"] = f"({context['year']})" if context["year"] else ""
    context["premiere_text"] = _line("首映", [context["premiere_date"]])
    context["score_text"] = _line("评分", [context["score_origin"], context["official_rating"]])
    context["film_info"] = _line("影片", [context["year"], context["score_origin"], context["official_rating"], context["genres_text"]])
    context["people_text"] = _line("主演", [context["people"]])
    context["overview_text"] = _line("简介", [context["overview"]])
    album = str(item.get("Album") or "")
    album = f"《{album}》" if album else ""
    artists = "|".join(_names(item.get("Artists"))[:3])
    if len(_names(item.get("Artists"))) > 3:
        artists += "等"
    context["album_info"] = _line("专辑", [artists, context["year"], album])
    context["title"] = context["item_name"]


def _base_emby_context(payload, event, emby_url):
    item = payload.get("Item") or {}
    session = payload.get("Session") or {}
    user = payload.get("User") or {}
    server = payload.get("Server") or {}
    item = item if isinstance(item, dict) else {}
    session = session if isinstance(session, dict) else {}
    user = user if isinstance(user, dict) else {}
    server = server if isinstance(server, dict) else {}
    item_type = str(item.get("Type") or "")
    server_name = _compact_title(server.get("Name"))
    server_id = server.get("Id") or ""
    emby_url = str(emby_url or payload.get("emby_url") or "").rstrip("/")
    remote_ip = str(session.get("RemoteEndPoint") or payload.get("RemoteEndPoint") or "")
    location = str(session.get("Location") or payload.get("Location") or "")
    client = _compact_title(session.get("Client"))
    device = _compact_title(session.get("DeviceName"))
    client_version = str(session.get("ApplicationVersion") or "")
    item_id = item.get("Id") or ""
    context = {
        "event_code": event,
        "event_label": EVENT_LABELS.get(event, event or "未定义事件"),
        "event": EVENT_LABELS.get(event, event or "未定义事件"),
        "user": str(user.get("Name") or ""),
        "username": str(user.get("Name") or ""),
        "user_data": user,
        "item": item,
        "item_data": item,
        "item_type": item_type,
        "session": session,
        "session_data": session,
        "server": server,
        "server_data": server,
        "payload": payload,
        "server_name": server_name,
        "server_id": server_id,
        "server_version": str(server.get("Version") or ""),
        "server_info": _line("设备", [server_name, server.get("Version") or ""]),
        "server_url": f"{emby_url}/web/index.html" if emby_url else "",
        "date": _format_date(payload.get("Date") or payload.get("Timestamp")),
        "date_text": _line("时间", [_format_date(payload.get("Date") or payload.get("Timestamp"))]),
        "remote_ip": remote_ip,
        "location": location,
        "address_info": _line("地址", [remote_ip, location], end=""),
        "client": client,
        "client_version": client_version,
        "device": device,
        "device_name": device,
        "device_info": _line("设备", [client, client_version, device], end=""),
        "device_play_info": _line("设备", [client, device, server_name], end=""),
        "item_url": _item_url(emby_url, item_id, server_id),
        "image_url": _image_url(emby_url, item_id),
        "emby_url": emby_url,
        "created_at": payload.get("Date") or payload.get("Timestamp") or "",
    }
    _item_context(context, item)
    return context


def _template_type(event, item_type):
    if event == "library.new":
        if item_type == "Movie":
            return "Emby.LibraryNewMovie"
        if item_type == "Audio":
            return "Emby.LibraryNewAudio"
        return "Emby.LibraryNewSeries"
    return EMBY_EVENTS.get(event)


def _playback_context(context, payload):
    item = context["item"]
    session = context["session"]
    playback = payload.get("PlaybackInfo") or {}
    playback = playback if isinstance(playback, dict) else {}
    play_state = playback.get("PlayState") or session.get("PlayState") or {}
    now_playing = playback.get("NowPlayingItem") or {}
    stream = _first_stream(now_playing) if now_playing else _first_stream(item)
    streams = _streams(now_playing) if now_playing else _streams(item)
    video = next((value for value in streams if value.get("Type") == "Video"), {})
    position_ticks = playback.get("PositionTicks")
    if position_ticks is None:
        position_ticks = play_state.get("PositionTicks")
    runtime_ticks = item.get("RunTimeTicks") or now_playing.get("RunTimeTicks")
    runtime_seconds = _seconds(runtime_ticks)
    position_seconds = min(_seconds(position_ticks), runtime_seconds) if runtime_seconds else _seconds(position_ticks)
    method = play_state.get("PlayMethod") or playback.get("PlayMethod") or session.get("PlayMethod") or "DirectPlay"
    play_method = "" if context["event_code"] == "playback.stop" else PLAY_METHOD_LABELS.get(method, str(method))
    if runtime_seconds:
        percent_value = min(100, max(0, _number(position_ticks) / _number(runtime_ticks) * 100))
        filled = min(27, max(0, int(27 * _number(position_ticks) // _number(runtime_ticks))))
        progress_bar = "●" * filled + "○" * (27 - filled)
        total_minutes = int(runtime_seconds / 60)
        played_minutes = int(position_seconds / 60)
        left_minutes = max(0, total_minutes - played_minutes)
        progress_text = _line(
            "进度",
            [f"{percent_value:.2f}%", f"余{left_minutes}分钟", f"共{total_minutes}分钟", play_method],
            end="",
        )
    else:
        progress_bar = ""
        progress_text = ""
    volume = play_state.get("VolumeLevel")
    volume_text = f"音量 {volume}%" if volume is not None and context["event_code"] != "playback.stop" else ""
    context.update(
        {
            "playback": playback,
            "playback_data": playback,
            "play_state": play_state,
            "play_method": play_method,
            "volume": volume_text,
            "position_seconds": position_seconds,
            "runtime_seconds": runtime_seconds,
            "position": _duration(position_seconds),
            "runtime": _duration(runtime_seconds),
            "progress_bar": progress_bar,
            "progress_text": progress_text,
            "media_info": _media_info(stream, context["item_type"]),
            "file_info": _line("文件", [context["item_type_name"], context["size"], context["container"], volume_text], end=""),
            "video_stream_title": video.get("DisplayTitle") or video.get("Title") or "",
            "transcoding_info": PLAY_METHOD_LABELS.get(method, str(method)),
            "bitrate": round(_number((playback.get("TranscodingInfo") or session.get("TranscodingInfo") or {}).get("Bitrate") or video.get("BitRate")) / 1_000_000, 2),
            "current_cpu": (playback.get("TranscodingInfo") or session.get("TranscodingInfo") or {}).get("CompletionPercentage") or "",
        }
    )
    context["notification_title"] = f"{context['username']} {context['event_label']}{context['item_type_name']}：{context['item_name']}"
    if context["item_type"] != "Audio" and context["year_label"]:
        context["notification_title"] += f" {context['year_label']}"
    context["notification_title"] = context["notification_title"].rstrip()
    context["device_play_info"] = _line("设备", [context["client"], context["device"], context["server_name"]], end="")
    _content(
        context,
        context["media_info"],
        context["file_info"],
        context["progress_bar"],
        context["progress_text"],
        context["date_text"],
        context["device_play_info"],
        context["address_info"],
        context["film_info"],
        context["people_text"],
        context["overview_text"],
    )


def parse_emby(payload, emby_url=""):
    if not isinstance(payload, dict):
        raise ValueError("Emby 请求体不是合法的 JSON 对象")
    event = str(payload.get("Event") or "")
    item = payload.get("Item") or {}
    item_type = str(item.get("Type") or "")
    template_type = _template_type(event, item_type)
    if not template_type:
        raise ValueError(f"不支持的事件类型: {event}")

    context = _base_emby_context(payload, event, emby_url)
    if event.startswith("playback."):
        _playback_context(context, payload)
        return event, template_type, context

    if event == "system.serverstartup":
        context["notification_title"] = f"Emby 服务器 {context['server_name']} 已启动"
        _content(context, context["date_text"], context["server_info"])
        return event, template_type, context

    if event == "system.updateavailable":
        package = payload.get("PackageVersionInfo") or {}
        context["new_version"] = str(package.get("versionStr") or package.get("version") or "")
        context["current_version_text"] = _line("当前版本", [context["server_version"]])
        context["new_version_text"] = _line("更新版本", [context["new_version"]])
        context["notification_title"] = f"服务器 {context['server_name']} 可升级 {context['event_label']}"
        _content(context, context["date_text"], context["current_version_text"], context["new_version_text"])
        return event, template_type, context

    if event in {"user.authenticated", "user.authenticationfailed"}:
        if event == "user.authenticationfailed":
            title = str(payload.get("Title") or "")
            match = re.search(r"来自 (.*) 的登录", title)
            if match:
                context["username"] = context["user"] = match.group(1)
            description = str(payload.get("Description") or "")
            ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", description)
            context["remote_ip"] = ip_match.group(0) if ip_match else context["remote_ip"]
            context["address_info"] = _line("地址", [context["remote_ip"], context["location"]], end="")
            context["notification_title"] = f"{context['username']} 在 {context['server_name']} 上 登录失败"
        else:
            context["notification_title"] = f"{context['username']} 在 {context['server_name']} 上 登录成功"
        _content(context, context["date_text"], context["device_info"], context["address_info"])
        return event, template_type, context

    if event in {"plugins.plugininstalled", "plugins.pluginuninstalled"}:
        package = payload.get("PackageVersionInfo") or {}
        context["plugin_name"] = _compact_title(package.get("name"))
        context["plugin_version"] = str(package.get("versionStr") or "")
        context["plugin_info"] = _line("插件", [context["plugin_name"]])
        context["plugin_version_text"] = _line("版本", [context["plugin_version"]])
        context["notification_title"] = (
            f"{context['plugin_name']} 已从 {context['server_name']} 卸载"
            if event == "plugins.pluginuninstalled"
            else f"{context['plugin_name']} 已安装到 {context['server_name']}"
        )
        _content(context, context["date_text"], context["plugin_info"], context["plugin_version_text"], context["server_info"])
        return event, template_type, context

    if event == "library.deleted":
        context["item_path"] = str(item.get("Path") or "")
        context["path_text"] = _line("路径", [context["item_path"]], end="")
        context["notification_title"] = f"删除媒体库：{context['item_name']}"
        _content(context, context["date_text"], context["server_info"], context["path_text"])
        return event, template_type, context

    if event == "introskip.update":
        context["notification_title"] = f"{context['username']} 标记更新：{context['item_name']}"
        _content(context, context["date_text"], context["device_play_info"], context["address_info"])
        return event, template_type, context

    if event in {"item.markplayed", "item.markunplayed", "item.rate"}:
        user_data = item.get("UserData") or {}
        context["is_favorite"] = bool(user_data.get("IsFavorite"))
        if event == "item.rate":
            context["notification_title"] = (
                f"{context['username']} 收藏了 {context['item_type_name']}：{context['item_name']} {context['year_label']}"
                if context["is_favorite"]
                else f"{context['username']} 取消收藏了 {context['item_type_name']}：{context['item_name']} {context['year_label']}"
            ).rstrip()
        else:
            context["notification_title"] = (
                f"{context['username']} 标记 {context['item_type_name']}：{context['item_name']} "
                f"{context['year_label']}为{context['event_label']}"
            ).strip()
        if item_type == "Audio":
            _content(context, context["date_text"], context["premiere_text"], context["media_info"], context["server_info"], context["album_info"], context["score_text"])
        else:
            _content(context, context["date_text"], context["premiere_text"], context["media_info"], context["server_info"], context["film_info"], context["people_text"], context["overview_text"])
        return event, template_type, context

    if event == "library.new":
        context["date_text"] = _line("入库", [context["date"]])
        context["episode_count"] = ""
        if item_type == "Series":
            title = str(payload.get("Title") or "")
            match = re.search(r"(?:将|已添加了) (\d+) (?:项目添加到|项到)", title)
            context["episode_count"] = match.group(1) if match else ""
        context["notification_title"] = context["item_type_name"] + context["event_label"] + "：" + context["item_name"]
        if context["year_label"]:
            context["notification_title"] += f" {context['year_label']}"
        if item_type == "Series" and context["episode_count"]:
            context["notification_title"] += f" | 共{context['episode_count']}集"
        if item_type == "Audio":
            _content(context, context["date_text"], context["premiere_text"], context["media_info"], context["server_info"], context["album_info"], context["score_text"])
        elif item_type == "Series":
            _content(context, context["date_text"], context["premiere_text"], context["server_info"], context["film_info"], context["people_text"], context["overview_text"])
        else:
            _content(context, context["date_text"], context["premiere_text"], context["media_info"], context["server_info"], context["film_info"], context["people_text"], context["overview_text"])
        return event, template_type, context

    raise ValueError(f"不支持的事件类型: {event}")


def parse_watchtower(payload):
    title = str(payload.get("title") or "")
    message = str(payload.get("message") or "")
    updates = list(dict.fromkeys(re.findall(r"Found new (.+?) image(?: |$)", message)))
    errors = [line.strip() for line in message.splitlines() if any(x in line for x in ("Could not do a head request", "Reason:", "Unable to update container"))]
    server_name = payload.get("server_name") or title.removeprefix("Watchtower updates on ") or "Watchtower"
    if updates:
        event, template_type = "update", "Watchtower.Update"
        context = {"updated_image_count": len(updates), "updated_image_list": "\n".join(f"• {x}" for x in updates), "server_name": server_name}
    elif errors:
        event, template_type = "error", "Watchtower.Error"
        context = {"update_title": f"检测更新出错 - {server_name}", "update_content": "\n".join(errors), "server_name": server_name}
    elif "Watchtower" in title or "Watchtower" in message:
        event, template_type = "start", "Watchtower.Start"
        context = {"update_title": title or f"Watchtower 已启动 - {server_name}", "update_content": message, "server_name": server_name}
    else:
        raise ValueError("不支持的事件类型: unknown")
    return event, template_type, context


def parse_pve(payload):
    title = str(payload.get("title") or "")
    message = str(payload.get("message") or "").strip("`\n ")
    lower = title.lower()
    if "vzdump backup status" in lower:
        event, template_type = "backup", "PVE.Backup"
        machine = re.search(r"\(([^)]+)\)", title)
        status = title.rsplit(":", 1)[-1].strip()
        total_time = re.search(r"Total running time:\s*(.+)", message)
        total_size = re.search(r"Total size:\s*(.+)", message)
        details = []
        for line in message.splitlines():
            fields = re.split(r"\s{2,}", line.strip())
            if len(fields) >= 5 and fields[0].isdigit():
                details.append(tuple(fields[:5]))
        context = {
            "machine_name": machine.group(1) if machine else "PVE",
            "task_type": "备份任务",
            "task_status": status,
            "details": details,
            "total_time": total_time.group(1) if total_time else "",
            "total_size": total_size.group(1) if total_size else "",
        }
    elif "prun" in lower:
        event, template_type = "pruning", "PVE.Pruning"
        context = _pve_fields(title, message, "精简任务")
    elif "garbage" in lower:
        event, template_type = "garbage", "PVE.Garbage"
        context = _pve_fields(title, message, "垃圾回收")
    else:
        raise ValueError("不支持的 PVE 通知")
    return event, template_type, context


def _pve_fields(title, message, task_type):
    values = {}
    for line in message.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip().lower().replace(" ", "_")] = value.strip()
    machine = re.search(r"\(([^)]+)\)", title)
    return {
        "machine_name": machine.group(1) if machine else "PVE",
        "task_type": task_type,
        "task_status": title.rsplit(":", 1)[-1].strip(),
        "datastore_name": values.get("datastore", ""),
        "job_id": values.get("job_id", ""),
        "index_file_count": values.get("index_file_count", ""),
        "removed_garbage": values.get("removed_garbage", ""),
        "original_data_usage": values.get("original_data_usage", ""),
        "on_disk_usage": values.get("on_disk_usage", ""),
        "deduplication_factor": values.get("deduplication_factor", ""),
    }
