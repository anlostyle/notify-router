import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from notifyhub.modules.monitor.api import build_monitor_router
from notifyhub.modules.tasks.api import build_task_router
from notifyhub.controller import schedule as schedule_runtime
from notifyhub.controller.server import Server
from notifyhub.store import Store


def test_monitor_state_and_events_are_normalized(tmp_path):
    store = Store(tmp_path)
    store.update_monitor("demo", "demo:service", "Demo service", "service", "healthy", "ready")
    store.update_monitor("demo", "demo:service", "Demo service", "service", "error", "unreachable")
    monitors = store.list_monitors()
    assert monitors[0]["status"] == "error"
    events = store.list_events("monitor")
    assert [item["status"] for item in events] == ["open", "resolved"]


def test_task_registration_and_run_history(tmp_path):
    store = Store(tmp_path)
    store.register_task("demo:sync", "demo", "Sync", "scheduled", "*/5 * * * *")
    started = time.time()
    run_id = store.start_task_run("demo:sync")
    store.finish_task_run("demo:sync", run_id, started)
    assert store.list_tasks()[0]["last_status"] == "success"
    assert store.list_task_runs()[0]["status"] == "success"


def test_task_errors_are_redacted(tmp_path):
    store = Store(tmp_path)
    store.register_task("demo:sync", "demo", "Sync", "scheduled", "* * * * *")
    run_id = store.start_task_run("demo:sync")
    store.finish_task_run("demo:sync", run_id, time.time(), "token=should-not-leak")
    assert "should-not-leak" not in store.list_task_runs()[0]["error"]


def test_domain_admin_apis_return_summaries_without_monitor_metadata(tmp_path):
    store = Store(tmp_path)
    store.update_monitor("demo", "demo:one", "Demo", "service", "healthy", "ready", {"token": "secret"})
    store.register_task("demo:sync", "demo", "Sync", "scheduled", "0 * * * *")
    app = FastAPI()
    app.include_router(build_monitor_router(store, lambda: None))
    app.include_router(build_task_router(store, lambda: None))
    client = TestClient(app)
    monitors = client.get("/api/admin/monitors").json()
    tasks = client.get("/api/admin/tasks").json()
    assert monitors["summary"] == {"total": 1, "healthy": 1, "attention": 0}
    assert "metadata" not in monitors["items"][0]
    assert tasks["summary"]["total"] == 1


def test_plugin_cron_registration_appears_in_task_center(tmp_path, monkeypatch):
    store = Store(tmp_path)
    Server.configure(store)
    monkeypatch.setenv("PLUGIN_ID", "demo")
    job = schedule_runtime.register_cron_job("*/5 * * * *", "Demo sync", lambda: None)
    try:
        task = store.list_tasks()[0]
        assert task["task_id"] == "demo:<lambda>"
        assert task["schedule"] == "*/5 * * * *"
    finally:
        schedule_runtime._scheduler.remove_job(job.id)


def test_prune_plugin_tasks_removes_stale_registrations(tmp_path):
    store = Store(tmp_path)
    store.register_task("nsrss:old", "nsrss", "Old", "scheduled", "0 * * * *")
    store.register_task("nsrss:current", "nsrss", "Current", "scheduled", "*/5 * * * *")
    store.prune_plugin_tasks("nsrss", ["nsrss:current"])
    assert [item["task_id"] for item in store.list_tasks()] == ["nsrss:current"]


def test_startup_repairs_legacy_pve_and_watchtower_monitor_labels(tmp_path):
    store = Store(tmp_path)
    store.update_monitor("pve", "pve:one", "PVE", "backup", "error", "最近备份状态：pruning datastore successful")
    store.update_monitor("watchtower", "watchtower:one", "Server A", "container", "healthy", "已接收容器更新检查结果")
    repaired = Store(tmp_path)
    rows = {item["provider"]: item for item in repaired.list_monitors()}
    assert rows["pve"]["status"] == "healthy"
    assert rows["watchtower"]["name"] == "Watchtower · Server A"
