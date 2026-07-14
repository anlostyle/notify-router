import datetime
import threading
import httpx
import logging
import re

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from cacheout import Cache
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response
from xml.etree.ElementTree import fromstring
from tenacity import wait_random_exponential, stop_after_attempt, retry

from notifyhub.plugins.components.qywx_Crypt.WXBizMsgCrypt import WXBizMsgCrypt
from notifyhub.common.response import json_500

from .utils import config
from .api.media302_api import media302

logger = logging.getLogger(__name__)

token_cache = Cache(maxsize=1)

# FastAPI路由器
wx_media302_router = APIRouter(prefix="/wx-media302-save", tags=["wx-media302-save"])

APP_USER_AGENT = "wx-media302-save/0.0.1"
XML_TEMPLATES = {
    "reply": """<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{create_time}</CreateTime>
<MsgType><![CDATA[{msg_type}]]></MsgType>
<Content><![CDATA[{content}]]></Content>
<MsgId>{msg_id}</MsgId>
<AgentID>{agent_id}</AgentID>
</xml>"""
}


@dataclass
class QywxMessage:
    """企业微信消息数据类"""
    content: str
    from_user: str
    to_user: str
    create_time: str
    msg_type: str
    msg_id: str


class QywxMessageSender:
    """企业微信消息发送器"""
    
    def __init__(self):
        self.base_url = config.qywx_base_url
        self.corpid = config.sCorpID
        self.corpsecret = config.sCorpsecret
        self.agentid = config.sAgentid
    
    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=10, max=30), reraise=True)
    def get_access_token(self) -> Optional[str]:
        """
        获取企业微信访问令牌
        
        Returns:
            Optional[str]: 访问令牌，获取失败返回None
        """
        # 检查缓存中的token是否有效
        cached_token = token_cache.get('access_token')
        expires_time = token_cache.get('expires_time')
        
        if (expires_time is not None and 
            expires_time >= datetime.datetime.now() and 
            cached_token):
            return cached_token
        
        if not all([self.corpid, self.corpsecret]):
            logger.error("配置错误")
            return None
        
        # 重新获取token
        try:
            response = httpx.get(
                f"{self.base_url.strip('/')}/cgi-bin/gettoken",
                params={
                    'corpid': self.corpid,
                    'corpsecret': self.corpsecret
                },
                headers={'user-agent': APP_USER_AGENT},
                timeout=180
            )
            
            result = response.json()
            if result.get('errcode') == 0:
                access_token = result['access_token']
                expires_in = result['expires_in']
                
                # 计算过期时间（提前500秒刷新）
                expires_time = datetime.datetime.now() + datetime.timedelta(
                    seconds=expires_in - 500
                )
                
                # 缓存token和过期时间
                token_cache.set('access_token', access_token, ttl=expires_in - 500)
                token_cache.set('expires_time', expires_time, ttl=expires_in - 500)
                
                return access_token
            else:
                logger.error(f"获取企业微信accessToken失败: {result}")
                return None
                
        except Exception as e:
            logger.error(f"获取企业微信accessToken异常: {e}", exc_info=True)
            return None
    
    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=10, max=30), reraise=True)
    def _send_message(self, access_token: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送消息到企业微信
        
        Args:
            access_token: 访问令牌
            message_data: 消息数据
            
        Returns:
            Dict[str, Any]: 发送结果
        """
        try:
            url = f"{self.base_url.strip('/')}/cgi-bin/message/send"
            params = {'access_token': access_token}
            
            response = httpx.post(
                url,
                params=params,
                json=message_data,
                headers={'user-agent': APP_USER_AGENT},
                timeout=180
            )
            
            return response.json()
            
        except Exception as e:
            logger.error(f"发送企业微信消息异常: {e}", exc_info=True)
            return {'errcode': -1, 'errmsg': str(e)}
    
    def send_text_message(self, text: str, to_user: str) -> bool:
        """
        发送文本消息
        
        Args:
            text: 消息内容
            to_user: 接收用户ID
            
        Returns:
            bool: 发送是否成功
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("获取企业微信accessToken失败")
            return False
        
        message_data = {
            'touser': to_user,
            'agentid': self.agentid,
            'msgtype': 'text',
            'text': {'content': text}
        }
        
        result = self._send_message(access_token, message_data)
        
        if result.get('errcode') == 0:
            return True
        else:
            logger.error(f"发送企业微信消息失败: {result}")
            return False
    
    def send_news_message(self, title: str, description: str, url: str, pic_url: str, to_user: str) -> bool:
        """
        发送图文消息
        
        Args:
            title: 消息标题
            description: 消息描述
            url: 点击跳转链接
            pic_url: 图片链接
            to_user: 接收用户ID
            
        Returns:
            bool: 发送是否成功
        """
        access_token = self.get_access_token()
        if not access_token:
            logger.error("获取企业微信accessToken失败")
            return False
        
        message_data = {
            'touser': to_user,
            'agentid': self.agentid,
            'msgtype': 'news',
            'news': {
                'articles': [
                    {
                        'title': title,
                        'description': description,
                        'url': url,
                        'picurl': pic_url
                    }
                ]
            }
        }
        
        result = self._send_message(access_token, message_data)
        
        if result.get('errcode') == 0:
            return True
        else:
            logger.error(f"发送企业微信图文消息失败: {result}")
            return False


class QywxMessageProcessor:
    """企业微信消息处理器"""
    
    def __init__(self):
        self._crypto = None
    
    def _get_crypto(self) -> WXBizMsgCrypt:
        """
        获取加密组件实例（按需创建）
        
        Returns:
            WXBizMsgCrypt: 加密组件实例
            
        Raises:
            ValueError: 当配置参数缺失时抛出异常
        """
        if self._crypto is None:
            # 验证配置参数
            if not all([config.sToken, config.sEncodingAESKey, config.sCorpID]):
                raise ValueError("配置错误")
            
            self._crypto = WXBizMsgCrypt(
                config.sToken,
                config.sEncodingAESKey,
                config.sCorpID
            )
        return self._crypto
    
    def _parse_xml_message(self, xml_data: str) -> QywxMessage:
        """
        解析XML消息
        
        Args:
            xml_data: XML格式的消息数据
            
        Returns:
            QywxMessage: 解析后的消息对象
        """
        try:
            root = fromstring(xml_data)
            message_data = {node.tag: node.text for node in root}
            
            return QywxMessage(
                content=message_data.get('Content', ''),
                from_user=message_data.get('FromUserName', ''),
                to_user=message_data.get('ToUserName', ''),
                create_time=message_data.get('CreateTime', ''),
                msg_type=message_data.get('MsgType', ''),
                msg_id=message_data.get('MsgId', '')
            )
        except Exception as e:
            logger.error(f"解析XML消息失败: {e}")
            raise ValueError("消息格式错误")
    
    def _create_reply_xml(self, message: QywxMessage, content: str) -> str:
        """
        创建回复XML
        
        Args:
            message: 原始消息
            content: 回复内容
            
        Returns:
            str: XML格式的回复
        """
        return XML_TEMPLATES["reply"].format(
            to_user=message.to_user,
            from_user=message.from_user,
            create_time=message.create_time,
            msg_type=message.msg_type,
            content=content,
            msg_id=message.msg_id,
            agent_id=config.sAgentid
        )
    
    def process_message(self, encrypted_msg: str, msg_signature: str, 
                       timestamp: str, nonce: str) -> str:
        """
        处理企业微信消息
        
        Args:
            encrypted_msg: 加密的消息
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            
        Returns:
            str: 加密的回复消息
        """
        try:
            # 解密消息
            crypto = self._get_crypto()
            ret, decrypted_msg = crypto.DecryptMsg(
                encrypted_msg, msg_signature, timestamp, nonce
            )
            
            if ret != 0:
                logger.error(f"消息解密失败: {decrypted_msg}")
                raise ValueError("消息解密失败")
            
            # 解析消息
            message = self._parse_xml_message(decrypted_msg.decode('utf-8'))
            content = (message.content or "").strip()
            
            # 启动异步处理线程
            self._process_chat_message_async(message)
            
            # 创建回复XML
            reply_xml = self._create_reply_xml(message, "正在处理您的请求，请稍候...")
            
            # 加密回复
            ret, encrypted_reply = crypto.EncryptMsg(reply_xml, nonce, timestamp)
            
            if ret != 0:
                logger.error(f"消息加密失败: {encrypted_reply}")
                raise ValueError("消息加密失败")
            
            return encrypted_reply
            
        except Exception as e:
            logger.error(f"处理企业微信消息失败: {e}")
            raise
    
    def _process_chat_message_async(self, message: QywxMessage):
        """
        异步处理聊天消息
        
        Args:
            message: 消息对象
        """
        thread = QywxChatThread(message)
        thread.start()


class QywxChatThread(threading.Thread):
    """企业微信聊天处理线程"""
    
    def __init__(self, message: QywxMessage):
        super().__init__()
        self.name = "QywxChatThread"
        self.message = message
        self.message_sender = QywxMessageSender()
    
    def run(self):
        """线程执行方法"""
        try:
            # 提取115分享链接
            content = (self.message.content or "").strip()
            
            # 检查是否包含115分享链接
            # 匹配模式: https://115.com/s/xxxx 或 https://115cdn.com/s/xxxx
            pattern = r'(https://(?:115\.com|115cdn\.com)/s/[^#\s]+)' 
            match = re.search(pattern, content)
            
            if not match:
                # 发送帮助信息
                help_text = "请输入115网盘分享链接，格式如：https://115cdn.com/s/swwao7136gr?password=1234#"
                self.message_sender.send_text_message(help_text, self.message.from_user)
                return
            
            # 提取匹配的链接
            share_url = match.group(1)
            
            # 调用media302 API进行转存
            result = media302.save_share(share_url)
            
            # 处理转存结果
            if result.get('msg') in ('success', '文件已接收，无需重复接收！'):
                response_text = f"✅ 转存成功！\n状态：{result.get('msg')}\n链接：{share_url}"
                # 发送图文消息
                title = "✅ 转存成功！"
                description = f"状态：{result.get('msg')}\n链接：{share_url}"
                pic_url = "https://s1.locimg.com/2025/01/03/13a09e2f7cb3a.png"
                self.message_sender.send_news_message(title, description, share_url, pic_url, self.message.from_user)
            elif result.get('success') is False:
                error_msg = result.get('message', '未知错误')
                response_text = f"❌ 转存失败：{error_msg}\n链接：{share_url}"
                # 发送文本消息
                self.message_sender.send_text_message(response_text, self.message.from_user)
            else:
                # 优化显示格式，特别是包含文件列表的情况
                if result.get('code') == 0 and 'msg' in result and '\n' in str(result['msg']):
                    # 提取文件列表并格式化显示
                    files = str(result['msg']).split('\n')
                    file_list_text = '\n'.join([f"- {file}" for file in files])
                    response_text = f"✅ 转存成功！\n共 {len(files)} 个文件\n{file_list_text}\n链接：{share_url}"
                    # 发送图文消息 - 优化文件列表显示以适应字数限制
                    title = f"✅ 转存成功！共 {len(files)} 个文件"
                    
                    # 进一步优化显示，同时限制文件名长度和总显示数量
                    max_display_files = 5  # 最大显示文件数恢复为10个
                    max_file_name_length = 30  # 限制每个文件名的长度
                    display_files = files[:max_display_files]
                    
                    # 格式化文件列表，从路径中提取纯文件名、目录路径并对长文件名进行截断处理
                    formatted_files = []
                    
                    # 提取转存文件路径
                    storage_path = ""
                    if display_files:
                        first_file = display_files[0].replace('\\', '/')
                        if '/' in first_file:
                            # 提取目录部分（去掉文件名）
                            path_parts = first_file.split('/')
                            if len(path_parts) > 1:
                                storage_path = '/'.join(path_parts[:-1])
                        
                    for file in display_files:
                        # 从路径中提取纯文件名（最后一部分）
                        # 先将所有路径分隔符统一为'/'，然后取最后一部分
                        file_path = file.replace('\\', '/')
                        file_name = file_path.split('/')[-1]
                        
                        # 对长文件名进行截断处理
                        if len(file_name) > max_file_name_length:
                            truncated_file = file_name[:max_file_name_length] + '...'
                            formatted_files.append(f"📄 {truncated_file}")
                        else:
                            formatted_files.append(f"📄 {file_name}")
                    
                    file_list_text = '\n'.join(formatted_files)
                    
                    # 添加剩余文件数量提示
                    if len(files) > max_display_files:
                        remaining_count = len(files) - max_display_files
                        file_list_text += f"\n📄 还有 {remaining_count} 个文件..."
                    
                    # 构建描述内容，包含文件列表、转存路径和分享链接
                    description = f"转存文件列表：\n{file_list_text}\n\n"
                    if storage_path:
                        description += f"转存文件路径：\n📁 {storage_path}\n\n"
                    description += f"分享链接：{share_url}"
                    
                    pic_url = "https://s1.locimg.com/2025/01/03/13a09e2f7cb3a.png"
                    self.message_sender.send_news_message(title, description, share_url, pic_url, self.message.from_user)
                else:
                    # 处理其他可能的返回格式
                    response_text = f"🔄 转存结果：{result}\n链接：{share_url}"
                    # 发送文本消息
                    self.message_sender.send_text_message(response_text, self.message.from_user)
            
        except Exception as e:
            logger.error(f"处理请求失败: {e}", exc_info=True)
            # 发送错误提示
            error_msg = f"⚠️ 处理请求时发生错误: {str(e)}"
            self.message_sender.send_text_message(error_msg, self.message.from_user)


class QywxCallbackHandler:
    """企业微信回调处理器"""
    
    def __init__(self):
        self._crypto = None
        self.message_processor = QywxMessageProcessor()
    
    def _get_crypto(self) -> WXBizMsgCrypt:
        """
        获取加密组件实例（按需创建）
        
        Returns:
            WXBizMsgCrypt: 加密组件实例
            
        Raises:
            ValueError: 当配置参数缺失时抛出异常
        """
        if self._crypto is None:
            # 验证配置参数
            if not all([config.sToken, config.sEncodingAESKey, config.sCorpID]):
                raise ValueError("配置错误")
            
            self._crypto = WXBizMsgCrypt(
                config.sToken,
                config.sEncodingAESKey,
                config.sCorpID
            )
        return self._crypto
    
    def verify_url(self, msg_signature: str, timestamp: str, 
                   nonce: str, echostr: str) -> str:
        """
        验证回调URL
        
        Args:
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            echostr: 验证字符串
            
        Returns:
            str: 验证结果
        """
        try:
            crypto = self._get_crypto()
            ret, echo_str = crypto.VerifyURL(
                msg_signature, timestamp, nonce, echostr
            )
            
            if ret == 0:
                logger.info(f"企业微信URL验证成功: {echo_str.decode('utf-8')}")
                return echo_str.decode('utf-8')
            else:
                logger.error(f"企业微信URL验证失败: {echo_str}")
                raise ValueError("企业微信URL验证失败")
                
        except Exception as e:
            logger.error(f"企业微信URL验证异常: {e}")
            raise
    
    def handle_message(self, encrypted_msg: str, msg_signature: str,
                      timestamp: str, nonce: str) -> str:
        """
        处理接收到的消息
        
        Args:
            encrypted_msg: 加密的消息
            msg_signature: 消息签名
            timestamp: 时间戳
            nonce: 随机数
            
        Returns:
            str: 加密的回复消息
        """
        return self.message_processor.process_message(
            encrypted_msg, msg_signature, timestamp, nonce
        )


# 全局处理器实例
callback_handler = QywxCallbackHandler()


@wx_media302_router.get("/chat")
async def verify_callback(request: Request):
    """
    企业微信回调URL验证接口
    
    Args:
        request: FastAPI请求对象
        
    Returns:
        Response: 验证结果
    """
    try:
        # 获取验证参数
        msg_signature = request.query_params.get('msg_signature')
        timestamp = request.query_params.get('timestamp')
        nonce = request.query_params.get('nonce')
        echostr = request.query_params.get('echostr')
        
        # 验证必要参数
        if not all([msg_signature, timestamp, nonce, echostr]):
            logger.error("缺少必要的验证参数")
            raise HTTPException(status_code=400, detail="缺少必要的验证参数")
        
        # 执行验证
        try:
            result = callback_handler.verify_url(msg_signature, timestamp, nonce, echostr)
            return int(result)
        except ValueError as e:
            logger.error(f"配置错误: {e}")
            raise HTTPException(status_code=500, detail="配置错误")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"企业微信回调验证失败: {e}")
        return json_500("服务器内部错误")


@wx_media302_router.post("/chat")
async def receive_message(request: Request):
    """
    企业微信消息接收接口
    
    Args:
        request: FastAPI请求对象
        
    Returns:
        Response: 加密的回复消息
    """
    try:
        # 获取消息参数
        msg_signature = request.query_params.get('msg_signature')
        timestamp = request.query_params.get('timestamp')
        nonce = request.query_params.get('nonce')
        
        # 验证必要参数
        if not all([msg_signature, timestamp, nonce]):
            logger.error("缺少必要的验证参数")
            raise HTTPException(status_code=400, detail="缺少必要的验证参数")
        
        # 获取请求体
        body = await request.body()
        encrypted_msg = body.decode('utf-8')
        
        # 处理消息
        try:
            result = callback_handler.handle_message(
                encrypted_msg, msg_signature, timestamp, nonce
            )
            return Response(content=result, media_type="text/plain")
        except ValueError as e:
            logger.error(f"配置错误: {e}")
            raise HTTPException(status_code=500, detail="配置错误")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"企业微信消息处理失败: {e}", exc_info=True)
        return json_500("服务器内部错误")