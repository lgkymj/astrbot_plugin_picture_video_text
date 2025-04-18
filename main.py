import json
import os
import aiohttp
import asyncio
import mimetypes
import re
import random
from pathlib import Path
from typing import Optional, Dict, List
import urllib.parse
import logging

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image, Video, Node, Nodes
from astrbot.api import AstrBotConfig

DATA_FILE = Path(__file__).parent / "api_config.json"

@register("astrbot_plugin_picture_manager", "大沙北",
          "API图片/视频发送插件，允许用户通过自定义触发指令从API或直接URL获取图片或视频，支持多链接转发和随机API调用",
          "v1.8.0")
class PictureManagerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.api_list: Dict[str, List[str]] = {}  # 触发指令映射到API地址列表
        self.direct_url_list: Dict[str, List[str]] = {}  # 触发指令映射到直接图片/视频URL列表
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
        self.logger.info("图片/视频发送插件初始化完成")

    def load_api_config(self):
        """加载API配置文件"""
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.api_list = {k: v if isinstance(v, list) else [v] for k, v in data.get('api_list', {}).items()}
                    self.direct_url_list = {k: v if isinstance(v, list) else [v] for k, v in data.get('direct_url_list', {}).items()}
            except json.JSONDecodeError as e:
                self.logger.error(f"加载配置文件失败，格式错误: {e}")
                self.api_list = {}
                self.direct_url_list = {}
        else:
            self.api_list = {}
            self.direct_url_list = {}

    def save_api_config(self):
        """保存API配置文件"""
        data = {
            'api_list': self.api_list.copy(),
            'direct_url_list': self.direct_url_list.copy()
        }
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            self.logger.error(f"保存配置文件失败: {e}")

    @filter.command("开启看图")
    async def enable_picture(self, event: AstrMessageEvent):
        """开启发图功能"""
        self.is_enabled = True
        yield event.plain_result("发图/发视频功能已开启")

    @filter.command("关闭看图")
    async def disable_picture(self, event: AstrMessageEvent):
        """关闭发图功能"""
        self.is_enabled = False
        yield event.plain_result("发图/发视频功能已关闭")

    @filter.command("看图列表")
    async def list_apis(self, event: AstrMessageEvent):
        """显示所有可用的API和直接URL"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if not self.api_list and not self.direct_url_list:
            yield event.plain_result("暂无可用的API或直接图片/视频URL")
            return

        msg = "可用API列表:\n"
        for trigger, urls in self.api_list.items():
            msg += f"触发指令: {trigger}\n对应地址: {', '.join(urls)}\n"
        
        msg += "\n可用直接图片/视频URL列表:\n"
        for trigger, urls in self.direct_url_list.items():
            msg += f"触发指令: {trigger}\n基础地址: {', '.join(urls)}\n"
        
        yield event.plain_result(msg)

    @filter.command("增加看图")
    async def add_api_or_url(self, event: AstrMessageEvent, trigger: str, url: str):
        """增加新的API或直接图片/视频URL"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()  # 统一转换为小写以避免大小写冲突
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
                        else:
                            if trigger in self.api_list:
                                self.api_list[trigger].append(url)
                            else:
                                self.api_list[trigger] = [url]
                            self.save_api_config()
                            yield event.plain_result(f"成功添加API - 触发指令: {trigger}, 地址: {url}")
                    else:
                        if trigger in self.api_list:
                            self.api_list[trigger].append(url)
                        else:
                            self.api_list[trigger] = [url]
                        self.save_api_config()
                        yield event.plain_result(f"成功添加API - 触发指令: {trigger}, 地址: {url}")
        except aiohttp.ClientError as e:
            yield event.plain_result(f"添加失败，网络错误: {str(e)}")
        except Exception as e:
            yield event.plain_result(f"添加失败，发生错误: {str(e)}")

    @filter.command("修改看图地址")
    async def modify_api_address(self, event: AstrMessageEvent, trigger: str, index: int, new_url: str):
        """修改API或直接图片/视频URL地址，index从1开始"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        if trigger in self.api_list:
            if 1 <= index <= len(self.api_list[trigger]):
                self.api_list[trigger][index - 1] = new_url
                self.save_api_config()
                yield event.plain_result(f"成功修改触发指令 {trigger} 的第 {index} 个地址为 {new_url}")
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
        elif trigger in self.direct_url_list:
            if 1 <= index <= len(self.direct_url_list[trigger]):
                self.direct_url_list[trigger][index - 1] = new_url
                self.save_api_config()
                yield event.plain_result(f"成功修改触发指令 {trigger} 的第 {index} 个地址为 {new_url}")
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
        else:
            yield event.plain_result("触发指令不存在")

    @filter.command("删除看图")
    async def delete_api(self, event: AstrMessageEvent, trigger: str, index: Optional[int] = None):
        """删除API或直接图片/视频URL，index不填则删除整个触发指令"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        trigger = trigger.lower()
        if trigger in self.api_list:
            if index is None:
                del self.api_list[trigger]
            elif 1 <= index <= len(self.api_list[trigger]):
                self.api_list[trigger].pop(index - 1)
                if not self.api_list[trigger]:
                    del self.api_list[trigger]
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        elif trigger in self.direct_url_list:
            if index is None:
                del self.direct_url_list[trigger]
            elif 1 <= index <= len(self.direct_url_list[trigger]):
                self.direct_url_list[trigger].pop(index - 1)
                if not self.direct_url_list[trigger]:
                    del self.direct_url_list[trigger]
            else:
                yield event.plain_result(f"索引 {index} 超出范围")
                return
        else:
            yield event.plain_result("触发指令不存在")
            return

        self.save_api_config()
        yield event.plain_result(f"成功删除触发指令 {trigger} 的相关地址")

    @filter.command("随机看图")
    async def random_picture(self, event: AstrMessageEvent):
        """随机发送一张图片或一段视频"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if not self.api_list and not self.direct_url_list:
            yield event.plain_result("暂无可用的API或直接图片/视频URL")
            return

        all_triggers = list(self.api_list.keys()) + list(self.direct_url_list.keys())
        trigger = random.choice(all_triggers)
        
        if trigger in self.api_list:
            api_urls = self.api_list[trigger]
            api_url = random.choice(api_urls)  # 随机选择一个API
            async for result in self.send_picture(event, api_url):
                yield result
        else:
            urls = self.direct_url_list[trigger]
            url = random.choice(urls)  # 随机选择一个URL
            async for result in self.send_direct_image(event, url):
                yield result

    @filter.command("看图帮助")
    async def picture_help(self, event: AstrMessageEvent):
        """显示插件的使用帮助"""
        help_msg = """
发图/发视频插件使用帮助:

1. /开启看图 - 开启发图/发视频功能，使插件能够响应图片/视频发送请求。
   - 使用示例: /开启看图

2. /关闭看图 - 关闭发图/发视频功能，插件将不会再发送图片/视频。
   - 使用示例: /关闭看图

3. /看图列表 - 查看所有可用的API和直接图片/视频URL列表。
   - 使用示例: /看图列表

4. /增加看图 [触发指令] [地址] - 增加新的API或直接图片/视频URL。
   - 使用示例: /增加看图 cute_cat 图片/视频URL或API地址
   - 注意: 如果地址直接指向图片/视频，将被视为直接图片/视频URL；否则视为API。

5. /修改看图地址 [触发指令] [索引] [新地址] - 修改已存在的API或图片/视频URL地址，索引从1开始。
   - 使用示例: /修改看图地址 cute_cat 1 新图片/视频URL或API地址

6. /删除看图 [触发指令] [索引] - 删除指定的API或直接图片/视频URL，索引不填则删除整个触发指令。
   - 使用示例: /删除看图 cute_cat 1 或 /删除看图 cute_cat

7. /随机看图 - 从所有已添加的API或直接图片/视频URL中随机选择一个发送图片/视频。
   - 使用示例: /随机看图

8. /看图 [触发指令] [数量] - 指定触发指令获取指定数量的图片/视频，数量不填默认为配置值，数量>2时使用转发。
   - 使用示例: /看图 cute_cat 3

9. [触发指令] - 直接使用已添加的触发指令来发送图片或视频。
   - 使用示例: 如果您添加了cute_cat作为触发指令，发送cute_cat即可获取图片/视频。

注意事项:
- 确保发图/发视频功能已开启才能使用图片/视频发送功能。
- 每个触发指令可以对应多个地址，调用时随机选择一个。
- 直接图片/视频URL的地址必须是有效的图片/视频链接。
- API地址应返回有效的图片/视频URL或直接图片/视频内容。
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
            api_url = random.choice(api_urls)  # 随机选择一个API
            async for result in self.send_picture(event, api_url):
                yield result
        elif trigger in self.direct_url_list:
            urls = self.direct_url_list[trigger]
            url = random.choice(urls)  # 随机选择一个URL
            async for result in self.send_direct_image(event, url):
                yield result
        else:
            yield event.plain_result(f"触发指令 '{trigger}' 不存在")

    @filter.command("看图")
    async def view_picture(self, event: AstrMessageEvent, trigger: Optional[str] = None, count: Optional[int] = None):
        """指定触发指令获取指定数量的图片/视频，count不填则使用配置的默认值，count>2时使用转发"""
        if not self.is_enabled:
            yield event.plain_result("插件功能已关闭，请先使用 /开启看图 启用")
            return

        if trigger is None:
            return  # 只发送"看图"不处理

        trigger = trigger.lower()
        if trigger not in self.api_list and trigger not in self.direct_url_list:
            yield event.plain_result(f"触发指令 '{trigger}' 不存在")
            return

        # 如果未指定count，则使用配置中的默认值
        count = max(1, count if count is not None else self.default_view_count)
        media_chains = []
        
        if trigger in self.api_list:
            for _ in range(count):
                api_urls = self.api_list[trigger]
                api_url = random.choice(api_urls)  # 随机选择一个API
                media_chain_list = await self._fetch_media_from_api(api_url)
                if media_chain_list:
                    media_chains.extend(media_chain_list)  # 可能返回多个
        else:
            for _ in range(count):
                urls = self.direct_url_list[trigger]
                url = random.choice(urls)  # 随机选择一个URL
                media_chain = await self._fetch_media_from_direct_url(url)
                if media_chain:
                    media_chains.append(media_chain)

        if not media_chains:
            yield event.plain_result("未能获取任何图片/视频")
            return

        if count > 2 or len(media_chains) > 2:
            # 使用转发消息发送
            nodes_list = []
            for i, chain in enumerate(media_chains[:max(count, len(media_chains))], 1):
                media_type = "图片" if isinstance(chain[0], Image) else "视频"
                node = Node(
                    uin=0,  # 使用0或其他固定值，具体值根据平台适配
                    name=f"{self.bot_id} - {media_type}{i}",
                    content=chain  # 内容部分只包含媒体，不加额外文字
                )
                nodes_list.append(node)
            yield event.chain_result([Nodes(nodes=nodes_list)])
        else:
            # 单个或两个直接发送
            for chain in media_chains[:count]:
                yield event.chain_result(chain)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息，检查是否为用户定义的触发指令"""
        if not self.is_enabled:
            return

        message_str = event.message_str.lower()
        for trigger in self.api_list.keys():
            if re.match(f"^{re.escape(trigger)}$", message_str):
                api_urls = self.api_list[trigger]
                api_url = random.choice(api_urls)  # 随机选择一个API
                async for result in self.send_picture(event, api_url):
                    yield result
                event.stop_event()
                return

        for trigger in self.direct_url_list.keys():
            if re.match(f"^{re.escape(trigger)}$", message_str):
                urls = self.direct_url_list[trigger]
                url = random.choice(urls)  # 随机选择一个URL
                async for result in self.send_direct_image(event, url):
                    yield result
                event.stop_event()
                return

        if re.match("^随机看图$", message_str):
            async for result in self.random_picture(event):
                yield result
            event.stop_event()

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
                    for file_url in file_urls:  # 处理所有有效链接
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
                        # 使用转发消息发送
                        nodes_list = []
                        for i, chain in enumerate(media_chains, 1):
                            media_type = "图片" if isinstance(chain[0], Image) else "视频"
                            node = Node(
                                uin=0,  # 使用0或其他固定值，具体值根据平台适配
                                name=f"{self.bot_id} - {media_type}{i}",
                                content=chain  # 内容部分只包含媒体，不加额外文字
                            )
                            nodes_list.append(node)
                        yield event.chain_result([Nodes(nodes=nodes_list)])
                    else:
                        # 单个或两个直接发送
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
                    for file_url in file_urls:  # 处理所有有效链接
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
