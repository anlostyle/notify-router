import asyncio
import inspect

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


_scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _run(func):
    result = func()
    if inspect.isawaitable(result):
        asyncio.run(result)


def register_cron_job(cron_expr, desc, func, random_delay_seconds=0):
    return _scheduler.add_job(
        _run,
        CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai"),
        args=[func],
        id=f"{getattr(func, '__module__', '')}:{getattr(func, '__name__', desc)}",
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
