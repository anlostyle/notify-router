"""
Telegram 双向私聊机器人核心逻辑
"""
import re
import logging
import asyncio
from typing import Optional, Dict, Any
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

from .config import config

logger = logging.getLogger(__name__)

PLUGIN_ID = "TGForwardBot"


class TGBot:
    """Telegram 双向私聊机器人"""
    
    def __init__(self):
        self.application: Optional[Application] = None
        self.bot: Optional[Bot] = None
        self._running = False
    
    async def initialize(self) -> bool:
        """初始化机器人"""
        try:
            if not config.is_valid():
                logger.error(f"[{PLUGIN_ID}] 配置无效，无法启动机器人")
                return False
            
            bot_token = config.bot_token
            proxy_url = config.proxy
            
            builder = Application.builder().token(bot_token)
            if proxy_url:
                request = HTTPXRequest(proxy=proxy_url)
                builder = builder.request(request)
            
            self.application = builder.build()
            self.bot = self.application.bot
            self._register_handlers()
            return True
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 机器人初始化失败: {e}", exc_info=True)
            return False
    
    def _register_handlers(self):
        """注册消息和命令处理器"""
        self.application.add_handler(CommandHandler("start", self._handle_start))
        self.application.add_handler(CommandHandler("help", self._handle_help))
        self.application.add_handler(CommandHandler("status", self._handle_status))
        self.application.add_handler(CommandHandler("block_list", self._handle_block_list))
        
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        
        media_filter = (
            filters.PHOTO 
            | filters.Document.ALL 
            | filters.VIDEO 
            | filters.AUDIO 
            | filters.VOICE
        )
        self.application.add_handler(
            MessageHandler(media_filter, self._handle_media)
        )
        
        self.application.add_handler(
            CallbackQueryHandler(self._handle_callback_query)
        )
    
    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /start 命令"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            
            welcome_msg = (
                f"欢迎使用 Telegram 双向私聊机器人！\n\n"
                f"你的用户ID: {chat_id}\n"
                f"用户名: @{user.username if user.username else '未设置'}\n\n"
                f"直接发送消息即可与管理员通信"
            )
            
            reply_markup = None
            if self._is_manager(chat_id):
                keyboard = [
                    [InlineKeyboardButton(
                        text="📖 查看帮助",
                        callback_data="show_help"
                    )]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
            
            if not self._is_manager(chat_id):
                await self._notify_manager(f"新用户启动机器人:\n用户ID: {chat_id}\n用户名: {user.username or '未设置'}")
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理 /start 命令失败: {e}", exc_info=True)
    
    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /help 命令（仅管理员）"""
        try:
            chat_id = update.effective_chat.id
            if not self._is_manager(chat_id):
                return
            
            help_msg = (
                "可用命令：\n"
                "/start - 启动机器人\n"
                "/help - 显示帮助信息\n"
                "/status - 查看机器人状态\n"
                "/block_list - 查看封禁用户列表\n\n"
                "直接发送消息即可与管理员通信"
            )
            await update.message.reply_text(help_msg)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理 /help 命令失败: {e}", exc_info=True)
    
    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /status 命令（仅管理员）"""
        try:
            chat_id = update.effective_chat.id
            if not self._is_manager(chat_id):
                return
            
            status_msg = (
                f"机器人状态：运行中 ✓\n"
                f"你的用户ID: {update.effective_chat.id}\n"
                f"管理员ID: {config.manager_chatid}"
            )
            await update.message.reply_text(status_msg)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理 /status 命令失败: {e}", exc_info=True)
    
    async def _handle_block_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理 /block_list 命令（仅管理员）"""
        try:
            chat_id = update.effective_chat.id
            if not self._is_manager(chat_id):
                return
            
            await self._show_block_list(update.message, page=0)
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理 /block_list 命令失败: {e}", exc_info=True)
    
    async def _show_block_list(self, message: Message, page: int = 0, user_id: Optional[int] = None):
        """
        显示封禁用户列表或用户详情
        
        Args:
            message: 消息对象（用于编辑或发送）
            page: 页码（从0开始）
            user_id: 如果提供，显示该用户的详情
        """
        try:
            blocklist = config.get_blocklist()
            
            if user_id is not None:
                # 显示用户详情
                user_info = None
                for item in blocklist:
                    if item["user_id"] == user_id:
                        user_info = item
                        break
                
                if not user_info:
                    await message.reply_text("用户不存在于封禁列表中")
                    return
                
                detail_msg = (
                    f"封禁用户详情\n\n"
                    f"用户ID: {user_info['user_id']}\n"
                    f"姓名: {user_info['name'] if user_info['name'] else '未设置'}\n\n"
                    f"点击「✅ 确认解除封禁」按钮即可解除封禁"
                )
                
                keyboard = [
                    [
                        InlineKeyboardButton(
                            text="⬅️ 返回列表",
                            callback_data=f"block_list:page:{page}"
                        ),
                        InlineKeyboardButton(
                            text="✅ 确认解除封禁",
                            callback_data=f"unblock_user:{user_id}:page:{page}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text="❌ 关闭",
                            callback_data="close_block_list"
                        )
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await message.edit_text(detail_msg, reply_markup=reply_markup)
                except Exception:
                    await message.reply_text(detail_msg, reply_markup=reply_markup)
                return
            
            # 显示封禁用户列表
            if not blocklist:
                help_msg = (
                    "📋 封禁用户管理\n\n"
                    "当前没有封禁用户\n\n"
                    "操作方法：\n"
                    "• 在用户消息中点击「🚫 封禁用户」按钮可封禁用户\n"
                    "• 使用 /block_list 查看所有封禁用户"
                )
                await message.reply_text(help_msg)
                return
            
            # 分页设置
            items_per_page = 8
            total_pages = (len(blocklist) + items_per_page - 1) // items_per_page
            
            if page < 0:
                page = 0
            if page >= total_pages:
                page = total_pages - 1
            
            start_idx = page * items_per_page
            end_idx = min(start_idx + items_per_page, len(blocklist))
            page_items = blocklist[start_idx:end_idx]
            
            help_msg = (
                "📋 封禁用户管理\n\n"
                f"共 {len(blocklist)} 个封禁用户（第 {page + 1}/{total_pages} 页）\n\n"
                "操作方法：\n"
                "• 点击下方用户按钮查看详情\n"
                "• 在详情页面可以解除封禁\n"
                "• 在用户消息中点击「🚫 封禁用户」按钮可封禁用户"
            )
            
            keyboard = []
            for item in page_items:
                user_name = item["name"] if item["name"] else f"用户 {item['user_id']}"
                keyboard.append([
                    InlineKeyboardButton(
                        text=user_name,
                        callback_data=f"block_list:user:{item['user_id']}:page:{page}"
                    )
                ])
            
            # 添加分页按钮（仅在有多页时显示）
            if total_pages > 1:
                nav_buttons = []
                if page > 0:
                    nav_buttons.append(
                        InlineKeyboardButton(
                            text="⬅️ 上一页",
                            callback_data=f"block_list:page:{page - 1}"
                        )
                    )
                if page < total_pages - 1:
                    nav_buttons.append(
                        InlineKeyboardButton(
                            text="下一页 ➡️",
                            callback_data=f"block_list:page:{page + 1}"
                        )
                    )
                if nav_buttons:
                    keyboard.append(nav_buttons)
            
            # 添加关闭按钮
            keyboard.append([
                InlineKeyboardButton(
                    text="❌ 关闭",
                    callback_data="close_block_list"
                )
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await message.edit_text(help_msg, reply_markup=reply_markup)
            except Exception:
                await message.reply_text(help_msg, reply_markup=reply_markup)
                
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 显示封禁列表失败: {e}", exc_info=True)
    
    def _is_manager(self, chat_id: int) -> bool:
        """
        检查是否是管理员
        
        Args:
            chat_id: 聊天ID
            
        Returns:
            bool: 是否是管理员
        """
        try:
            manager_chatid = config.manager_chatid
            if not manager_chatid:
                return False
            return str(chat_id) == str(manager_chatid)
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 检查管理员身份失败: {e}", exc_info=True)
            return False
    
    def _contains_block_keywords(self, text: str) -> bool:
        """
        检查文本是否包含封禁关键词
        
        Args:
            text: 要检查的文本
            
        Returns:
            bool: 如果包含关键词返回True，否则返回False
        """
        try:
            if not text:
                return False
            
            block_keywords = config.block_keywords
            if not block_keywords:
                return False
            
            text_lower = text.lower()
            for keyword in block_keywords:
                if keyword.lower() in text_lower:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 检查关键词失败: {e}", exc_info=True)
            return False
    
    def _delete_message_after_delay(self, message: Message, delay: int = 10):
        """
        在指定延迟后删除消息
        
        Args:
            message: 要删除的消息对象
            delay: 延迟时间（秒），默认10秒
        """
        async def delete_after_delay():
            try:
                await asyncio.sleep(delay)
                await message.delete()
            except Exception as e:
                logger.error(f"[{PLUGIN_ID}] 自动删除消息失败: {e}", exc_info=True)
        
        asyncio.create_task(delete_after_delay())
    
    def _extract_user_id_from_message(self, message_text: str) -> Optional[int]:
        """
        从消息文本中提取用户ID
        消息格式：...用户ID: 123456789...
        
        Args:
            message_text: 消息文本
            
        Returns:
            Optional[int]: 提取到的用户ID，如果未找到返回None
        """
        try:
            pattern = r'用户ID:\s*(\d+)'
            match = re.search(pattern, message_text)
            if match:
                return int(match.group(1))
            return None
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 提取用户ID失败: {e}", exc_info=True)
            return None
    
    def _extract_user_name_from_message(self, message_text: str) -> Optional[str]:
        """
        从消息文本中提取用户名
        消息格式：...姓名: 张三... 或 ...用户名: @zhangsan...
        
        Args:
            message_text: 消息文本
            
        Returns:
            Optional[str]: 提取到的用户名，如果未找到返回None
        """
        try:
            name_pattern = r'姓名:\s*([^\n]+)'
            name_match = re.search(name_pattern, message_text)
            if name_match:
                name = name_match.group(1).strip()
                if name:
                    return name
            
            username_pattern = r'用户名:\s*@?([^\n]+)'
            username_match = re.search(username_pattern, message_text)
            if username_match:
                username = username_match.group(1).strip()
                if username:
                    return f"@{username}"
            
            return None
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 提取用户名失败: {e}", exc_info=True)
            return None
    
    async def _handle_manager_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        处理管理员的回复消息
        
        Args:
            update: Telegram更新对象
            context: 上下文对象
        """
        try:
            message = update.message
            reply_to_message = message.reply_to_message
            
            if not reply_to_message:
                await message.reply_text(
                    "⚠️ 请回复对应的用户消息进行回复。\n\n"
                    "使用方法：\n"
                    "1. 找到要回复的用户消息\n"
                    "2. 点击“回复”按钮\n"
                    "3. 输入回复内容并发送"
                )
                return
            
            replied_text = reply_to_message.text or reply_to_message.caption or ""
            
            if not replied_text:
                await message.reply_text(
                    "❌ 无法识别要回复的用户。\n\n"
                    "请确保回复的是机器人转发的用户消息（包含用户信息）。"
                )
                return
            
            target_user_id = self._extract_user_id_from_message(replied_text)
            target_user_name = self._extract_user_name_from_message(replied_text)
            
            if not target_user_id:
                await message.reply_text(
                    "❌ 无法识别要回复的用户。\n\n"
                    "请确保回复的是机器人转发的用户消息（包含用户ID信息）。"
                )
                return
            
            reply_text = message.text or message.caption or ""
            success = False
            
            if message.photo or message.document or message.video or message.audio or message.voice:
                success = await self._forward_media_to_user(
                    message, 
                    target_user_id,
                    caption=reply_text if reply_text else None
                )
            elif reply_text:
                success = await self.send_message(target_user_id, reply_text)
            else:
                await message.reply_text(
                    "⚠️ 回复消息需要包含文字内容或媒体文件。\n\n"
                    "请发送文字消息或媒体消息进行回复。"
                )
                return
            
            if success:
                display_name = target_user_name or f"用户 {target_user_id}"
                content_parts = []
                if message.photo or message.document or message.video or message.audio or message.voice:
                    if message.photo:
                        content_parts.append("图片")
                    elif message.document:
                        content_parts.append("文档")
                    elif message.video:
                        content_parts.append("视频")
                    elif message.audio:
                        content_parts.append("音频")
                    elif message.voice:
                        content_parts.append("语音")
                
                if reply_text:
                    content_parts.append("文字")
                
                if content_parts:
                    reply_content = "和".join(content_parts) + "回复"
                else:
                    reply_content = "回复"
                
                await message.reply_text(f"✓ {reply_content}已发送给 「{display_name}」")
            else:
                await message.reply_text(
                    f"✗ 发送失败，请检查用户ID是否正确：{target_user_id}\n"
                    "可能原因：用户已屏蔽机器人或用户ID无效"
                )
                
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理管理员回复失败: {e}", exc_info=True)
            try:
                await update.message.reply_text("处理回复时发生错误，请稍后重试。")
            except:
                pass
    
    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理内联键盘回调"""
        try:
            query = update.callback_query
            callback_data = query.data
            
            # 处理不需要管理员权限的回调
            if callback_data == "already_blocked":
                await query.answer("该用户已被封禁", show_alert=True)
                return
            
            # 其他操作需要管理员权限
            if not self._is_manager(query.from_user.id):
                await query.answer("此操作仅限管理员使用", show_alert=True)
                return
            
            await query.answer()
            
            if callback_data.startswith("block_user:"):
                user_id_str = callback_data.split(":", 1)[1]
                try:
                    user_id = int(user_id_str)
                    
                    if config.is_blocked(user_id):
                        await query.answer("该用户已被封禁", show_alert=True)
                        return
                    
                    user_name = ""
                    original_message = query.message
                    if original_message:
                        message_text = original_message.text or original_message.caption or ""
                        if message_text:
                            name_match = re.search(r'姓名:\s*([^\n]+)', message_text)
                            if name_match:
                                user_name = name_match.group(1).strip()
                            else:
                                username_match = re.search(r'用户名:\s*@?([^\n]+)', message_text)
                                if username_match:
                                    user_name = f"@{username_match.group(1).strip()}"
                    
                    success = config.add_to_blocklist(user_id, user_name)
                    
                    if success:
                        await query.answer("✓ 用户已封禁", show_alert=True)
                        
                        try:
                            original_message = query.message
                            if original_message and original_message.reply_markup:
                                keyboard = original_message.reply_markup.inline_keyboard
                                new_keyboard = []
                                for row in keyboard:
                                    new_row = []
                                    for button in row:
                                        if button.callback_data == callback_data:
                                            new_row.append(
                                                InlineKeyboardButton(
                                                    text="✅ 已封禁",
                                                    callback_data="already_blocked"
                                                )
                                            )
                                        else:
                                            new_row.append(button)
                                    new_keyboard.append(new_row)
                                
                                new_reply_markup = InlineKeyboardMarkup(new_keyboard)
                                await original_message.edit_reply_markup(reply_markup=new_reply_markup)
                        except Exception as e:
                            logger.error(f"[{PLUGIN_ID}] 更新按钮状态失败: {e}", exc_info=True)
                    else:
                        await query.answer("✗ 封禁失败，请稍后重试", show_alert=True)
                        
                except ValueError:
                    await query.answer("无效的用户ID", show_alert=True)
                except Exception as e:
                    logger.error(f"[{PLUGIN_ID}] 处理封禁回调失败: {e}", exc_info=True)
                    await query.answer("处理失败，请稍后重试", show_alert=True)
            
            elif callback_data == "show_help":
                help_msg = (
                    "可用命令：\n"
                    "/start - 启动机器人\n"
                    "/help - 显示帮助信息\n"
                    "/status - 查看机器人状态\n"
                    "/block_list - 查看封禁用户列表\n\n"
                    "直接发送消息即可与管理员通信"
                )
                await query.answer()
                await query.message.reply_text(help_msg)
            
            elif callback_data.startswith("block_list:"):
                await query.answer()
                parts = callback_data.split(":")
                if len(parts) >= 3 and parts[1] == "page":
                    page = int(parts[2])
                    await self._show_block_list(query.message, page=page)
                elif len(parts) >= 5 and parts[1] == "user":
                    user_id = int(parts[2])
                    page = int(parts[4]) if len(parts) > 4 else 0
                    await self._show_block_list(query.message, page=page, user_id=user_id)
            
            elif callback_data.startswith("unblock_user:"):
                parts = callback_data.split(":")
                if len(parts) >= 4:
                    user_id = int(parts[1])
                    page = int(parts[3])
                    
                    success = config.remove_from_blocklist(user_id)
                    if success:
                        await query.answer("✓ 用户已解除封禁", show_alert=True)
                        await self._show_block_list(query.message, page=page)
                    else:
                        await query.answer("✗ 解除封禁失败", show_alert=True)
            
            elif callback_data == "close_block_list":
                await query.answer()
                try:
                    await query.message.delete()
                except Exception as e:
                    logger.error(f"[{PLUGIN_ID}] 删除消息失败: {e}", exc_info=True)
                    await query.answer("删除消息失败", show_alert=True)
                
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理回调查询失败: {e}", exc_info=True)
            try:
                await query.answer("处理失败，请稍后重试", show_alert=True)
            except:
                pass
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message_text = update.message.text
            
            if self._is_manager(chat_id):
                await self._handle_manager_reply(update, context)
                return
            
            if config.is_blocked(chat_id):
                return
            
            # 检查是否包含封禁关键词
            if self._contains_block_keywords(message_text):
                return
            
            user_info = "\n\n" + "="*25 + f"\n用户ID: {chat_id}"
            if user.first_name or user.last_name:
                full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                user_info += f"\n姓名: {full_name}"
            if user.username:
                user_info += f"\n用户名: @{user.username}"
            
            if user.first_name:
                user_name = user.first_name
                if user.last_name:
                    user_name += f" {user.last_name}"
            elif user.username:
                user_name = f"@{user.username}"
            else:
                user_name = f"用户 {chat_id}"
            
            keyboard = [
                [
                    InlineKeyboardButton(
                        text=user_name,
                        url=f"tg://user?id={chat_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 封禁用户",
                        callback_data=f"block_user:{chat_id}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            forward_msg = message_text + user_info
            await self._notify_manager(forward_msg, reply_markup=reply_markup)
            
            # 发送确认消息，10秒后自动删除
            confirm_msg = await update.message.reply_text("消息已收到！(10s后自动销毁)")
            self._delete_message_after_delay(confirm_msg, delay=10)
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理消息失败: {e}", exc_info=True)
            try:
                await update.message.reply_text("处理消息时发生错误，请稍后重试。")
            except:
                pass
    
    async def _handle_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理媒体消息（图片、文档等）"""
        try:
            chat_id = update.effective_chat.id
            user = update.effective_user
            message = update.message
            
            if self._is_manager(chat_id):
                if message.reply_to_message:
                    await self._handle_manager_reply(update, context)
                    return
                return
            
            if config.is_blocked(chat_id):
                return
            
            # 检查媒体消息的caption是否包含封禁关键词
            caption = message.caption or ""
            if self._contains_block_keywords(caption):
                return
            media_type = "未知类型"
            media_type_key = None
            file_id = None
            if message.photo:
                media_type = "图片"
                media_type_key = "photo"
                file_id = message.photo[-1].file_id
            elif message.document:
                media_type = "文档"
                media_type_key = "document"
                file_id = message.document.file_id
            elif message.video:
                media_type = "视频"
                media_type_key = "video"
                file_id = message.video.file_id
            elif message.audio:
                media_type = "音频"
                media_type_key = "audio"
                file_id = message.audio.file_id
            elif message.voice:
                media_type = "语音"
                media_type_key = "voice"
                file_id = message.voice.file_id
            
            user_info = "\n\n" + "="*25 + f"\n用户ID: {chat_id}"
            if user.first_name or user.last_name:
                full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
                user_info += f"\n姓名: {full_name}"
            if user.username:
                user_info += f"\n用户名: @{user.username}"
            
            if user.first_name:
                user_name = user.first_name
                if user.last_name:
                    user_name += f" {user.last_name}"
            elif user.username:
                user_name = f"@{user.username}"
            else:
                user_name = f"用户 {chat_id}"
            
            keyboard = [
                [
                    InlineKeyboardButton(
                        text=user_name,
                        url=f"tg://user?id={chat_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🚫 封禁用户",
                        callback_data=f"block_user:{chat_id}"
                    )
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            caption = f"收到来自用户的{media_type}{user_info}"
            if message.caption:
                caption = f"{message.caption}{user_info}"
            
            try:
                if file_id and media_type_key:
                    await self._forward_media_to_manager(
                        file_id, 
                        media_type_key, 
                        caption=caption,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"[{PLUGIN_ID}] 转发媒体失败: {e}", exc_info=True)
            
            confirm_msg = await update.message.reply_text(f"{media_type}已收到！(10s后自动销毁)")
            self._delete_message_after_delay(confirm_msg, delay=10)
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 处理媒体消息失败: {e}", exc_info=True)
    
    async def _notify_manager(self, message: str, reply_markup=None):
        """通知管理员"""
        try:
            manager_chatid = config.manager_chatid
            if not manager_chatid:
                return
            
            await self.bot.send_message(
                chat_id=int(manager_chatid),
                text=message,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 通知管理员失败: {e}", exc_info=True)
    
    async def _forward_media_to_manager(
        self, 
        file_id: str, 
        media_type: str, 
        caption: Optional[str] = None,
        reply_markup: Optional[InlineKeyboardMarkup] = None
    ):
        """
        转发媒体文件给管理员
        
        Args:
            file_id: 媒体文件ID
            media_type: 媒体类型（photo/document/video/audio/voice）
            caption: 可选的说明文字
            reply_markup: 可选的内联键盘
        """
        try:
            manager_chatid = config.manager_chatid
            if not manager_chatid:
                return
            
            chat_id = int(manager_chatid)
            
            if media_type == "photo":
                await self.bot.send_photo(
                    chat_id=chat_id, 
                    photo=file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
            elif media_type == "document":
                await self.bot.send_document(
                    chat_id=chat_id, 
                    document=file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
            elif media_type == "video":
                await self.bot.send_video(
                    chat_id=chat_id, 
                    video=file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
            elif media_type == "audio":
                await self.bot.send_audio(
                    chat_id=chat_id, 
                    audio=file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
            elif media_type == "voice":
                await self.bot.send_voice(
                    chat_id=chat_id, 
                    voice=file_id,
                    caption=caption,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 转发媒体给管理员失败: {e}", exc_info=True)
    
    async def _forward_media_to_user(
        self,
        message: Message,
        user_id: int,
        caption: Optional[str] = None
    ) -> bool:
        """
        转发媒体消息给用户
        
        Args:
            message: Telegram消息对象
            user_id: 目标用户ID
            caption: 可选的说明文字
            
        Returns:
            bool: 是否发送成功
        """
        try:
            if not self.bot:
                logger.error(f"[{PLUGIN_ID}] 机器人未初始化")
                return False
            
            if message.photo:
                await self.bot.send_photo(
                    chat_id=user_id,
                    photo=message.photo[-1].file_id,
                    caption=caption
                )
                return True
            elif message.document:
                await self.bot.send_document(
                    chat_id=user_id,
                    document=message.document.file_id,
                    caption=caption
                )
                return True
            elif message.video:
                await self.bot.send_video(
                    chat_id=user_id,
                    video=message.video.file_id,
                    caption=caption
                )
                return True
            elif message.audio:
                await self.bot.send_audio(
                    chat_id=user_id,
                    audio=message.audio.file_id,
                    caption=caption
                )
                return True
            elif message.voice:
                await self.bot.send_voice(
                    chat_id=user_id,
                    voice=message.voice.file_id,
                    caption=caption
                )
                return True
            else:
                return False
                
        except TelegramError as e:
            logger.error(f"[{PLUGIN_ID}] 转发媒体给用户失败: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 转发媒体给用户时发生未知错误: {e}", exc_info=True)
            return False
    
    async def start(self):
        """启动机器人"""
        if self._running:
            return
        
        if not self.application:
            if not await self.initialize():
                return
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
            self._running = True
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 机器人启动失败: {e}", exc_info=True)
            self._running = False
            raise
    
    async def stop(self):
        """停止机器人"""
        if not self._running:
            return
        
        try:
            if self.application:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            self._running = False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 停止机器人失败: {e}", exc_info=True)
    
    async def send_message(self, chat_id: int, message: str) -> bool:
        """
        发送消息到指定聊天
        
        Args:
            chat_id: 目标聊天ID
            message: 消息内容
            
        Returns:
            bool: 是否发送成功
        """
        try:
            if not self.bot:
                logger.error(f"[{PLUGIN_ID}] 机器人未初始化")
                return False
            
            await self.bot.send_message(chat_id=chat_id, text=message)
            return True
        except TelegramError as e:
            logger.error(f"[{PLUGIN_ID}] 发送消息失败: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 发送消息时发生未知错误: {e}", exc_info=True)
            return False


# 全局机器人实例
bot_instance: Optional[TGBot] = None


def get_bot() -> Optional[TGBot]:
    """获取机器人实例"""
    return bot_instance


async def init_bot() -> bool:
    """初始化机器人实例"""
    global bot_instance
    if bot_instance is None:
        bot_instance = TGBot()
    return await bot_instance.initialize()


async def start_bot():
    """启动机器人"""
    global bot_instance
    if bot_instance is None:
        bot_instance = TGBot()
    await bot_instance.start()


async def stop_bot():
    """停止机器人"""
    global bot_instance
    if bot_instance:
        await bot_instance.stop()

