import json
import os
import aiohttp
import asyncio
import mimetypes
import re
import random
from pathlib import Path
from typing import Optional, Dict, List, Union
import urllib.parse
import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image, Video, Node, Nodes
from astrbot.api import AstrBotConfig

DATA_FILE = Path(__file__).parent / "api_config.json"

@register("astrbot_plugin_picture_manager", "代码工匠💻",
          "API图片/视频/文本发送插件，允许用户通过自定义触发指令从API获取图片、视频或文本内容，支持多链接转发和随机API调用",
          "v2.3.0")
class PictureManagerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.api_list: Dict[str, List[str]] = {}  # 触发指令映射到API地址列表
        self.direct_url_list: Dict[str, List[str]] = {}  # 触发指令映射到直接图片/视频URL列表
        self.text_api_list: Dict[str, List[str]] = {}  # 触发指令映射到文本API地址列表
        self.bot_id: str = "AstrBot"  # 机器人ID/昵称，用于转发消息
        
        # 从配置中读取插件总开关和默认数量
        self.is_enabled: bool = config.enabled if hasattr(config, 'enabled') else True
        self.default_view_count: int = max(1, config.default_view_count) if hasattr(config, 'default_view_count') else 1
        
        # 配置日志记录器
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # 创建控制台处理器，仅在未有处理器时添加
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        self.load_api_config()  # 加载存储的API配置
        self.logger.info("图片/视频/文本发送插件初始化完成")

    def load_api_config(self):
        """加载API配置文件"""
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.api_list = {k: v if isinstance(v, list) else [v] for k, v in data.get('api_list', {}).items()}
                    self.direct_url_list = {k: v if isinstance(v, list) else [v] for k, v in data.get('direct_url_list', {}).items()}
                    self.text_api_list = {k: v if isinstance(v, list) else [v] for k, v in data.get('text_api_list', {}).items()}
            except json.JSONDecodeError as e:
                self.logger.error(f"加载配置文件失败，格式错误: {e}")
                self.api_list = {}
                self.direct_url_list = {}
                self.text_api_list = {}
        else:
            self.api_list = {}
            self.direct_url_list = {}
            self.text_api_list = {}

    def save_api_config(self):
        """保存API配置文件"""
        data = {
            'api_list': self.api_list.copy(),
            'direct_url_list': self.direct_url_list.copy(),
            'text_api_list': self.text_api_list.copy()
        }
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")

    # 修改：查看所有服务器API并返回完整内容
    @filter.command("查看所有服务器")
    async def list_servers(self, event: AstrMessageEvent):
        """请求所有包含'服务器'关键词的API，并返回完整汇总内容"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        # 搜索所有包含"服务器"关键词的触发指令
        server_tasks = []
        
        # 搜索图片/视频API
        for trigger, urls in self.api_list.items():
            if "服务器" in trigger:
                for url in urls:
                    server_tasks.append({
                        "trigger": trigger,
                        "type": "图片/视频API",
                        "url": url
                    })
        
        # 搜索直接URL
        for trigger, urls in self.direct_url_list.items():
            if "服务器" in trigger:
                for url in urls:
                    server_tasks.append({
                        "trigger": trigger,
                        "type": "直接图片/视频URL",
                        "url": url
                    })
        
        # 搜索文本API
        for trigger, urls in self.text_api_list.items():
            if "服务器" in trigger:
                for url in urls:
                    server_tasks.append({
                        "trigger": trigger,
                        "type": "文本API",
                        "url": url
                    })

        if not server_tasks:
            yield event.plain_result("没有找到包含'服务器'关键词的API")
            return

        yield event.plain_result(f"🔍 正在请求 {len(server_tasks)} 个服务器相关API，请稍候...")

        # 并发请求所有服务器API
        results = []
        for task in server_tasks:
            try:
                if task["type"] == "文本API":
                    content = await self._fetch_text_content(task["url"])
                    results.append({
                        "trigger": task["trigger"],
                        "type": task["type"],
                        "url": task["url"],
                        "content": content,
                        "success": True
                    })
                elif task["type"] == "图片/视频API":
                    media_urls = await self._fetch_media_urls_from_api(task["url"])
                    results.append({
                        "trigger": task["trigger"],
                        "type": task["type"],
                        "url": task["url"],
                        "content": f"获取到 {len(media_urls)} 个媒体链接",
                        "media_urls": media_urls,
                        "success": True
                    })
                else:  # 直接图片/视频URL
                    media_info = await self._fetch_media_info(task["url"])
                    results.append({
                        "trigger": task["trigger"],
                        "type": task["type"],
                        "url": task["url"],
                        "content": media_info,
                        "success": True
                    })
            except Exception as e:
                results.append({
                    "trigger": task["trigger"],
                    "type": task["type"],
                    "url": task["url"],
                    "content": f"请求失败: {str(e)}",
                    "success": False
                })

        # 构建汇总结果 - 分批次发送，避免消息过长
        success_count = sum(1 for r in results if r["success"])
        failed_count = len(results) - success_count
        
        # 发送汇总头部
        summary_header = f"📊 服务器API请求汇总 (成功: {success_count}, 失败: {failed_count})\n\n"
        yield event.plain_result(summary_header)
        
        # 分批发送每个API的详细结果
        for i, result in enumerate(results, 1):
            status_icon = "✅" if result["success"] else "❌"
            api_result = f"{i}. {status_icon} 【{result['type']}】{result['trigger']}\n"
            api_result += f"   📍 地址: {result['url']}\n"
            api_result += f"   📝 结果: {result['content']}\n"
            
            # 如果是图片/视频API且成功获取到媒体链接，显示所有链接
            if result["success"] and "media_urls" in result and result["media_urls"]:
                api_result += f"   🖼️ 媒体链接 ({len(result['media_urls'])} 个):\n"
                for j, media_url in enumerate(result["media_urls"], 1):
                    api_result += f"      {j}. {media_url}\n"
            
            api_result += "\n"
            
            # 发送单个API的结果
            yield event.plain_result(api_result)
            
            # 如果是文本API且内容很长，可能需要进一步分割
            if result["success"] and result["type"] == "文本API" and len(result["content"]) > 1000:
                # 如果文本内容特别长，分开发送
                content_parts = self._split_long_text(result["content"], 1500)
                for part_num, part in enumerate(content_parts, 1):
                    yield event.plain_result(f"   📄 内容部分 {part_num}/{len(content_parts)}:\n{part}\n")

        # 发送统计信息
        stats = f"📈 统计信息:\n"
        stats += f"- 总请求数: {len(results)}\n"
        stats += f"- 成功: {success_count}\n"
        stats += f"- 失败: {failed_count}\n"
        stats += f"- 成功率: {success_count/len(results)*100:.1f}%"
        
        yield event.plain_result(stats)

    # 新增：分割长文本的辅助方法
    def _split_long_text(self, text: str, max_length: int) -> List[str]:
        """将长文本分割为多个部分"""
        if len(text) <= max_length:
            return [text]
        
        parts = []
        start = 0
        while start < len(text):
            # 尽量在句子边界处分割
            end = start + max_length
            if end < len(text):
                # 查找合适的分割点（换行、句号、空格）
                for split_point in range(end, start, -1):
                    if split_point < len(text) and text[split_point] in ['\n', '。', '.', ' ']:
                        end = split_point + 1
                        break
            parts.append(text[start:end])
            start = end
        
        return parts

    # 修改：获取文本内容的辅助方法 - 移除长度限制
    async def _fetch_text_content(self, url: str) -> str:
        """获取文本API的完整内容"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return f"HTTP错误: {response.status}"
                    
                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    if 'application/json' in content_type:
                        data = await response.json()
                        text_content = self._parse_json_response(data)
                        return text_content
                    else:
                        text_content = await response.text(encoding='utf-8', errors='ignore')
                        text_content = text_content.strip()
                        return text_content or "空内容"
        except asyncio.TimeoutError:
            return "请求超时"
        except aiohttp.ClientError as e:
            return f"网络错误: {str(e)}"
        except Exception as e:
            return f"处理错误: {str(e)}"

    # 修改：从API获取媒体链接 - 移除数量限制
    async def _fetch_media_urls_from_api(self, api_url: str) -> List[str]:
        """从API获取所有媒体链接"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return []
                    
                    content_type = response.headers.get('Content-Type', '').lower()
                    file_urls = []
                    
                    if 'json' in content_type:
                        content = await response.json()
                        if isinstance(content, list):
                            file_urls = [item.get('url', '') for item in content if 'url' in item]
                        elif isinstance(content, dict):
                            url = content.get('url', '')
                            if url:
                                file_urls = [url]
                            else:
                                file_urls = [content.get('data', {}).get('url', '')]
                    else:
                        content = await response.text(encoding='utf-8', errors='ignore')
                        lines = content.splitlines()
                        if len(lines) > 1:
                            file_urls = [line.strip() for line in lines if line.strip().startswith(('http://', 'https://'))]
                        else:
                            file_urls = [content.strip()]
                    
                    # 过滤无效URL
                    valid_urls = [url for url in file_urls if url.startswith(('http://', 'https://'))]
                    return valid_urls
        except Exception as e:
            self.logger.error(f"获取媒体链接失败: {str(e)}")
            return []

    # 修改：获取直接媒体信息 - 提供更详细信息
    async def _fetch_media_info(self, url: str) -> str:
        """获取直接媒体URL的完整信息"""
        try:
            final_url = await self.get_latest_url(url)
            async with aiohttp.ClientSession() as session:
                async with session.get(final_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        return f"无法访问媒体: HTTP {response.status}"
                    
                    content_type = response.headers.get('Content-Type', '')
                    content_length = response.headers.get('Content-Length', '未知')
                    content_encoding = response.headers.get('Content-Encoding', '未知')
                    
                    info = f"媒体类型: {content_type}\n"
                    info += f"文件大小: {content_length}\n"
                    info += f"编码方式: {content_encoding}\n"
                    info += f"最终URL: {final_url}"
                    
                    return info
        except Exception as e:
            return f"获取媒体信息失败: {str(e)}"

    # 原有的其他方法保持不变...
    @filter.command("开启看图")
    async def enable_picture(self, event: AstrMessageEvent):
        """开启发图功能"""
        self.is_enabled = True
        yield event.plain_result("发图/发视频/发文本功能已开启")

    @filter.command("关闭看图")
    async def disable_picture(self, event: AstrMessageEvent):
        """关闭发图功能"""
        self.is_enabled = False
        yield event.plain_result("发图/发视频/发文本功能已关闭")

    @filter.command("看图列表")
    async def list_apis(self, event: AstrMessageEvent):
        """显示所有可用的API和直接URL"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if not self.api_list and not self.direct_url_list and not self.text_api_list:
            yield event.plain_result("暂无可用的API或直接图片/视频URL或文本API")
            return

        msg = "可用API列表:\n"
        for trigger, urls in self.api_list.items():
            msg += f"触发指令: {trigger}\n对应地址: {', '.join(urls)}\n"
        
        msg += "\n可用直接图片/视频URL列表:\n"
        for trigger, urls in self.direct_url_list.items():
            msg += f"触发指令: {trigger}\n基础地址: {', '.join(urls)}\n"
        
        msg += "\n可用文本API列表:\n"
        for trigger, urls in self.text_api_list.items():
            msg += f"触发指令: {trigger}\n对应地址: {', '.join(urls)}\n"
        
        yield event.plain_result(msg)

    @filter.command("增加看图")
    async def add_api_or_url(self, event: AstrMessageEvent, trigger: str, url: str):
        """增加新的API或直接图片/视频URL"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; AMOI N828 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 SogouMSE/1.2.1'
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '').lower()
                        if content_type.startswith(('image/', 'video/')):
                            if trigger in self.direct_url_list:
                                self.direct_url_list[trigger].append(url)
                            else:
                                self.direct_url_list[trigger] = [url]
                            self.save_api_config()
                            yield event.plain_result(f"成功添加直接图片/视频URL - 触发指令: {trigger}, 基础地址: {url}")
                        elif content_type.startswith(('text/', 'application/json')):
                            if trigger in self.text_api_list:
                                self.text_api_list[trigger].append(url)
                            else:
                                self.text_api_list[trigger] = [url]
                            self.save_api_config()
                            yield event.plain_result(f"成功添加文本API - 触发指令: {trigger}, 地址: {url}")
                        else:
                            if trigger in self.api_list:
                                self.api_list[trigger].append(url)
                            else:
                                self.api_list[trigger] = [url]
                            self.save_api_config()
                            yield event.plain_result(f"成功添加API - 触发指令: {trigger}, 地址: {url}")
                    else:
                        if trigger in self.text_api_list:
                            self.text_api_list[trigger].append(url)
                        else:
                            self.text_api_list[trigger] = [url]
                        self.save_api_config()
                        yield event.plain_result(f"成功添加文本API - 触发指令: {trigger}, 地址: {url}")
        except aiohttp.ClientError as e:
            yield event.plain_result(f"添加失败，网络错误: {str(e)}")
        except Exception as e:
            yield event.plain_result(f"添加失败，发生错误: {str(e)}")

    @filter.command("增加文本")
    async def add_text_api(self, event: AstrMessageEvent, trigger: str, url: str):
        """专门添加文本API"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        if trigger in self.text_api_list:
            self.text_api_list[trigger].append(url)
        else:
            self.text_api_list[trigger] = [url]
        self.save_api_config()
        yield event.plain_result(f"成功添加文本API - 触发指令: {trigger}, 地址: {url}")

    @filter.command("修改看图地址")
    async def modify_api_address(self, event: AstrMessageEvent, trigger: str, index: int, new_url: str):
        """修改API或直接图片/视频URL地址，index从1开始"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        modified = False
        
        if trigger in self.api_list:
            if 1 <= index <= len(self.api_list[trigger]):
                self.api_list[trigger][index - 1] = new_url
                modified = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        elif trigger in self.direct_url_list:
            if 1 <= index <= len(self.direct_url_list[trigger]):
                self.direct_url_list[trigger][index - 1] = new_url
                modified = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        elif trigger in self.text_api_list:
            if 1 <= index <= len(self.text_api_list[trigger]):
                self.text_api_list[trigger][index - 1] = new_url
                modified = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        else:
            yield event.plain_result("触发指令不存在")
            return

        if modified:
            self.save_api_config()
            yield event.plain_result(f"成功修改触发指令 {trigger} 的第 {index} 个地址为 {new_url}")

    @filter.command("删除看图")
    async def delete_api(self, event: AstrMessageEvent, trigger: str, index: Optional[int] = None):
        """删除API或直接图片/视频URL，index不填则删除整个触发指令"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        deleted = False
        
        if trigger in self.api_list:
            if index is None:
                del self.api_list[trigger]
                deleted = True
            elif 1 <= index <= len(self.api_list[trigger]):
                self.api_list[trigger].pop(index - 1)
                if not self.api_list[trigger]:
                    del self.api_list[trigger]
                deleted = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        elif trigger in self.direct_url_list:
            if index is None:
                del self.direct_url_list[trigger]
                deleted = True
            elif 1 <= index <= len(self.direct_url_list[trigger]):
                self.direct_url_list[trigger].pop(index - 1)
                if not self.direct_url_list[trigger]:
                    del self.direct_url_list[trigger]
                deleted = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        elif trigger in self.text_api_list:
            if index is None:
                del self.text_api_list[trigger]
                deleted = True
            elif 1 <= index <= len(self.text_api_list[trigger]):
                self.text_api_list[trigger].pop(index - 1)
                if not self.text_api_list[trigger]:
                    del self.text_api_list[trigger]
                deleted = True
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        else:
            yield event.plain_result("触发指令不存在")
            return

        if deleted:
            self.save_api_config()
            yield event.plain_result(f"成功删除触发指令 {trigger} 的相关地址")

    @filter.command("随机看图")
    async def random_picture(self, event: AstrMessageEvent):
        """随机发送一张图片、一段视频或一段文本"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if not self.api_list and not self.direct_url_list and not self.text_api_list:
            yield event.plain_result("暂无可用的API或直接图片/视频URL或文本API")
            return

        all_triggers = list(self.api_list.keys()) + list(self.direct_url_list.keys()) + list(self.text_api_list.keys())
        if not all_triggers:
            yield event.plain_result("暂无可用的触发指令")
            return
            
        trigger = random.choice(all_triggers)
        
        if trigger in self.api_list:
            api_urls = self.api_list[trigger]
            api_url = random.choice(api_urls)
            async for result in self.send_picture(event, api_url):
                yield result
        elif trigger in self.direct_url_list:
            urls = self.direct_url_list[trigger]
            url = random.choice(urls)
            async for result in self.send_direct_image(event, url):
                yield result
        else:
            urls = self.text_api_list[trigger]
            url = random.choice(urls)
            async for result in self.send_text(event, url):
                yield result

    @filter.command("随机文本")
    async def random_text(self, event: AstrMessageEvent):
        """随机发送一段文本内容"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if not self.text_api_list:
            yield event.plain_result("暂无可用的文本API")
            return

        trigger = random.choice(list(self.text_api_list.keys()))
        urls = self.text_api_list[trigger]
        url = random.choice(urls)
        async for result in self.send_text(event, url):
            yield result

    @filter.command("看图帮助")
    async def picture_help(self, event: AstrMessageEvent):
        """显示插件的使用帮助"""
        help_msg = """
发图/发视频/发文本插件使用帮助:

1. /开启看图 - 开启发图/发视频/发文本功能
   - 使用示例: /开启看图

2. /关闭看图 - 关闭发图/发视频/发文本功能
   - 使用示例: /关闭看图

3. /看图列表 - 查看所有可用的API、直接图片/视频URL和文本API
   - 使用示例: /看图列表

4. /查看所有服务器 - 请求所有包含"服务器"关键词的API并返回完整汇总内容
   - 使用示例: /查看所有服务器

5. /增加看图 [触发指令] [地址] - 增加新的API、直接图片/视频URL或文本API
   - 使用示例: /增加看图 cute_cat 图片/视频URL或API地址
   - 智能识别：自动检测内容类型

6. /增加文本 [触发指令] [地址] - 专门添加文本API
   - 使用示例: /增加文本 每日一言 https://v1.hitokoto.cn/

7. /修改看图地址 [触发指令] [索引] [新地址] - 修改已存在的API、图片/视频URL或文本API地址
   - 使用示例: /修改看图地址 cute_cat 1 新地址

8. /删除看图 [触发指令] [索引] - 删除指定的API、直接图片/视频URL或文本API
   - 使用示例: /删除看图 cute_cat 1 或 /删除看图 cute_cat

9. /随机看图 - 从所有已添加的API、直接URL和文本API中随机选择一个发送
   - 使用示例: /随机看图

10. /随机文本 - 从文本API中随机选择一个发送文本内容
    - 使用示例: /随机文本

11. /看图 [触发指令] [数量] - 指定触发指令获取指定数量的图片/视频
    - 使用示例: /看图 cute_cat 3

12. /文本 [触发指令] - 指定触发指令获取文本内容
    - 使用示例: /文本 每日一言

13. [触发指令] - 直接使用已添加的触发指令来发送图片、视频或文本
    - 使用示例: 如果您添加了cute_cat作为触发指令，发送cute_cat即可获取图片/视频

注意事项:
- 确保功能已开启才能使用
- 每个触发指令可以对应多个地址，调用时随机选择一个
- 文本API应返回有效的文本内容（JSON或纯文本）
- /查看所有服务器 会实际请求所有相关API并返回完整内容，可能需要较长时间
"""
        yield event.plain_result(help_msg)

    @filter.command("图片")
    async def picture(self, event: AstrMessageEvent, trigger: Optional[str] = None):
        """通过触发指令发送图片或视频"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if trigger is None:
            yield event.plain_result("请指定触发指令")
            return

        trigger = trigger.lower()
        if trigger in self.api_list:
            api_urls = self.api_list[trigger]
            api_url = random.choice(api_urls)
            async for result in self.send_picture(event, api_url):
                yield result
        elif trigger in self.direct_url_list:
            urls = self.direct_url_list[trigger]
            url = random.choice(urls)
            async for result in self.send_direct_image(event, url):
                yield result
        else:
            yield event.plain_result(f"触发指令 '{trigger}' 不存在或不是图片/视频类型")

    @filter.command("文本")
    async def send_text_command(self, event: AstrMessageEvent, trigger: Optional[str] = None):
        """通过触发指令发送文本内容"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if trigger is None:
            yield event.plain_result("请指定触发指令")
            return

        trigger = trigger.lower()
        if trigger in self.text_api_list:
            urls = self.text_api_list[trigger]
            url = random.choice(urls)
            async for result in self.send_text(event, url):
                yield result
        else:
            yield event.plain_result(f"文本触发指令 '{trigger}' 不存在")

    @filter.command("看图")
    async def view_picture(self, event: AstrMessageEvent, trigger: Optional[str] = None, count: Optional[int] = None):
        """指定触发指令获取指定数量的图片/视频，count不填则使用配置的默认值，count>2时使用转发"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if trigger is None:
            return

        trigger = trigger.lower()
        if trigger not in self.api_list and trigger not in self.direct_url_list:
            yield event.plain_result(f"触发指令 '{trigger}' 不存在或不是图片/视频类型")
            return

        count = max(1, count if count is not None else self.default_view_count)
        media_chains = []
        
        if trigger in self.api_list:
            for _ in range(count):
                api_urls = self.api_list[trigger]
                api_url = random.choice(api_urls)
                media_chain_list = await self._fetch_media_from_api(api_url)
                if media_chain_list:
                    media_chains.extend(media_chain_list)
        else:
            for _ in range(count):
                urls = self.direct_url_list[trigger]
                url = random.choice(urls)
                media_chain = await self._fetch_media_from_direct_url(url)
                if media_chain:
                    media_chains.append(media_chain)

        if not media_chains:
            yield event.plain_result("未能获取任何图片/视频")
            return

        if count > 2 or len(media_chains) > 2:
            nodes_list = []
            for i, chain in enumerate(media_chains[:max(count, len(media_chains))], 1):
                media_type = "图片" if isinstance(chain[0], Image) else "视频"
                node = Node(
                    uin=0,
                    name=f"{self.bot_id} - {media_type}{i}",
                    content=chain
                )
                nodes_list.append(node)
            yield event.chain_result([Nodes(nodes=nodes_list)])
        else:
            for chain in media_chains[:count]:
                yield event.chain_result(chain)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息，检查是否为用户定义的触发指令"""
        if not self.is_enabled:
            return

        message_str = event.message_str.lower()
        
        # 检查图片/视频API
        for trigger in self.api_list.keys():
            if re.match(f"^{re.escape(trigger)}$", message_str):
                api_urls = self.api_list[trigger]
                api_url = random.choice(api_urls)
                async for result in self.send_picture(event, api_url):
                    yield result
                event.stop_event()
                return

        # 检查直接URL
        for trigger in self.direct_url_list.keys():
            if re.match(f"^{re.escape(trigger)}$", message_str):
                urls = self.direct_url_list[trigger]
                url = random.choice(urls)
                async for result in self.send_direct_image(event, url):
                    yield result
                event.stop_event()
                return

        # 检查文本API
        for trigger in self.text_api_list.keys():
            if re.match(f"^{re.escape(trigger)}$", message_str):
                urls = self.text_api_list[trigger]
                url = random.choice(urls)
                async for result in self.send_text(event, url):
                    yield result
                event.stop_event()
                return

        # 随机功能
        if re.match("^随机看图$", message_str):
            async for result in self.random_picture(event):
                yield result
            event.stop_event()
        elif re.match("^随机文本$", message_str):
            async for result in self.random_text(event):
                yield result
            event.stop_event()
        # 新增：服务器相关快捷指令
        elif re.match("^查看所有服务器$", message_str):
            async for result in self.list_servers(event):
                yield result
            event.stop_event()

    # 原有的其他辅助方法保持不变...
    async def get_latest_url(self, base_url: str) -> str:
        """获取最新的图片/视频URL，处理重定向"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; AMOI N828 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 SogouMSE/1.2.1'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(base_url, allow_redirects=True) as response:
                if response.status == 200:
                    return str(response.url)
                else:
                    raise Exception(f"获取图片/视频URL失败，状态码: {response.status}")

    async def send_picture(self, event: AstrMessageEvent, api_url: str):
        """发送图片或视频，处理API返回的内容，处理所有有效链接"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, allow_redirects=True) as response:
                    if response.status != 200:
                        yield event.plain_result(f"访问API失败: {api_url}")
                        return

                    content_type = response.headers.get('Content-Type', '').lower()
                    file_urls = []
                    if 'json' in content_type:
                        content = await response.json()
                        if isinstance(content, list):
                            file_urls = [item.get('url', '') for item in content if 'url' in item]
                        elif isinstance(content, dict):
                            url = content.get('url', '')
                            if url:
                                file_urls = [url]
                            else:
                                file_urls = [content.get('data', {}).get('url', '')]
                    else:
                        content = await response.text(encoding='utf-8', errors='ignore')
                        lines = content.splitlines()
                        if len(lines) > 1:
                            file_urls = [line.strip() for line in lines if line.strip().startswith(('http://', 'https://'))]
                        else:
                            file_urls = [content.strip()]

                    if not file_urls:
                        yield event.plain_result(f"API返回无效的URL: {api_url}")
                        return

                    media_chains = []
                    for file_url in file_urls:
                        if not file_url.startswith(('http://', 'https://')):
                            continue
                        async with session.get(file_url, allow_redirects=True) as final_response:
                            if final_response.status != 200:
                                continue
                            content_type = final_response.headers.get('Content-Type', '').lower()
                            media_chain = self._determine_media_type(file_url, content_type)
                            media_chains.append(media_chain)

                    if not media_chains:
                        yield event.plain_result(f"未能获取任何有效的图片/视频: {api_url}")
                        return

                    if len(media_chains) > 2:
                        nodes_list = []
                        for i, chain in enumerate(media_chains, 1):
                            media_type = "图片" if isinstance(chain[0], Image) else "视频"
                            node = Node(
                                uin=0,
                                name=f"{self.bot_id} - {media_type}{i}",
                                content=chain
                            )
                            nodes_list.append(node)
                        yield event.chain_result([Nodes(nodes=nodes_list)])
                    else:
                        for chain in media_chains:
                            yield event.chain_result(chain)

        except aiohttp.ClientError as e:
            self.logger.error(f"发送图片/视频失败，网络错误: {str(e)}")
            yield event.plain_result(f"发送图片/视频失败: 网络错误")
        except Exception as e:
            self.logger.error(f"发送图片/视频失败: {str(e)}")
            yield event.plain_result(f"发送图片/视频失败: {str(e)}")

    async def send_direct_image(self, event: AstrMessageEvent, url: str):
        """发送直接图片URL或视频URL，处理重定向"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        try:
            url = await self.get_latest_url(url)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        yield event.plain_result(f"获取最终资源失败: {url}")
                        return

                    content_type = response.headers.get('Content-Type', '').lower()
                    self.logger.info(f"Content-Type: {content_type}")
                    message_chain = self._determine_media_type(url, content_type)
                    yield event.chain_result(message_chain)
        except aiohttp.ClientError as e:
            self.logger.error(f"发送图片/视频失败，网络错误: {str(e)}")
            yield event.plain_result(f"发送图片/视频失败: 网络错误")
        except Exception as e:
            self.logger.error(f"发送图片/视频失败: {str(e)}")
            yield event.plain_result(f"发送图片/视频失败: {str(e)}")

    async def send_text(self, event: AstrMessageEvent, api_url: str):
        """发送文本内容，处理API返回的文本"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        yield event.plain_result(f"文本API请求失败，状态码: {response.status}")
                        return

                    content_type = response.headers.get('Content-Type', '').lower()
                    
                    if 'application/json' in content_type:
                        data = await response.json()
                        text_content = self._parse_json_response(data)
                    else:
                        text_content = await response.text(encoding='utf-8', errors='ignore')
                        text_content = text_content.strip()

                    if not text_content:
                        yield event.plain_result("文本API返回空内容")
                        return

                    yield event.plain_result(text_content)

        except asyncio.TimeoutError:
            yield event.plain_result("文本API请求超时")
        except aiohttp.ClientError as e:
            self.logger.error(f"发送文本失败，网络错误: {str(e)}")
            yield event.plain_result(f"发送文本失败: 网络错误")
        except Exception as e:
            self.logger.error(f"发送文本失败: {str(e)}")
            yield event.plain_result(f"发送文本失败: {str(e)}")

    def _parse_json_response(self, data: Union[dict, list]) -> str:
        """解析JSON响应，提取文本内容"""
        try:
            if isinstance(data, dict):
                if 'hitokoto' in data and 'from' in data:
                    return f"{data['hitokoto']}\n—— {data.get('from', '未知')}"
                elif 'text' in data:
                    return data['text']
                elif 'content' in data:
                    return data['content']
                elif 'data' in data and isinstance(data['data'], dict):
                    sub_data = data['data']
                    if 'text' in sub_data:
                        return sub_data['text']
                    elif 'content' in sub_data:
                        return sub_data['content']
                elif 'msg' in data:
                    return data['msg']
                else:
                    for value in data.values():
                        if isinstance(value, str) and value.strip():
                            return value
            elif isinstance(data, list) and data:
                return self._parse_json_response(data[0])
            
            return json.dumps(data, ensure_ascii=False, indent=2)
            
        except Exception as e:
            self.logger.error(f"解析JSON响应失败: {e}")
            return json.dumps(data, ensure_ascii=False, indent=2)

    async def _fetch_media_from_api(self, api_url: str):
        """从API获取媒体链接，返回媒体链列表，处理所有有效链接"""
        if not self.is_enabled:
            return []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, allow_redirects=True) as response:
                    if response.status != 200:
                        return []
                    content_type = response.headers.get('Content-Type', '').lower()
                    file_urls = []
                    if 'json' in content_type:
                        content = await response.json()
                        if isinstance(content, list):
                            file_urls = [item.get('url', '') for item in content if 'url' in item]
                        elif isinstance(content, dict):
                            url = content.get('url', '')
                            if url:
                                file_urls = [url]
                            else:
                                file_urls = [content.get('data', {}).get('url', '')]
                    else:
                        content = await response.text(encoding='utf-8', errors='ignore')
                        lines = content.splitlines()
                        if len(lines) > 1:
                            file_urls = [line.strip() for line in lines if line.strip().startswith(('http://', 'https://'))]
                        else:
                            file_urls = [content.strip()]

                    media_chains = []
                    for file_url in file_urls:
                        if not file_url.startswith(('http://', 'https://')):
                            continue
                        async with session.get(file_url, allow_redirects=True) as final_response:
                            if final_response.status != 200:
                                continue
                            content_type = final_response.headers.get('Content-Type', '').lower()
                            media_chain = self._determine_media_type(file_url, content_type)
                            media_chains.append(media_chain)
                    return media_chains
        except Exception as e:
            self.logger.error(f"从API获取媒体失败: {str(e)}")
            return []

    async def _fetch_media_from_direct_url(self, url: str):
        """从直接URL获取媒体，返回媒体链"""
        if not self.is_enabled:
            return []

        try:
            url = await self.get_latest_url(url)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        return []
                    content_type = response.headers.get('Content-Type', '').lower()
                    return self._determine_media_type(url, content_type)
        except Exception as e:
            self.logger.error(f"从直接URL获取媒体失败: {str(e)}")
            return []

    def _determine_media_type(self, url: str, content_type: str):
        """根据内容类型或文件扩展名判断媒体类型"""
        if 'video' in content_type:
            return [Video(file=url)]
        elif 'image' in content_type:
            return [Image(file=url)]
        else:
            file_extension = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
            if not file_extension:
                guessed_type, _ = mimetypes.guess_type(url)
                if guessed_type:
                    if 'video' in guessed_type:
                        return [Video(file=url)]
                    elif 'image' in guessed_type:
                        return [Image(file=url)]
            if file_extension in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
                return [Video(file=url)]
            return [Image(file=url)]
