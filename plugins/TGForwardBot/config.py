import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Set

from notifyhub.plugins.utils import get_plugin_config

logger = logging.getLogger(__name__)

PLUGIN_ID = "TGForwardBot"


class TGForwardBotConfig:
    """TG双向私聊机器人配置"""
    
    def __init__(self):
        self._config: Optional[Dict[str, Any]] = None
        self._workdir: Optional[str] = None
        self._conf_dir: Optional[Path] = None
        self._blocklist_file: Optional[Path] = None
        self._blocklist_cache: Optional[Set[int]] = None  # 用户ID集合（用于快速查找）
        self._blocklist_data_cache: Optional[List[Dict[str, Any]]] = None  # 完整数据（包含姓名）
        
        # 初始化目录和文件
        self._init_directories()
        self._load_config()
    
    def _init_directories(self):
        """初始化配置目录和文件"""
        try:
            # 获取 workdir
            self._workdir = os.environ.get("WORKDIR", os.getcwd())
            
            # 创建 conf/TGForwardBot 目录
            conf_dir = os.path.join(self._workdir, "conf")
            self._conf_dir = Path(conf_dir) / PLUGIN_ID
            self._conf_dir.mkdir(parents=True, exist_ok=True)
            
            # blocklist 文件路径
            self._blocklist_file = self._conf_dir / "blocklist.json"
            
            # 如果 blocklist 文件不存在，创建空文件
            if not self._blocklist_file.exists():
                self._save_blocklist_data([])
                logger.info(f"[{PLUGIN_ID}] 创建 blocklist 文件: {self._blocklist_file}")
            
            logger.info(f"[{PLUGIN_ID}] 配置目录初始化完成: {self._conf_dir}")
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 初始化配置目录失败: {e}", exc_info=True)
            # 设置默认值，避免后续出错
            self._conf_dir = None
            self._blocklist_file = None
    
    def _load_config(self):
        """加载配置"""
        try:
            self._config = get_plugin_config(PLUGIN_ID) or {}
        except Exception as e:
            logger.error(f"加载插件配置失败: {e}", exc_info=True)
            self._config = {}
    
    def reload(self):
        """重新加载配置"""
        self._load_config()
        # 清除 blocklist 缓存，下次访问时重新加载
        self._blocklist_cache = None
        self._blocklist_data_cache = None
    
    @property
    def bot_token(self) -> str:
        """获取Bot Token"""
        return self._config.get("tgbot_token", "") if self._config else ""
    
    @property
    def manager_chatid(self) -> str:
        """获取管理员ChatID"""
        return self._config.get("manager_chatid", "") if self._config else ""
    
    @property
    def proxy(self) -> Optional[str]:
        """获取代理地址"""
        if not self._config:
            return None
        proxy = self._config.get("proxy", "").strip()
        return proxy if proxy else None

    @property
    def block_keywords(self) -> Optional[List[str]]:
        """获取封禁关键词"""
        if not self._config:
            return None
        block_keywords = self._config.get("block_keywords", "").strip()
        if block_keywords:
            block_keywords = block_keywords.split(",")
            block_keywords = [keyword.strip() for keyword in block_keywords]
            block_keywords = [keyword for keyword in block_keywords if keyword]
            return block_keywords
        return None
    
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return bool(self.bot_token and self.manager_chatid)
    
    def _load_blocklist(self) -> Set[int]:
        """
        加载封禁用户列表（返回用户ID集合，用于快速查找）
        
        Returns:
            Set[int]: 封禁用户ID集合
        """
        # 如果缓存存在，直接返回
        if self._blocklist_cache is not None:
            return self._blocklist_cache
        
        # 加载完整数据
        self._load_blocklist_data()
        
        # 从完整数据中提取用户ID集合
        if self._blocklist_data_cache:
            self._blocklist_cache = {item["user_id"] for item in self._blocklist_data_cache}
        else:
            self._blocklist_cache = set()
        
        return self._blocklist_cache
    
    def _load_blocklist_data(self) -> List[Dict[str, Any]]:
        """
        加载封禁用户完整数据（包含用户ID和姓名）
        
        Returns:
            List[Dict[str, Any]]: 封禁用户信息列表，格式：[{"user_id": int, "name": str}, ...]
        """
        if self._blocklist_data_cache is not None:
            return self._blocklist_data_cache
        
        if not self._blocklist_file or not self._blocklist_file.exists():
            self._blocklist_data_cache = []
            return self._blocklist_data_cache
        
        try:
            with open(self._blocklist_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # 处理嵌套列表的情况（兼容格式错误）
                if isinstance(data, list) and len(data) > 0:
                    # 如果第一个元素是列表，说明是嵌套列表 [[...]]，需要展开
                    if isinstance(data[0], list):
                        data = data[0]
                
                # 处理格式：包含 user_id 和 name 的对象列表
                if isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], dict) and "user_id" in data[0]:
                        # 格式：[{"user_id": int, "name": str}, ...]
                        self._blocklist_data_cache = [
                            {"user_id": int(item["user_id"]), "name": str(item.get("name", ""))}
                            for item in data
                            if "user_id" in item
                        ]
                    else:
                        self._blocklist_data_cache = []
                else:
                    self._blocklist_data_cache = []
            
            logger.debug(f"[{PLUGIN_ID}] 加载 blocklist 数据: {len(self._blocklist_data_cache)} 个用户")
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 加载 blocklist 失败: {e}", exc_info=True)
            self._blocklist_data_cache = []
        
        return self._blocklist_data_cache
    
    def _save_blocklist_data(self, blocklist_data: List[Dict[str, Any]]):
        """
        保存封禁用户完整数据到文件
        
        Args:
            blocklist_data: 用户信息列表，格式：[{"user_id": int, "name": str}, ...]
        """
        if not self._blocklist_file:
            logger.error(f"[{PLUGIN_ID}] blocklist 文件路径未初始化")
            return False
        
        try:
            # 去重（基于 user_id）并排序
            seen_ids = set()
            unique_data = []
            for item in blocklist_data:
                user_id = int(item["user_id"])
                if user_id not in seen_ids:
                    seen_ids.add(user_id)
                    unique_data.append({
                        "user_id": user_id,
                        "name": str(item.get("name", "")).strip()
                    })
            
            # 按 user_id 排序
            unique_data.sort(key=lambda x: x["user_id"])
            
            with open(self._blocklist_file, "w", encoding="utf-8") as f:
                json.dump(unique_data, f, indent=2, ensure_ascii=False)
            
            # 更新缓存
            self._blocklist_data_cache = unique_data
            self._blocklist_cache = {item["user_id"] for item in unique_data}
            
            logger.info(f"[{PLUGIN_ID}] 保存 blocklist: {len(unique_data)} 个用户")
            return True
            
        except Exception as e:
            logger.error(f"[{PLUGIN_ID}] 保存 blocklist 失败: {e}", exc_info=True)
            return False
    
    def is_blocked(self, user_id: int) -> bool:
        """
        检查用户是否被封禁
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否被封禁
        """
        blocklist = self._load_blocklist()
        return user_id in blocklist
    
    def add_to_blocklist(self, user_id: int, name: str = "") -> bool:
        """
        添加用户到封禁列表
        
        Args:
            user_id: 用户ID
            name: 用户姓名（可选）
            
        Returns:
            bool: 是否添加成功
        """
        blocklist_data = self._load_blocklist_data()
        
        # 检查是否已存在
        for item in blocklist_data:
            if item["user_id"] == user_id:
                # 如果已存在但姓名不同，更新姓名
                if name and item["name"] != name:
                    item["name"] = name
                    return self._save_blocklist_data(blocklist_data)
                logger.warning(f"[{PLUGIN_ID}] 用户 {user_id} 已在封禁列表中")
                return False
        
        # 添加新用户
        blocklist_data.append({
            "user_id": user_id,
            "name": name.strip() if name else ""
        })
        
        return self._save_blocklist_data(blocklist_data)
    
    def remove_from_blocklist(self, user_id: int) -> bool:
        """
        从封禁列表中移除用户
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否移除成功
        """
        blocklist_data = self._load_blocklist_data()
        
        # 查找并移除
        original_count = len(blocklist_data)
        blocklist_data = [item for item in blocklist_data if item["user_id"] != user_id]
        
        if len(blocklist_data) == original_count:
            logger.warning(f"[{PLUGIN_ID}] 用户 {user_id} 不在封禁列表中")
            return False
        
        return self._save_blocklist_data(blocklist_data)
    
    def get_blocklist(self) -> List[Dict[str, Any]]:
        """
        获取封禁用户完整列表（包含用户ID和姓名）
        
        Returns:
            List[Dict[str, Any]]: 封禁用户信息列表，格式：[{"user_id": int, "name": str}, ...]
        """
        return self._load_blocklist_data()
    
    def get_blocklist_user_ids(self) -> List[int]:
        """
        获取封禁用户ID列表（兼容旧接口）
        
        Returns:
            List[int]: 封禁用户ID列表
        """
        blocklist = self._load_blocklist()
        return sorted(list(blocklist))
    
    @property
    def conf_dir(self) -> Optional[Path]:
        """获取配置目录路径"""
        return self._conf_dir
    
    @property
    def blocklist_file(self) -> Optional[Path]:
        """获取 blocklist 文件路径"""
        return self._blocklist_file


# 全局配置实例
config = TGForwardBotConfig()

