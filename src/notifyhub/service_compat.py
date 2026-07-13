import re


EMBY_EVENTS = {
    "playback.start": "Emby.PlaybackStart",
    "playback.stop": "Emby.PlaybackEnd",
}


def _seconds(ticks):
    return max(0, int(ticks or 0) // 10_000_000)


def _duration(seconds):
    minutes, seconds = divmod(int(seconds or 0), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _size(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024


def parse_emby(payload):
    event = payload.get("Event")
    item = payload.get("Item") or {}
    item_type = str(item.get("Type") or "")
    if event == "library.new":
        template_type = "Emby.LibraryNewMovie" if item_type == "Movie" else "Emby.LibraryNewSeries"
    else:
        template_type = EMBY_EVENTS.get(event)
    if not template_type:
        raise ValueError(f"不支持的事件类型: {event}")

    session = payload.get("Session") or {}
    play_state = session.get("PlayState") or {}
    transcoding = session.get("TranscodingInfo") or {}
    streams = item.get("MediaStreams") or []
    video = next((x for x in streams if x.get("Type") == "Video"), {})
    position = _seconds(play_state.get("PositionTicks"))
    runtime = _seconds(item.get("RunTimeTicks"))
    method = play_state.get("PlayMethod") or session.get("PlayMethod") or "DirectPlay"
    method_text = {"DirectPlay": "直接播放", "DirectStream": "直接串流", "Transcode": "转码"}.get(method, str(method))
    series = item.get("SeriesName")
    season = item.get("ParentIndexNumber")
    episode = item.get("IndexNumber")
    title = item.get("Name") if item_type != "Episode" else f"{series} S{season}E{episode}"
    context = {
        "user": (payload.get("User") or {}).get("Name") or "",
        "title": title or "",
        "year": item.get("ProductionYear") or "",
        "progress_text": f"播放进度：{_duration(position)} / {_duration(runtime)}" if runtime else "",
        "container": str(item.get("Container") or "").upper(),
        "video_stream_title": video.get("DisplayTitle") or video.get("Title") or "",
        "transcoding_info": method_text,
        "bitrate": round(float(transcoding.get("Bitrate") or video.get("BitRate") or 0) / 1_000_000, 2),
        "current_cpu": transcoding.get("CompletionPercentage") or "",
        "server_name": (payload.get("Server") or {}).get("Name") or "",
        "size": _size(item.get("Size")),
        "client": session.get("Client") or "",
        "device_name": session.get("DeviceName") or "",
        "genres": "、".join(item.get("Genres") or []),
        "series_genres": "、".join(item.get("Genres") or []),
        "intro": item.get("Overview") or "",
        "episode_title": item.get("Name") or "",
        "release_year": item.get("ProductionYear") or "",
        "created_at": payload.get("Date") or payload.get("Timestamp") or "",
    }
    return event, template_type, context


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
