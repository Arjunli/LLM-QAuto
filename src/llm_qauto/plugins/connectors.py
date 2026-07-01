"""
连接器插件 - 支持不同协议的被测对象
"""

import json
import logging
import asyncio
from typing import Any, Dict, List, Optional
from abc import abstractmethod
import aiohttp
import httpx
from jinja2 import Template

from . import Plugin, register_plugin


logger = logging.getLogger(__name__)


def _parser_cfg(parser_config: Any) -> Dict[str, Any]:
    """支持 Pydantic 模型与普通 dict"""
    if hasattr(parser_config, "model_dump"):
        return parser_config.model_dump()
    if isinstance(parser_config, dict):
        return parser_config
    return {
        "path": getattr(parser_config, "path", None),
        "keys": getattr(parser_config, "keys", None),
        "name": getattr(parser_config, "name", "json_extractor"),
    }


def _traverse_dotted(start: Any, path: Optional[str]) -> Any:
    if not path or not str(path).strip():
        return start
    cur = start
    for raw in str(path).split("."):
        key = raw.strip()
        if not key:
            continue
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)]
        else:
            return None
    return cur


def _apply_keys_filter(node: Any, keys: Optional[List[str]]) -> Any:
    """从对象中取白名单字段；缺的键值为 null"""
    if not keys:
        return node
    want = [k for k in keys if isinstance(k, str) and k.strip()]
    if not want:
        return node
    if isinstance(node, dict):
        return {k: node.get(k) for k in want}
    return {k: None for k in want}


def _stringify_extractor_result(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, (dict, list)):
        return json.dumps(node, ensure_ascii=False, default=str)
    return str(node)


class BaseConnector(Plugin):
    """连接器基类"""
    
    @abstractmethod
    async def call(self, formatted_input: Dict) -> Dict:
        """调用被测对象"""
        pass
    
    @abstractmethod
    def format_input(
        self, 
        test_input, 
        formatter_config
    ) -> Dict:
        """格式化输入"""
        pass
    
    @abstractmethod
    def parse_output(
        self, 
        response: Dict, 
        parser_config
    ) -> str:
        """解析输出"""
        pass
    
    async def call_batch(self, formatted_inputs: List[Dict]) -> List[Dict]:
        """批量调用（默认顺序执行）"""
        results = []
        for inp in formatted_inputs:
            result = await self.call(inp)
            results.append(result)
        return results


@register_plugin("connector", "http_json")
class HTTPJSONConnector(BaseConnector):
    """HTTP JSON API连接器"""
    
    @property
    def name(self) -> str:
        return "http_json"
    
    async def initialize(self, config: Dict[str, Any]):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.timeout = aiohttp.ClientTimeout(total=config.get("timeout", 30))
        self.retry_count = config.get("retry", 3)
    
    async def cleanup(self):
        if self.session:
            await self.session.close()
    
    def format_input(self, test_input, formatter_config) -> Dict:
        """格式化输入"""
        template_str = formatter_config.template
        
        if isinstance(template_str, str):
            # Jinja2模板
            template = Template(template_str)
            variables = {
                "input": test_input,
                "config": formatter_config.config if hasattr(formatter_config, 'config') else {}
            }
            rendered = template.render(**variables)
            return json.loads(rendered)
        else:
            # 直接是字典
            template = Template(json.dumps(template_str))
            variables = {
                "input": test_input,
                "config": formatter_config.config if hasattr(formatter_config, 'config') else {}
            }
            rendered = template.render(**variables)
            return json.loads(rendered)
    
    def parse_output(self, response: Dict, parser_config) -> str:
        """解析输出"""
        cfg = _parser_cfg(parser_config)
        path = (cfg.get("path") or "").strip()
        keys = cfg.get("keys")

        root = response
        # 配置了 keys、且未写 path：优先从顶层 data 中取（与 httpx 返回结构一致）
        if keys and not path:
            inner = root.get("data", root)
        else:
            inner = root
        current = _traverse_dotted(inner, path) if path else inner
        current = _apply_keys_filter(current, keys)
        return _stringify_extractor_result(current)
    
    async def call(self, formatted_input: Dict) -> Dict:
        """调用API"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        url = self.config.get("endpoint")
        method = self.config.get("method", "POST").upper()
        headers = self.config.get("headers", {})
        
        start_time = asyncio.get_event_loop().time()
        
        for attempt in range(self.retry_count):
            try:
                async with self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=formatted_input,
                    timeout=self.timeout
                ) as response:
                    response_data = await response.json()
                    latency = (asyncio.get_event_loop().time() - start_time) * 1000
                    
                    return {
                        "status": response.status,
                        "data": response_data,
                        "latency_ms": latency,
                        "error": None
                    }
            except Exception as e:
                if attempt == self.retry_count - 1:
                    return {
                        "status": 500,
                        "data": None,
                        "latency_ms": (asyncio.get_event_loop().time() - start_time) * 1000,
                        "error": str(e)
                    }
                await asyncio.sleep(0.5 * (attempt + 1))  # 指数退避


@register_plugin("connector", "httpx")
class HTTPXConnector(BaseConnector):
    """使用httpx的同步/异步连接器（更好的性能）"""
    
    @property
    def name(self) -> str:
        return "httpx"
    
    async def initialize(self, config: Dict[str, Any]):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
        self.timeout = httpx.Timeout(config.get("timeout", 30))
        self.retry_count = config.get("retry", 3)
    
    async def cleanup(self):
        if self.client:
            await self.client.aclose()
    
    def format_input(self, test_input, formatter_config) -> Dict:
        template_str = formatter_config.template
        
        if isinstance(template_str, str):
            template = Template(template_str)
            variables = {"input": test_input}
            rendered = template.render(**variables)
            return json.loads(rendered) if rendered.strip().startswith("{") else {"content": rendered}
        else:
            template = Template(json.dumps(template_str))
            variables = {"input": test_input}
            rendered = template.render(**variables)
            return json.loads(rendered)
    
    def parse_output(self, response: Dict, parser_config) -> str:
        cfg = _parser_cfg(parser_config)
        path = (cfg.get("path") or "").strip()
        keys = cfg.get("keys")

        inner = response.get("data")
        current = _traverse_dotted(inner, path) if path else inner
        current = _apply_keys_filter(current, keys)
        return _stringify_extractor_result(current)
    
    async def call(self, formatted_input: Dict) -> Dict:
        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)
        
        url = self.config.get("endpoint")
        method = (self.config.get("method") or "POST").strip().upper()
        headers = self.config.get("headers", {})

        if method in ("OPTIONS", "HEAD", "TRACE"):
            msg = (
                f"连接器不支持将 HTTP 方法设为 {method}（常见于 CORS 预检/仅头信息）。"
                "请改为 GET 或 POST；拉取类接口请使用 method: GET。"
            )
            logger.warning("[httpx] %s endpoint=%s", msg, url)
            return {
                "status": 400,
                "data": None,
                "latency_ms": 0.0,
                "error": msg,
            }
        
        start_time = asyncio.get_event_loop().time()
        
        for attempt in range(self.retry_count):
            try:
                if method == "GET":
                    response = await self.client.get(url, headers=headers, params=formatted_input)
                else:
                    response = await self.client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=formatted_input
                    )

                latency = (asyncio.get_event_loop().time() - start_time) * 1000
                body_text = response.text or ""
                preview_len = 500

                if response.status_code >= 300:
                    logger.warning(
                        "[httpx] HTTP 非成功 status=%s method=%s endpoint=%s attempt=%s/%s preview=%r",
                        response.status_code,
                        method,
                        url,
                        attempt + 1,
                        self.retry_count,
                        body_text[:preview_len],
                    )
                    return {
                        "status": response.status_code,
                        "data": None,
                        "latency_ms": latency,
                        "error": f"HTTP {response.status_code}: {body_text[:preview_len]}",
                    }

                if not body_text.strip():
                    req_m = getattr(response.request, "method", "?") if response.request else "?"
                    logger.warning(
                        "[httpx] 响应正文为空 config_method=%s actual_request=%s url=%s "
                        "content_length=%s attempt=%s/%s",
                        method,
                        req_m,
                        str(response.url),
                        response.headers.get("content-length"),
                        attempt + 1,
                        self.retry_count,
                    )
                    return {
                        "status": response.status_code,
                        "data": None,
                        "latency_ms": latency,
                        "error": "HTTP 成功但响应正文为空，无法按 JSON 解析",
                    }

                try:
                    response_data = json.loads(body_text)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[httpx] JSON 解析失败 method=%s endpoint=%s err=%s preview=%r",
                        method,
                        url,
                        exc,
                        body_text[:preview_len],
                    )
                    return {
                        "status": response.status_code,
                        "data": None,
                        "latency_ms": latency,
                        "error": (
                            f"响应正文不是合法 JSON ({exc}); HTTP {response.status_code}; "
                            f"正文预览: {body_text[:preview_len]!r}"
                        ),
                    }

                return {
                    "status": response.status_code,
                    "data": response_data,
                    "latency_ms": latency,
                    "error": None,
                }
            except Exception as e:
                if attempt == self.retry_count - 1:
                    logger.warning(
                        "[httpx] 调用异常 method=%s endpoint=%s err=%s attempt=%s/%s",
                        method,
                        url,
                        e,
                        attempt + 1,
                        self.retry_count,
                    )
                    return {
                        "status": 500,
                        "data": None,
                        "latency_ms": (asyncio.get_event_loop().time() - start_time) * 1000,
                        "error": str(e)
                    }
                await asyncio.sleep(0.5 * (attempt + 1))
    
    async def call_batch(self, formatted_inputs: List[Dict]) -> List[Dict]:
        """并发批量调用"""
        if not self.client:
            self.client = httpx.AsyncClient(timeout=self.timeout)
        
        concurrency = self.config.get("concurrency", 5)
        semaphore = asyncio.Semaphore(concurrency)
        url = self.config.get("endpoint")

        logger.info(
            "[httpx] 批量调用 n=%d concurrency=%d endpoint=%s",
            len(formatted_inputs),
            concurrency,
            url,
        )
        
        async def call_with_limit(inp):
            async with semaphore:
                return await self.call(inp)
        
        results = await asyncio.gather(*[call_with_limit(inp) for inp in formatted_inputs])
        err_n = sum(1 for r in results if r.get("error"))
        if err_n:
            logger.warning(
                "[httpx] 批量调用完成 errors=%d/%d endpoint=%s",
                err_n,
                len(results),
                url,
            )
        return results


@register_plugin("connector", "local_model")
class LocalModelConnector(BaseConnector):
    """本地模型连接器（用于测试本地部署的模型）"""
    
    @property
    def name(self) -> str:
        return "local_model"
    
    async def initialize(self, config: Dict[str, Any]):
        self.config = config
        self.model_path = config.get("model_path")
        self.device = config.get("device", "cpu")
        self.batch_size = config.get("batch_size", 1)
        # 这里可以加载本地模型
        self.model = None
        self.tokenizer = None
    
    async def cleanup(self):
        if self.model:
            del self.model
    
    def format_input(self, test_input, formatter_config) -> Dict:
        """格式化为本地模型输入"""
        return {
            "prompt": test_input.prompt,
            "max_tokens": formatter_config.config.get("max_tokens", 512),
            "temperature": formatter_config.config.get("temperature", 0.7)
        }
    
    def parse_output(self, response: Dict, parser_config) -> str:
        """解析本地模型输出"""
        return response.get("generated_text", "")
    
    async def call(self, formatted_input: Dict) -> Dict:
        """调用本地模型"""
        # 这里需要根据实际情况实现
        # 如果是transformers模型，需要在这里调用generate
        start_time = asyncio.get_event_loop().time()
        
        # 模拟调用
        await asyncio.sleep(0.1)
        
        return {
            "status": 200,
            "data": {"generated_text": "本地模型输出示例"},
            "latency_ms": 100,
            "error": None
        }
