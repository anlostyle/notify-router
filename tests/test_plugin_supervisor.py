import json

import httpx
import pytest

from notifyhub.plugin_supervisor import PluginSupervisor, _friendly_worker_log
from notifyhub.store import Store


def write_plugin(directory, version, body=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"id": "demo", "name": "Demo", "version": version}),
        encoding="utf-8",
    )
    (directory / "__init__.py").write_text(
        body
        or (
            "from fastapi import APIRouter\n"
            "demo_router = APIRouter(prefix='/demo')\n"
            "@demo_router.get('/version')\n"
            f"def version(): return {{'version': '{version}'}}\n"
        ),
        encoding="utf-8",
    )


def test_worker_migrates_legacy_state_without_preserve_manifest(tmp_path):
    from notifyhub.plugin_worker import create_worker

    store = Store(tmp_path)
    directory = store.plugins_dir / "demo"
    write_plugin(directory, "1.0.0")
    (directory / "state.json").write_text('{"cursor":42}')
    create_worker(directory, tmp_path)
    migrated = tmp_path / "plugin-data" / "demo" / "state.json"
    assert json.loads(migrated.read_text()) == {"cursor": 42}


def worker_version(item):
    transport = httpx.HTTPTransport(uds=str(item.socket))
    with httpx.Client(transport=transport, base_url="http://plugin") as client:
        return client.get("/api/plugins/demo/version").json()["version"]


def test_friendly_worker_log_translates_uvicorn_lifecycle_lines():
    assert _friendly_worker_log("INFO:     Started server process [123]") == "Worker 进程已启动（PID 123）"
    assert _friendly_worker_log("INFO:     Application startup complete.") == "插件启动完成"
    assert _friendly_worker_log("INFO:     Uvicorn running on unix socket /tmp/demo.sock (Press CTRL+C to quit)") == "Worker 正在监听 Unix Socket：/tmp/demo.sock"


def test_hot_reload_switches_only_plugin_worker_and_keeps_old_on_failure(tmp_path):
    store = Store(tmp_path)
    directory = store.plugins_dir / "demo"
    write_plugin(directory, "1.0.0")
    supervisor = PluginSupervisor(store)
    try:
        first = supervisor.reload("demo")
        first_process = supervisor.processes["demo"].process
        assert first == {"id": "demo", "version": "1.0.0", "hot_applied": True, "restart_required": False}
        assert worker_version(supervisor.processes["demo"]) == "1.0.0"

        write_plugin(directory, "1.1.0")
        supervisor.reload("demo")
        second = supervisor.processes["demo"]
        assert second.process.pid != first_process.pid
        assert worker_version(second) == "1.1.0"

        write_plugin(directory, "1.2.0", "this is not valid python !!!\n")
        with pytest.raises(RuntimeError, match="exited during startup"):
            supervisor.reload("demo")
        assert second.process.poll() is None
        assert worker_version(second) == "1.1.0"
    finally:
        supervisor.stop_all()
