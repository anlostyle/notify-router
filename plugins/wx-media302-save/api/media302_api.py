import httpx
import logging

from ..utils import config

logger = logging.getLogger(__name__)

class Media302Api:
    def __init__(self):
        self.base_url = config.media302_url
        self.folder = config.folder
        self.token = config.media302_token
        self.app_user_agent = "wx-media302-save/0.0.1"
        
    def save_share(self, url: str) -> dict:
        """保存115分享链接到115网盘
        
        Args:
            url: 115网盘分享链接
            
        Returns:
            dict: 转存结果
        """
        if not all([self.base_url, self.token]):
            logger.error("media302配置不完整")
            return {"success": False, "message": "插件配置不完整"}
            
        if not url.startswith(("https://115.com", "https://115cdn.com")):
            return {"success": False, "message": "无效的115分享链接"}
            
        try:
            api_url = f"{self.base_url.rstrip('/')}/strm/api/task/save-share"
            params = {"folder": self.folder, "token": self.token, "url": url}
            
            with httpx.Client() as client:
                response = client.get(api_url, params=params, timeout=30, headers={"User-Agent": self.app_user_agent})
                response.raise_for_status()
                return response.json()
                
        except httpx.TimeoutException as e:
            error_msg = f"请求超时: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        except httpx.HTTPStatusError as e:
            # 优化500错误信息，移除URL细节
            if e.response.status_code == 500:
                error_msg = "HTTP错误: 500 服务器内部错误，请稍后再试"
            else:
                error_msg = f"HTTP错误: {e.response.status_code} {str(e)}"
            logger.error(f"请求失败: {error_msg}, URL: {api_url}")
            return {"success": False, "message": error_msg}
        except httpx.RequestError as e:
            error_msg = f"请求失败: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        except ValueError as e:
            error_msg = f"响应解析失败: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "message": error_msg}
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {"success": False, "message": error_msg}


# 全局API实例
media302 = Media302Api()