from notifyhub.controller.schedule import register_cron_job
from notifyhub.plugins.common import after_setup

from .event import run_cron_job
from .config import list_reminder_configs, list_subscribe_configs


@after_setup("reminder", "reminder 插件初始化")
def start_reminder():
    # 注册 reminder 任务：每分钟执行
    if list_reminder_configs():
        register_cron_job(
            cron_expr="* * * * *",
            desc="reminder 定时提醒",
            func=run_cron_job.run_reminder
        )
    
    # 注册 subscribe 任务：每天0点执行
    if list_subscribe_configs():
        register_cron_job(
            cron_expr="0 0 * * *",
            desc="subscribe 订阅提醒",
            func=run_cron_job.run_subscribe
        )