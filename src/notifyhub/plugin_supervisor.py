import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from fastapi import HTTPException, Request, Response

from .store import enabled


logger = logging.getLogger(__name__)


@dataclass
class PluginProcess:
    plugin_id: str
    version: str
    manifest: dict
    process: subprocess.Popen
    socket: Path


class PluginSupervisor:
    def __init__(self, store):
        self.store = store
        self.runtime_dir = store.data_dir / "plugin-runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        instance = hashlib.sha256(str(store.data_dir).encode()).hexdigest()[:10]
        self.socket_dir = Path(os.environ.get("PLUGIN_SOCKET_DIR", "/tmp/notify-router-plugins")) / instance
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self.processes = {}
        self.manifests = []

    def _enabled(self, plugin_id):
        data = self.store.get_plugin_data(plugin_id)
        return not data or enabled(data.get("status", True))

    def start_all(self):
        for directory in sorted(self.store.plugins_dir.iterdir()):
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or directory.name.startswith(".") or not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if self._enabled(str(manifest.get("id") or directory.name)):
                try:
                    self.reload(directory.name)
                except Exception:
                    logger.exception("plugin worker startup failed: %s", directory.name)

    def _spawn(self, plugin_id):
        directory = self.store.plugins_dir / plugin_id
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", plugin_id)
        socket = self.socket_dir / f"{safe[:24]}-{str(time.time_ns())[-10:]}.sock"
        env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(value for value in (package_root, env.get("PYTHONPATH")) if value)
        process = subprocess.Popen(
            [sys.executable, "-m", "notifyhub.plugin_worker", "--plugin-dir", str(directory), "--socket", str(socket), "--data-dir", str(self.store.data_dir)],
            env=env,
        )
        candidate = PluginProcess(plugin_id, str(manifest.get("version") or ""), manifest, process, socket)
        try:
            self._wait(candidate)
            return candidate
        except Exception:
            self._terminate(candidate)
            raise

    @staticmethod
    def _client(item, timeout=5):
        return httpx.Client(transport=httpx.HTTPTransport(uds=str(item.socket)), base_url="http://plugin", timeout=timeout)

    def _wait(self, item):
        timeout = max(10, min(float(os.environ.get("PLUGIN_START_TIMEOUT", "120")), 300))
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            if item.process.poll() is not None:
                raise RuntimeError(f"plugin worker exited during startup: {item.plugin_id}")
            try:
                with self._client(item) as client:
                    response = client.get("/__health")
                    response.raise_for_status()
                    return
            except (OSError, httpx.HTTPError) as exc:
                last_error = exc
                time.sleep(0.2)
        raise RuntimeError(f"plugin worker health timeout: {item.plugin_id}: {last_error}")

    def _activate(self, item):
        with self._client(item, 30) as client:
            response = client.post("/__activate")
            response.raise_for_status()

    @staticmethod
    def _terminate(item):
        if item.process.poll() is None:
            item.process.terminate()
            try:
                item.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                item.process.kill()
                item.process.wait(timeout=3)
        item.socket.unlink(missing_ok=True)

    def _sync_manifests(self):
        self.manifests[:] = [item.manifest for item in sorted(self.processes.values(), key=lambda value: value.plugin_id)]

    def reload(self, plugin_id):
        candidate = self._spawn(plugin_id)
        old = self.processes.get(plugin_id)
        if old and old.process.poll() is None:
            old.process.send_signal(signal.SIGSTOP)
        try:
            self._activate(candidate)
        except Exception:
            self._terminate(candidate)
            if old and old.process.poll() is None:
                old.process.send_signal(signal.SIGCONT)
            raise
        if old:
            if old.process.poll() is None:
                old.process.send_signal(signal.SIGCONT)
            self._terminate(old)
        self.processes[plugin_id] = candidate
        self._sync_manifests()
        return {"id": plugin_id, "version": candidate.version, "hot_applied": True, "restart_required": False}

    def stop(self, plugin_id):
        item = self.processes.pop(plugin_id, None)
        if item:
            self._terminate(item)
        self._sync_manifests()

    def stop_all(self):
        for plugin_id in list(self.processes):
            self.stop(plugin_id)

    def status(self, plugin_id):
        item = self.processes.get(plugin_id)
        return {"running": bool(item and item.process.poll() is None), "version": item.version if item else None}

    async def proxy(self, plugin_id, path, request: Request):
        item = self.processes.get(plugin_id)
        if not item or item.process.poll() is not None:
            raise HTTPException(503, "plugin worker unavailable")
        transport = httpx.AsyncHTTPTransport(uds=str(item.socket))
        headers = {key: value for key, value in request.headers.items() if key.lower() not in {"host", "content-length", "connection"}}
        async with httpx.AsyncClient(transport=transport, base_url="http://plugin", timeout=60) as client:
            response = await client.request(request.method, f"/api/plugins/{plugin_id}/{path}", params=request.query_params, content=await request.body(), headers=headers)
        output_headers = {key: value for key, value in response.headers.items() if key.lower() not in {"content-length", "connection", "transfer-encoding"}}
        return Response(response.content, status_code=response.status_code, headers=output_headers, media_type=response.headers.get("content-type"))
