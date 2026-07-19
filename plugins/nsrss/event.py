import logging

from notifyhub.controller.schedule import register_cron_job
from notifyhub.plugins.common import after_setup
from notifyhub.plugins.sdk import record_monitor

from .main import RSSMonitor
from .utils import config

logger = logging.getLogger(__name__)


def run_rss_monitor():
    try:
        result = RSSMonitor().run_once()
        record_monitor("rss", "NS/DF 论坛 RSS", "healthy", "最近一次 RSS 检查成功", "content")
        return result
    except Exception:
        record_monitor("rss", "NS/DF 论坛 RSS", "error", "最近一次 RSS 检查失败", "content")
        raise

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
            func=run_rss_monitor
        )
