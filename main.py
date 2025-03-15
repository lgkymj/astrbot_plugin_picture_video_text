import json
import os
import aiohttp
import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Optional, Dict, Callable
import urllib.parse

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image, Video, File

DATA_FILE = Path(__file__).parent / "api_config.json"
@register("astrbot_plugin_picture_manager", "大沙北",
          "API图片发送插件，允许用户通过自定义触发指令从API或直接URL获取图片，内置了一些测试用的图片URL（添加后即可使用）",
          "v1.8.0")
class PictureManagerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.api_list: Dict[str, str] = {}  # 用于存储API地址的触发指令
        self.direct_url_list: Dict[str, Callable[[], str]] = {}  # 用于存储直接图片URL的触发指令，存储的是获取URL的函数
        self.is_enabled: bool = True  # 是否启用发图功能
        self.load_api_config()  # 加载存储的API配置

    def load_api_config(self):
        """加载API配置文件"""
        if DATA_FILE.exists():
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.api_list = data.get('api_list', {})
                # 这里我们需要特别处理，因为存储的是函数
                self.direct_url_list = {}
                for trigger, url_func in data.get('direct_url_list', {}).items():
                    # 这里假设存储的是一个字符串，我们需要将其转换为函数
                    self.direct_url_list[trigger] = lambda base_url=url_func: base_url
        else:
            self.api_list = {}
            self.direct_url_list = {}

    def save_api_config(self):
        """保存API配置文件"""
        data = {
            'api_list': self.api_list.copy(),
            'direct_url_list': {k: v() for k, v in self.direct_url_list.items()}  # 保存时调用函数获取最新的URL
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @filter.command("开启看图")
    async def enable_picture(self, event: AstrMessageEvent):
        """开启发图功能"""
        self.is_enabled = True
        yield event.plain_result("发图功能已开启")

    @filter.command("关闭看图")
    async def disable_picture(self, event: AstrMessageEvent):
        """关闭发图功能"""
        self.is_enabled = False
        yield event.plain_result("发图功能已关闭")

    @filter.command("看图列表")
    async def list_apis(self, event: AstrMessageEvent):
        """显示所有可用的API和直接URL"""
        if not self.api_list and not self.direct_url_list:
            yield event.plain_result("暂无可用的API或直接图片URL")
            return

        msg = "可用API列表:\n"
        for trigger, url in self.api_list.items():
            msg += f"触发指令: {trigger}\n对应地址: {url}\n"
        
        msg += "\n可用直接图片URL列表:\n"
        for trigger, url_func in self.direct_url_list.items():
            msg += f"触发指令: {trigger}\n基础地址: {url_func()}\n"
        
        yield event.plain_result(msg)

    @filter.command("增加看图")
    async def add_api_or_url(self, event: AstrMessageEvent, trigger: str, url: str):
        """增加新的API或直接图片URL"""
        if trigger in self.api_list or trigger in self.direct_url_list:
            yield event.plain_result("触发指令已存在，请更换触发指令")
            return

        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; AMOI N828 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 SogouMSE/1.2.1'
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status == 200:
                        content_type = response.headers.get('Content-Type', '').lower()
                        if content_type.startswith('image/'):
                            # 存储一个函数，每次调用时获取最新的图片URL
                            self.direct_url_list[trigger] = lambda: url
                            self.save_api_config()
                            yield event.plain_result(f"成功添加直接图片URL - 触发指令: {trigger}, 基础地址: {url}")
                        else:
                            self.api_list[trigger] = url
                            self.save_api_config()
                            yield event.plain_result(f"成功添加API - 触发指令: {trigger}, 地址: {url}")
                    else:
                        self.api_list[trigger] = url
                        self.save_api_config()
                        yield event.plain_result(f"成功添加API - 触发指令: {trigger}, 地址: {url}")
        except Exception as e:
            yield event.plain_result(f"添加失败，发生错误: {str(e)}")

    @filter.command("修改看图地址")
    async def modify_api_address(self, event: AstrMessageEvent, trigger: str, new_url: str):
        """修改API或直接图片URL地址"""
        if trigger in self.api_list:
            self.api_list[trigger] = new_url
        elif trigger in self.direct_url_list:
            self.direct_url_list[trigger] = lambda: new_url
        else:
            yield event.plain_result("触发指令不存在")
            return

        self.save_api_config()
        yield event.plain_result(f"成功修改触发指令 {trigger} 的地址为 {new_url}")

    @filter.command("删除看图")
    async def delete_api(self, event: AstrMessageEvent, trigger: str):
        """删除API或直接图片URL"""
        if trigger in self.api_list:
            del self.api_list[trigger]
        elif trigger in self.direct_url_list:
            del self.direct_url_list[trigger]
        else:
            yield event.plain_result("触发指令不存在")
            return

        self.save_api_config()
        yield event.plain_result(f"成功删除触发指令 {trigger}")

    @filter.command("随机看图")
    async def random_picture(self, event: AstrMessageEvent):
        """随机发送一张图片或动图"""
        if not self.is_enabled:
            yield event.plain_result("发图功能已关闭")
            return

        if not self.api_list and not self.direct_url_list:
            yield event.plain_result("暂无可用的API或直接图片URL")
            return

        # 随机选择一个触发指令
        all_triggers = list(self.api_list.keys()) + list(self.direct_url_list.keys())
        import random
        trigger = random.choice(all_triggers)
        
        if trigger in self.api_list:
            api_url = self.api_list[trigger]
            async for result in self.send_picture(event, api_url):
                yield result
        else:
            async for result in self.send_direct_image(event, trigger):
                yield result

    @filter.command("看图帮助")
    async def picture_help(self, event: AstrMessageEvent):
        """显示插件的使用帮助"""
        help_msg = """
发图插件使用帮助:

1. /开启看图 - 开启发图功能，使插件能够响应图片发送请求。
   - 使用示例: /开启看图

2. /关闭看图 - 关闭发图功能，插件将不会再发送图片。
   - 使用示例: /关闭看图

3. /看图列表 - 查看所有可用的API和直接图片URL列表。
   - 使用示例: /看图列表

4. /增加看图 [触发指令] [地址] - 增加新的API或直接图片URL。
   - 使用示例: /增加看图 cute_cat 图片URL或API地址
   - 注意: 如果地址直接指向图片，将被视为直接图片URL；否则视为API。

5. /修改看图地址 [触发指令] [新地址] - 修改已存在的API或图片URL地址。
   - 使用示例: /修改看图地址 cute_cat 新图片URL或API地址

6. /删除看图 [触发指令] - 删除指定的API或直接图片URL。
   - 使用示例: /删除看图 cute_cat

7. /随机看图 - 从所有已添加的API或直接图片URL中随机选择一个发送图片。
   - 使用示例: /随机看图

8. [触发指令] - 直接使用已添加的触发指令来发送图片或动图。
   - 使用示例: 如果您添加了cute_cat作为触发指令，发送cute_cat即可获取图片。

注意事项:
- 确保发图功能已开启才能使用图片发送功能。
- 每个触发指令必须唯一，添加新指令前请先检查是否已存在。
- 直接图片URL的地址必须是有效的图片链接。
- API地址应返回有效的图片URL或直接图片内容。
"""
        yield event.plain_result(help_msg)

    @filter.command("图片")
    async def picture(self, event: AstrMessageEvent, trigger: Optional[str] = None):
        """通过触发指令发送图片或动图"""
        if not self.is_enabled:
            yield event.plain_result("发图功能已关闭")
            return

        if trigger is None:
            yield event.plain_result("请指定触发指令")
            return

        if trigger in self.api_list:
            api_url = self.api_list[trigger]
            async for result in self.send_picture(event, api_url):
                yield result
        elif trigger in self.direct_url_list:
            async for result in self.send_direct_image(event, trigger):
                yield result
        else:
            yield event.plain_result(f"触发指令 '{trigger}' 不存在")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息，检查是否为用户定义的触发指令"""
        if not self.is_enabled:
            return

        # 检查消息是否为用户定义的触发指令
        for trigger in self.api_list.keys():
            if re.match(f"^{trigger}$", event.message_str):
                api_url = self.api_list[trigger]
                async for result in self.send_picture(event, api_url):
                    yield result
                return

        for trigger in self.direct_url_list.keys():
            if re.match(f"^{trigger}$", event.message_str):
                async for result in self.send_direct_image(event, trigger):
                    yield result
                return

        # 检查是否为随机看图命令
        if re.match("^随机看图$", event.message_str):
            async for result in self.random_picture(event):
                yield result

    async def send_picture(self, event: AstrMessageEvent, api_url: str):
        """发送图片或动图"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; AMOI N828 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 SogouMSE/1.2.1'
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                # 访问API获取文件URL
                async with session.get(api_url, allow_redirects=True) as response:
                    if response.status != 200:
                        yield event.plain_result(f"访问API失败: {api_url}")
                        return

                    content = await response.text(encoding='utf-8', errors='ignore')
                    if not content:
                        yield event.plain_result(f"API返回空内容: {api_url}")
                        return

                    file_url = content.strip()
                    if not file_url.startswith(('http://', 'https://')):
                        yield event.plain_result(f"API返回无效的URL: {file_url}")
                        return

                    # 直接发送URL
                    yield event.image_result(file_url)

        except Exception as e:
            yield event.plain_result(f"发生错误: {str(e)}")

    async def get_latest_url(self, base_url: str) -> str:
        """获取最新的图片URL"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; U; Android 4.2.1; zh-cn; AMOI N828 Build/JOP40D) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30 SogouMSE/1.2.1'
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(base_url, allow_redirects=True) as response:
                if response.status == 200:
                    return str(response.url)
                else:
                    raise Exception(f"获取图片URL失败，状态码: {response.status}")

    async def send_direct_image(self, event: AstrMessageEvent, trigger: str):
        """发送直接图片URL，处理重定向"""
        try:
            if trigger in self.direct_url_list:
                base_url = self.direct_url_list[trigger]()
                url = await self.get_latest_url(base_url)
                yield event.image_result(url)
            else:
                yield event.plain_result(f"触发指令 '{trigger}' 不存在")
        except Exception as e:
            yield event.plain_result(f"发送图片失败: {str(e)}")
