"""
TG双向私聊机器人插件
"""
import logging
import asyncio

from notifyhub.plugins.common import after_setup

from .bot import start_bot, stop_bot, get_bot
from .config import config

logger = logging.getLogger(__name__)

PLUGIN_ID = "TGForwardBot"


@after_setup(PLUGIN_ID, "初始化TG双向私聊机器人")
async def init_tg_bot():
    """初始化Telegram机器人"""
    try:
        # 检查配置
        if not config.is_valid():
            return
        
        # 初始化机器人实例（不启动）
        logger.info(f"[{PLUGIN_ID}] 开始初始化Telegram机器人...")
        
        from .bot import init_bot
        init_success = await init_bot()
        if not init_success:
            logger.error(f"[{PLUGIN_ID}] 机器人初始化失败")
            return
        
        # 获取当前事件循环并创建后台任务启动机器人
        # 注意：start_bot() 会一直运行（start_polling会阻塞），所以需要在后台任务中执行
        # 我们立即返回，不等待机器人启动完成
        async def run_bot_background():
            try:
                logger.info(f"[{PLUGIN_ID}] 正在后台启动机器人，如果看到'Application started'则表示机器人启动成功")
                await start_bot()
            except Exception as e:
                logger.error(f"[{PLUGIN_ID}] 机器人运行出错: {e}", exc_info=True)
        
        # 创建后台任务，但不等待完成
        # 使用 asyncio.create_task 在后台运行
        try:
            loop = asyncio.get_running_loop()
            # 如果循环正在运行，创建任务但不等待
            task = loop.create_task(run_bot_background())
        except RuntimeError:
            # 如果没有运行的循环，直接运行（这种情况不应该发生，因为after_setup在事件循环中执行）
            asyncio.create_task(run_bot_background())
        
        
    except Exception as e:
        logger.error(f"[{PLUGIN_ID}] 初始化Telegram机器人失败: {e}", exc_info=True)


# 导出主要接口
__all__ = [
    "get_bot",
    "config",
    "start_bot",
    "stop_bot",
]

