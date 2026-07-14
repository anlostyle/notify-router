import logging
import time

from typing import Optional, Dict, Any, List

from notifyhub.plugins.utils import get_plugin_config

logger = logging.getLogger(__name__)


class nsrssConfig:
    """nsrss配置管理"""
    PLUGIN_ID = "nsrss"
    
    def __init__(self):
        self._config_cache = None
        self._last_fetch_time = 0
        self._cache_ttl = 30  # 缓存30秒，避免频繁数据库查询
    
    def _fetch_config(self) -> Optional[Dict[str, Any]]:
        """
        从数据库获取最新配置
        
        Returns:
            Optional[Dict]: 插件配置，如果不存在返回None
        """
        try:
            config = get_plugin_config(self.PLUGIN_ID)
            return config
        except Exception as e:
            logger.error(f"获取nsrss配置失败: {e}")
            return None
    
    def _get_config_with_cache(self) -> Optional[Dict[str, Any]]:
        """
        获取配置（带缓存机制）
        
        Returns:
            Optional[Dict]: 配置信息，如果不存在返回None
        """
        current_time = time.time()
        
        # 检查缓存是否过期
        if (self._config_cache is None or 
            current_time - self._last_fetch_time > self._cache_ttl):
            
            # 从数据库获取最新配置
            config_data = self._fetch_config()
            if config_data:
                try:
                    self._config_cache = config_data
                    self._last_fetch_time = current_time
                except (ValueError, SyntaxError) as e:
                    logger.error(f"解析nsrss配置失败: {e}")
                    return None
            else:
                self._config_cache = None
                self._last_fetch_time = current_time
        
        return self._config_cache
    
    def get_config(self) -> Optional[Dict[str, Any]]:
        """
        获取nsrss配置
        
        Returns:
            Optional[Dict]: 配置信息，如果不存在返回None
        """
        return self._get_config_with_cache()
    
    def _get_config_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值的通用方法
        
        Args:
            key: 配置键名
            default: 默认值
            
        Returns:
            Any: 配置值或默认值
        """
        config = self._get_config_with_cache()
        if config is None:
            return default
        return config.get(key, default)

    @property
    def site_list(self) -> Optional[List[str]]:
        """获取监控站点"""
        return self._get_config_value("site_list", [])

    @property
    def keyword(self) -> Optional[str]:
        """获取监控关键词"""
        return self._get_config_value("keyword", "")
    
    @property
    def bind_routes(self) -> Optional[List[str]]:
        """获取绑定通道"""
        return self._get_config_value("bind_routes", [])
    
    @property
    def rss_cron(self) -> Optional[str]:
        """获取RSS定时任务"""
        return self._get_config_value("rss_cron")
    
    def validate_config(self) -> Dict[str, bool]:
        """
        验证配置完整性
        
        Returns:
            Dict[str, bool]: 各配置项的验证结果
        """
        validation_result = {
            'site_list': bool(self.site_list),
            'keyword': bool(self.keyword),
            'bind_routes': bool(self.bind_routes),
            'rss_cron': bool(self.rss_cron),
        }
        
        return validation_result
    
    def get_missing_configs(self) -> List[str]:
        """
        获取缺失的配置项
        
        Returns:
            List[str]: 缺失的配置项列表
        """
        validation_result = self.validate_config()
        missing_configs = [key for key, valid in validation_result.items() if not valid]
        return missing_configs


# 全局配置实例
config = nsrssConfig()