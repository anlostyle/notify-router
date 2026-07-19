import ipaddress
import json
import re
import shutil
import socket
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx


PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_INDEX_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 50 * 1024 * 1024
MAX_PLUGIN_FILES = 500


def _version_key(value):
    parts = re.findall(r"\d+|[A-Za-z]+", str(value or "").lstrip("vV"))
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts)


def _validate_remote_url(url):
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("插件源和安装包必须使用无凭据的 HTTPS 地址")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError(f"无法解析远程地址: {parsed.hostname}") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("插件源不能指向本机、内网或保留地址")
    return parsed.geturl()


class PluginStore:
    def __init__(self, store):
        self.store = store

    def _fetch_bytes(self, url, limit):
        current = str(url)
        with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20, connect=8)) as client:
            for _ in range(6):
                _validate_remote_url(current)
                with client.stream("GET", current, headers={"User-Agent": "Notify-Router-Plugin-Store/1"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("远程地址返回了无目标的重定向")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > limit:
                            raise ValueError("远程文件超过允许大小")
                    return bytes(payload)
        raise ValueError("远程地址重定向次数过多")

    def source_index(self, source_url):
        try:
            payload = json.loads(self._fetch_bytes(source_url, MAX_INDEX_BYTES))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("插件源不是合法的 JSON") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("plugins"), list):
            raise ValueError("插件源格式不受支持")
        plugins = []
        for item in payload["plugins"]:
            if not isinstance(item, dict):
                raise ValueError("插件源包含无效条目")
            plugin_id = str(item.get("id") or "")
            if not PLUGIN_ID_RE.fullmatch(plugin_id):
                raise ValueError(f"插件 ID 无效: {plugin_id}")
            if not item.get("version") or not item.get("archive_url") or not item.get("subdir"):
                raise ValueError(f"插件条目缺少版本或安装包信息: {plugin_id}")
            _validate_remote_url(item["archive_url"])
            subdir = PurePosixPath(str(item["subdir"]))
            if subdir.is_absolute() or ".." in subdir.parts:
                raise ValueError(f"插件子目录无效: {plugin_id}")
            plugins.append({**item, "id": plugin_id, "source_url": source_url, "source_name": payload.get("name") or source_url})
        return {"name": payload.get("name") or source_url, "plugins": plugins}

    def installed(self):
        result = {}
        for directory in self.store.plugins_dir.iterdir():
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or directory.name.startswith(".") or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            plugin_id = str(manifest.get("id") or directory.name)
            result[plugin_id] = {"version": str(manifest.get("version") or ""), "directory": directory.name}
        return result

    def catalog(self, sources):
        installed = self.installed()
        plugins = []
        source_states = []
        seen = set()
        for source_url in sources:
            try:
                index = self.source_index(source_url)
                source_states.append({"url": source_url, "name": index["name"], "status": "ok"})
                for item in index["plugins"]:
                    key = item["id"]
                    if key in seen:
                        continue
                    seen.add(key)
                    current = installed.get(key)
                    plugins.append(
                        {
                            **item,
                            "installed": bool(current),
                            "installed_version": current.get("version") if current else None,
                            "update_available": bool(current and _version_key(item["version"]) > _version_key(current.get("version"))),
                        }
                    )
            except (ValueError, httpx.HTTPError) as exc:
                source_states.append({"url": source_url, "name": source_url, "status": "error", "error": str(exc)})
        return {"sources": source_states, "plugins": plugins}

    def _entry(self, source_url, plugin_id):
        return next((item for item in self.source_index(source_url)["plugins"] if item["id"] == plugin_id), None)

    def install(self, source_url, plugin_id):
        if not PLUGIN_ID_RE.fullmatch(str(plugin_id or "")):
            raise ValueError("插件 ID 无效")
        entry = self._entry(source_url, plugin_id)
        if not entry:
            raise KeyError(plugin_id)
        archive = self._fetch_bytes(entry["archive_url"], MAX_ARCHIVE_BYTES)
        target = self.store.plugins_dir / plugin_id
        backup = None
        temp_root = self.store.data_dir / "tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="plugin-install-", dir=temp_root) as temp_name:
            staging = Path(temp_name) / plugin_id
            staging.mkdir()
            self._extract_plugin(archive, entry["subdir"], staging)
            manifest_path = staging / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("安装包缺少合法的 manifest.json") from exc
            if manifest.get("id") != plugin_id or str(manifest.get("version") or "") != str(entry["version"]):
                raise ValueError("安装包 manifest 与插件源条目不一致")
            self._preserve_runtime_paths(target, staging, manifest.get("preserve") or [])
            old = self.store.plugins_dir / f".{plugin_id}.old-{time.time_ns()}"
            if target.exists():
                target.replace(old)
            try:
                staging.replace(target)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                if old.exists():
                    old.replace(target)
                raise
            if old.exists():
                backup_dir = self.store.data_dir / "plugin-backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"{plugin_id}-{time.strftime('%Y%m%d-%H%M%S')}"
                old.replace(backup)
        return {"id": plugin_id, "version": entry["version"], "backup": str(backup) if backup else None, "restart_required": True}

    def uninstall(self, plugin_id):
        if not PLUGIN_ID_RE.fullmatch(str(plugin_id or "")):
            raise ValueError("插件 ID 无效")
        target = self.store.plugins_dir / plugin_id
        if not target.is_dir():
            raise KeyError(plugin_id)
        backup_dir = self.store.data_dir / "plugin-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{plugin_id}-{time.strftime('%Y%m%d-%H%M%S')}-removed"
        target.replace(backup)
        return {"id": plugin_id, "backup": str(backup), "restart_required": True}

    @staticmethod
    def _extract_plugin(archive, subdir, staging):
        prefix = PurePosixPath(str(subdir)).as_posix().strip("/") + "/"
        files = 0
        unpacked = 0
        try:
            with tempfile.SpooledTemporaryFile(max_size=MAX_ARCHIVE_BYTES) as source:
                source.write(archive)
                source.seek(0)
                with zipfile.ZipFile(source) as bundle:
                    for member in bundle.infolist():
                        name = PurePosixPath(member.filename).as_posix()
                        if not name.startswith(prefix) or member.is_dir():
                            continue
                        relative = PurePosixPath(name[len(prefix):])
                        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                            raise ValueError("安装包包含不安全路径")
                        if (member.external_attr >> 16) & 0o170000 == 0o120000:
                            raise ValueError("安装包不能包含符号链接")
                        files += 1
                        unpacked += member.file_size
                        if files > MAX_PLUGIN_FILES or unpacked > MAX_UNPACKED_BYTES:
                            raise ValueError("插件解压内容超过允许大小")
                        destination = staging.joinpath(*relative.parts)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with bundle.open(member) as source_file, destination.open("wb") as target_file:
                            shutil.copyfileobj(source_file, target_file)
        except zipfile.BadZipFile as exc:
            raise ValueError("插件安装包不是合法的 ZIP 文件") from exc
        if not files:
            raise ValueError("安装包中没有找到插件目录")

    @staticmethod
    def _preserve_runtime_paths(current, staging, paths):
        if not isinstance(paths, list) or len(paths) > 20:
            raise ValueError("manifest preserve 配置无效")
        for value in paths:
            relative = PurePosixPath(str(value))
            if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.as_posix() == "manifest.json":
                raise ValueError("manifest preserve 路径无效")
            source = current.joinpath(*relative.parts)
            if not source.exists():
                continue
            if source.is_symlink() or (source.is_dir() and any(path.is_symlink() for path in source.rglob("*"))):
                raise ValueError("运行数据不能包含符号链接")
            destination = staging.joinpath(*relative.parts)
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
