import os
import json
import logging
import httpx

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Optional

from notifyhub.controller.server import Server

from .utils import config

logger = logging.getLogger(__name__)
server = Server()

class RSSMonitor:
    def __init__(self):
        self.keywords = []
        self.bind_routes = config.bind_routes
        self.ns_url = "https://rss.nodeseek.com/"
        self.df_url = "https://feed.deepflood.com/topic.rss.xml"
        self.setup_data_storage()
            
    def setup_data_storage(self):
        """设置数据存储"""
        self.processed_file = os.path.join(os.environ.get("WORKDIR"), 'conf', 'nsrss', 'processed_posts.json')
        if not os.path.isdir(os.path.dirname(self.processed_file)):
            os.makedirs(os.path.dirname(self.processed_file), exist_ok=True)
        self.processed_posts = self.load_processed_posts()
        self.ns_list = set(self.processed_posts.get("ns", []))
        self.df_list = set(self.processed_posts.get("df", []))
        
    def load_processed_posts(self) -> Dict[str, List[str]]:
        """加载已处理的帖子ID"""
        try:
            if not os.path.isfile(self.processed_file):
                return {}
            with open(self.processed_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get('processed_ids', {})
        except Exception as e:
            logger.error(f"加载已处理帖子记录失败: {e}", exc_info=True)
            return {}
            
    def save_processed_posts(self):
        """保存已处理的帖子ID"""
        try:
            data = {
                'processed_ids': {
                    "ns": list(self.ns_list),
                    "df": list(self.df_list)
                },
                'last_update': datetime.now().isoformat()
            }
            os.makedirs(os.path.dirname(self.processed_file), exist_ok=True)
            temp_file = self.processed_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, self.processed_file)
        except Exception as e:
            logger.error(f"保存已处理帖子记录失败: {e}", exc_info=True)
    
    def send_notify(self, title: str, content: str, link: str):
        """发送通知到指定路由"""
        try:
            for route in self.bind_routes:
                server.send_notify_by_router(route, title, content, push_link_url=link)
        except Exception as e:
            logger.error(f"发送通知失败: {e}", exc_info=True)
            return False
        return True

    def fetch_rss(self, rss_url: str) -> Optional[str]:
        """获取RSS内容"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            resp = httpx.get(rss_url, headers=headers, timeout=30)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            
            # logger.info("RSS获取成功")
            return resp.text
            
        except httpx.RequestError as e:
            logger.error(f"RSS获取失败: {e}", exc_info=True)
            return None
            
    def parse_rss(self, rss_content: str) -> List[Dict]:
        """解析RSS内容"""
        try:
            root = ET.fromstring(rss_content)
            items = []
            
            # 查找所有item元素
            for item in root.findall('.//item'):
                try:
                    # 提取标题
                    title_elem = item.find('title')
                    title = title_elem.text if title_elem is not None else ''
                    
                    # 提取描述
                    description_elem = item.find('description')
                    description = description_elem.text if description_elem is not None else ''
                    
                    # 提取链接
                    link_elem = item.find('link')
                    link = link_elem.text if link_elem is not None else ''
                    
                    # 提取GUID (帖子ID)
                    guid_elem = item.find('guid')
                    guid = guid_elem.text if guid_elem is not None else ''
                    
                    # 提取发布时间
                    pubdate_elem = item.find('pubDate')
                    pubdate = pubdate_elem.text if pubdate_elem is not None else ''
                    
                    # 提取作者
                    creator_elem = item.find('.//{http://purl.org/dc/elements/1.1/}creator')
                    creator = creator_elem.text if creator_elem is not None else ''
                    
                    if guid:  # 只处理有ID的帖子
                        items.append({
                            'id': guid,
                            'title': title,
                            'description': description,
                            'link': link,
                            'pubdate': pubdate,
                            'creator': creator
                        })
                        
                except Exception as e:
                    logger.warning(f"解析item失败: {e}")
                    continue
                    
            # logger.info(f"成功解析 {len(items)} 个帖子")
            return items
            
        except ET.ParseError as e:
            logger.error(f"RSS解析失败: {e}")
            return []
            
    def check_keywords(self, text: str) -> List[str]:
        """检查文本中是否包含关键词"""
        found_keywords = []
        text_lower = text.lower()
        
        for keyword in self.keywords:
            if keyword.lower() in text_lower:
                found_keywords.append(keyword)
                
        return found_keywords
            
    def process_items(self, items: List[Dict]):
        """处理RSS项目"""
        new_matches = 0
        
        for item in items:
            post_id = item['id']
            if self.site == "NS":
                history_list = self.ns_list
            elif self.site == "DF":
                history_list = self.df_list
            # 检查是否已处理过
            if post_id in history_list:
                continue
                
            # 检查标题和描述中的关键词
            title_keywords = self.check_keywords(item['title'])
            desc_keywords = self.check_keywords(item['description'])
            
            all_keywords = list(set(title_keywords + desc_keywords))
            
            if all_keywords:
                # 发现匹配的关键词
                logger.info(f"发现匹配帖子: ID={post_id}, 关键词={all_keywords}")
                
                # 准备通知内容
                site = "NodeSeek论坛" if self.site == "NS" else "DeepFlood论坛"
                notification_title = f"{site}关键词监控 - {', '.join(all_keywords)}"
                notification_content = f"""
帖子标题: {item['title']}

匹配关键词: {', '.join(all_keywords)}

帖子链接: {item['link']}

作者: {item['creator']}

发布时间: {item['pubdate']}

帖子描述:
{item['description'][:500]}{'...' if len(item['description']) > 500 else ''}
"""
                
                # 发送通知
                if self.send_notify(notification_title, notification_content, item['link']):
                    # 标记为已处理
                    history_list.add(post_id)
                    new_matches += 1
                    logger.info(f"帖子 {post_id} 处理完成")
                else:
                    logger.warning(f"帖子 {post_id} 通知发送失败")
                    
        if new_matches > 0:
            if self.site == "NS":
                self.ns_list = history_list
            elif self.site == "DF":
                self.df_list = history_list
            self.save_processed_posts()
            logger.info(f"本次检查发现 {new_matches} 个新匹配帖子")
        else:
            logger.debug("本次检查无新匹配帖子")
            
    def run_once(self):
        """执行一次检查"""
        # logger.info("开始执行RSS检查...")
        keywords = config.keyword.split(',')
        self.keywords = [keyword.strip() for keyword in keywords]
        # logger.info(f"检查关键字: {self.keywords}")
        
        for site in config.site_list:
            if site == "ns":
                rss_url = self.ns_url
                self.site = "NS"
            elif site == "df":
                rss_url = self.df_url
                self.site = "DF"
            # 获取RSS内容
            rss_content = self.fetch_rss(rss_url)
            if not rss_content:
                logger.error("无法获取RSS内容，跳过本次检查")
                continue
                
            # 解析RSS
            items = self.parse_rss(rss_content)
            if not items:
                logger.error("无法解析RSS内容，跳过本次检查")
                continue
                
            # 处理项目
            self.process_items(items)
        
        # logger.info("RSS检查完成")
