import re

import httpx

from .utils import UserState, config

state = UserState()


def media_type(item):
    if item.get("raw_type"):
        return item["raw_type"]
    if item.get("media_type"):
        return item["media_type"]
    return "movie" if item.get("type") == "电影" else "tv"


def is_ongoing(item):
    text = " ".join(str(item.get(k) or "") for k in ("year", "status", "air_status", "release_status"))
    return bool(re.search(r"现在|至今|连载|播出|ongoing|returning|present", text, re.I))


def search_status(item, is_movie):
    if is_movie:
        if item.get("is_in_library"):
            return "已入库"
        return "订阅中" if item.get("is_subscribed") else "未订阅"
    if item.get("is_in_library"):
        if is_ongoing(item):
            return "已入库｜追更中" if item.get("is_subscribed") else "已入库｜未追更"
        return "已入库｜已完结"
    if item.get("is_subscribed"):
        return "订阅中"
    return "未订阅｜连载中" if is_ongoing(item) else "未订阅｜已完结"


async def api(method, path, params=None, body=None):
    if not config.nextfind_base_url:
        return {"status": "error", "message": "NextFind OpenAPI 地址未配置"}
    if not config.nextfind_api_key:
        return {"status": "error", "message": "NextFind API Key 未配置"}
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.request(
            method,
            config.nextfind_base_url + path,
            params=params,
            json=body,
            headers={"X-API-Key": config.nextfind_api_key},
        )
    try:
        data = res.json()
    except Exception:
        data = {"message": res.text}
    if res.is_error:
        return {"status": "error", "message": data.get("message") or data.get("detail") or str(data)}
    return data


def fmt_search(items):
    if not items:
        return "没搜到。换个片名试试。"
    lines = ["🔎 搜索结果："]
    for i, item in enumerate(items[:8], 1):
        kind = media_type(item)
        is_movie = kind in {"movie", "电影"}
        icon = "🎬" if is_movie else "📺"
        display_type = item.get("type") or ("电影" if is_movie else "电视剧")
        status = search_status(item, is_movie)
        lines.append(f"\n{i}. {icon} {item.get('title')} ({item.get('year','')})")
        lines.append(f"   └ {display_type}｜{status}")
    lines.append("\n回复数字看资源，例如：1")
    lines.append("回复：订阅1")
    return "\n".join(lines)


def compact_tag(value):
    if not value:
        return ""
    if isinstance(value, list):
        value = "/".join(str(x) for x in value if x)
    return str(value).strip()


def clean_remark(resource, current=None):
    current = current or {}
    title = (current.get("title") or resource.get("title") or resource.get("name") or "").strip()
    year = str(resource.get("year") or current.get("year") or "").strip()
    remark = resource.get("remark") or resource.get("db_raw_text") or resource.get("title") or ""
    if "备注：" in remark:
        remark = remark.split("备注：", 1)[1]
    remark = re.sub(r"\{(?:tmdb|tvdb|imdb)-[^}]+\}", " ", remark, flags=re.I)
    remark = re.sub(r"名称[：:]", " ", remark).strip()
    remark = re.sub(r"标签[：:].*?(\n|$)", " ", remark).strip()
    remark = re.sub(r"^[🎬🎥📺\s]+", "", remark).strip()
    remark = re.sub(r"^(电影|剧集|电视剧)[：:｜|]?\s*", "", remark).strip()
    if title:
        remark = re.sub(rf"\[?{re.escape(title)}\]?\s*(\({re.escape(year)}\)|{re.escape(year)})?", " ", remark).strip()
    remark = re.sub(r"(整理成功|电影|剧集|电视剧)", " ", remark).strip()
    remark = remark.replace("[", " ").replace("]", " ")
    remark = re.sub(r"\(\s*\)", " ", remark).strip()
    remark = re.sub(r"\s+", " ", remark).strip()
    return remark[:80] or "参数未知"


def extract_size(resource, text=""):
    size = compact_tag(resource.get("share_size"))
    if re.fullmatch(r"\d+(?:\.\d+)?", size):
        size += "GB"
    if size:
        return size
    match = re.search(r"(?i)\b\d+(?:\.\d+)?\s*(?:GB|G|MB)\b", text or "")
    return match.group(0).replace(" ", "") if match else ""


def chinese_num_to_int(text):
    table = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + table.get(text[1:], 0)
    if "十" in text:
        left, right = text.split("十", 1)
        return table.get(left, 0) * 10 + table.get(right, 0)
    return table.get(text, 0)


def normalize_episode_label(label):
    if not label:
        return ""
    label = label.upper()
    label = re.sub(
        r"S(\d{1,2})E(\d{1,2})-E?(\d{1,2})",
        lambda m: f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}-E{int(m.group(3)):02d}",
        label,
    )
    label = re.sub(r"S(\d{1,2})E(\d{1,2})", lambda m: f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}", label)
    return label


def episode_label(resource, text):
    match = re.search(r"(?i)\bS(\d{1,2})E(\d{1,2})(?:-E?(\d{1,2}))?\b", text)
    if match:
        end = f"-E{int(match.group(3)):02d}" if match.group(3) else ""
        return f"S{int(match.group(1)):02d}E{int(match.group(2)):02d}{end}"
    match = re.search(r"(?i)\bS(\d{1,2})\s*更新至\s*(?:E|第)?(\d{1,2})", text)
    if match:
        return f"S{int(match.group(1)):02d}E01-E{int(match.group(2)):02d}"
    match = re.search(r"第([一二三四五六七八九十\d]+)季.*?(\d{1,2})\s*[-~到至]\s*(\d{1,2})", text)
    if match:
        season = chinese_num_to_int(match.group(1))
        if season:
            return f"S{season:02d}E{int(match.group(2)):02d}-E{int(match.group(3)):02d}"
    return normalize_episode_label(resource.get("parsed_episodes") or resource.get("episode_str") or "")


def derived_params(resource):
    attrs = resource.get("movie_attributes") or {}
    return " ".join(
        x
        for x in [
            compact_tag(attrs.get("resolution") or resource.get("video_resolution")),
            compact_tag(resource.get("source")),
            compact_tag(attrs.get("color")),
            compact_tag(attrs.get("audio")),
            compact_tag(resource.get("subtitle_type")),
            compact_tag(resource.get("subtitle_language")),
            compact_tag(attrs.get("group")),
        ]
        if x
    )


def resource_params(resource, current=None):
    remark = clean_remark(resource, current)
    size = extract_size(resource, remark)
    if size:
        remark = re.sub(r"(?i)\b\d+(?:\.\d+)?\s*(?:GB|G|MB)\b", " ", remark)
        remark = re.sub(r"\s+", " ", remark).strip(" -_[]|｜")
    episode = episode_label(resource, remark)
    if episode:
        remark = re.sub(r"(?i)\bS\d{1,2}E\d{1,2}(?:-E?\d{1,2})?\b", " ", remark)
        remark = re.sub(r"(?i)\bS\d{1,2}\s*更新至\s*(?:E|第)?\d{1,2}集?\b", " ", remark)
        remark = re.sub(r"第[一二三四五六七八九十\d]+季\s*\d{1,2}\s*[-~到至]\s*\d{1,2}", " ", remark)
        remark = re.sub(r"\s+", " ", remark).strip(" -_[]|｜")
    if not remark or remark in {"参数未知", "HDHiveAPI", "115网盘资源分享频道"} or "收录版本" in remark:
        remark = derived_params(resource)
    if episode and not remark:
        remark = episode
    elif episode and episode not in remark:
        remark = f"{episode}｜{remark}"
    return size, "" if remark == "参数未知" else remark


def fmt_resources(resources, current=None):
    if not resources:
        return "没找到可用资源。可以直接回复：订阅1，让系统后台补。"
    number_icons = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
    lines = ["🎞️ 资源列表："]
    for i, r in enumerate(resources[:8], 1):
        icon = number_icons[i - 1]
        size, params = resource_params(r, current)
        if size and params:
            lines.append(f"{icon} {size}｜{params}")
        elif size:
            lines.append(f"{icon} {size}")
        else:
            lines.append(f"{icon} {params or '参数未知'}")
    lines.append("\n回复数字直接转存，例如：1")
    return "\n".join(lines)


async def transfer_resource(user_state, idx):
    if idx < 0 or idx >= len(user_state["resources"]):
        return "先回复数字看资源，然后再输入资源序号。"
    r = user_state["resources"][idx]
    current = user_state.get("current") or {}
    data = await api(
        "POST",
        "/transfer",
        body={
            "slug": r.get("slug"),
            "title": r.get("title") or current.get("title"),
            "type": r.get("media_type") or current.get("media_type"),
            "source": r.get("source_type") or "hdhive",
            "remark": r.get("remark"),
            "tmdb_id": r.get("tmdb_id") or current.get("id"),
            "year": r.get("year"),
        },
    )
    if data.get("status") == "success":
        return data.get("message") or "转存请求已提交。"
    return "转存失败：" + str(data.get("message") or data)


async def handle_command(user, text):
    text = (text or "").strip()
    user_state = state.get(user)

    if text in {"帮助", "help", "/help"}:
        return "命令：\n搜 阿凡达\n1：看资源/转存\n订阅1\n订阅列表"

    if text == "订阅列表":
        data = await api("GET", "/subscriptions")
        items = (data.get("data") or [])[:10]
        if not items:
            return "当前没有订阅。"
        return "\n".join(["当前订阅："] + [f"{i + 1}. {x.get('title')} ({x.get('media_type')})" for i, x in enumerate(items)])

    if text.startswith(("搜 ", "搜索 ")):
        query = text.split(maxsplit=1)[1]
        data = await api("GET", "/search", {"query": query, "type": "all"})
        items = data.get("data") or []
        state.save(user, search=items, resources=[], current=None)
        return fmt_search(items)

    if text.startswith("订阅"):
        try:
            idx = int(text.replace("订阅", "").strip()) - 1
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(user_state["search"]):
            return "先回复：搜 片名，然后用 订阅1。"
        item = user_state["search"][idx]
        data = await api(
            "POST",
            "/subscriptions/add",
            body={
                "tmdb_id": item["id"],
                "title": item.get("title"),
                "media_type": media_type(item),
                "poster_path": item.get("poster"),
                "source": "openapi",
            },
        )
        if data.get("status") == "success":
            return "订阅成功：" + item.get("title", "")
        return "订阅失败：" + str(data.get("message") or data)

    if text.startswith("转存"):
        try:
            idx = int(text.replace("转存", "").strip()) - 1
        except Exception:
            idx = -1
        return await transfer_resource(user_state, idx)

    if text.isdigit():
        idx = int(text) - 1
        if user_state.get("resources"):
            return await transfer_resource(user_state, idx)
        if idx < 0 or idx >= len(user_state["search"]):
            return "这个序号不在当前搜索结果里。"
        item = user_state["search"][idx]
        data = await api("GET", "/resources/search", {"tmdb_id": item["id"], "media_type": media_type(item)})
        resources = data.get("data") or []
        current = {"id": item["id"], "title": item.get("title"), "year": item.get("year"), "media_type": media_type(item)}
        state.save(user, resources=resources, current=current)
        return f"{item.get('title')} 的资源：\n" + fmt_resources(resources, current)

    data = await api("GET", "/search", {"query": text, "type": "all"})
    items = data.get("data") or []
    state.save(user, search=items, resources=[], current=None)
    return fmt_search(items)
