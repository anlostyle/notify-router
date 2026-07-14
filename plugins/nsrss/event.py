import logging

from notifyhub.controller.schedule import register_cron_job
from notifyhub.plugins.common import after_setup

from .main import RSSMonitor
from .utils import config

logger = logging.getLogger(__name__)

@after_setup("nsrss", "nsrss 插件初始化")
def after_setup_nsrss():
    if not all(config.validate_config().values()):
        logger.error("nsrss 配置不完整，跳过定时任务")
        return
    if config.rss_cron:
        logger.info(f"nsrss 检查关键字: {config.keyword.split(',')}")
        register_cron_job(
            cron_expr=config.rss_cron,
            desc="nsrss 定时任务",
            func=RSSMonitor().run_once
        )