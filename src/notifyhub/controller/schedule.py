import asyncio
import inspect
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from .server import server


_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _run(func, task_id):
    store = server._store
    started = time.time()
    run_id = store.start_task_run(task_id) if store else None
    try:
        result = func()
        if inspect.isawaitable(result):
            asyncio.run(result)
    except Exception as exc:
        if store and run_id:
            store.finish_task_run(task_id, run_id, started, str(exc))
        raise
    if store and run_id:
        store.finish_task_run(task_id, run_id, started)


def register_cron_job(cron_expr, desc, func, random_delay_seconds=0):
    plugin_id = os.environ.get("PLUGIN_ID") or "system"
    task_id = f"{plugin_id}:{getattr(func, '__name__', desc)}"
    if server._store:
        server._store.register_task(task_id, plugin_id, desc, "scheduled", cron_expr)
    return _scheduler.add_job(
        _run,
        CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai"),
        args=[func, task_id],
        id=task_id,
        name=desc,
        replace_existing=True,
        jitter=max(0, int(random_delay_seconds or 0)),
        coalesce=True,
        max_instances=1,
    )


def start_scheduler():
    if not _scheduler.running:
        _scheduler.start()


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def registered_task_ids():
    return [job.id for job in _scheduler.get_jobs()]
