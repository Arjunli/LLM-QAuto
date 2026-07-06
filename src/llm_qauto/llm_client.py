"""
LLM客户端 - 支持多种LLM API (OpenAI, 火山引擎/Doubao, 阿里云, 百度云VOD/Gemini 等)
"""

import os
import json
import asyncio
import logging
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx

from .media import encode_image_for_vision_api, encode_image_for_gemini_api
from .media import encode_data_url_for_vision_api, encode_data_url_for_gemini_api


logger = logging.getLogger(__name__)


def _default_llm_timeout_sec() -> float:
    try:
        return float(os.environ.get("QAUTO_LLM_TIMEOUT_SEC", "180"))
    except ValueError:
        return 180.0


def _bce_auth_v1_headers(
    method: str,
    path: str,
    access_key_id: str,
    secret_access_key: str,
    host: str = "vod.bj.baidubce.com",
    expiration_seconds: int = 1800,
) -> Dict[str, str]:
    """百度云 BCE Auth V1 签名（AK/SK），用于 v2/chat/gc 等接口。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    request_id = str(uuid.uuid4())
    signed_headers = "host;x-bce-date"
    canonical_uri = path
    canonical_headers = (
        f"host:{host}\n"
        f"x-bce-date:{timestamp}\n"
    )
    canonical_request = f"{method.upper()}\n{canonical_uri}\n\n{canonical_headers}"
    auth_prefix = (
        f"bce-auth-v1/{access_key_id}/{timestamp}/{expiration_seconds}"
    )
    signing_key = hmac.new(
        secret_access_key.encode("utf-8"),
        auth_prefix.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    signature = hmac.new(
        signing_key.encode("utf-8"),
        canonical_request.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    authorization = f"{auth_prefix}/{signed_headers}/{signature}"
    return {
        "Host": host,
        "x-bce-request-id": request_id,
        "x-bce-date": timestamp,
        "authorization": authorization,
        "Content-Type": "application/json",
    }


def _normalize_baidu_bearer(api_key: str) -> str:
    """API Key 鉴权：官方推荐 Bearer bce-v3/...；已带前缀则原样使用。"""
    key = (api_key or "").strip()
    if key.lower().startswith("bearer "):
        return key
    return f"Bearer {key}"


@dataclass
class LLMResponse:
    """LLM响应"""

    content: str
    model: str
    usage: Dict[str, Any]
    latency_ms: float
    error: Optional[str] = None
    raw_response: Optional[Dict] = None


class LLMClient:
    """通用LLM客户端 - 支持多厂商API"""
    
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
        endpoint_id: Optional[str] = None
    ):
        # 自动检测提供商
        self.provider = provider or self._detect_provider()
        
        # 根据提供商设置参数
        if self.provider == "volcano":
            # 火山方舟：chat/completions 的 model 须为推理接入点 ID(ep-…) 或已开通的豆包等业务模型 ID；
            # YAML 评判器常写 gpt-4o-mini（OpenAI 名），不能直接用于方舟 → 退回环境变量默认模型。
            self.api_key = api_key or os.environ.get("ARK_API_KEY")
            self.base_url = base_url or os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
            self.endpoint_id = endpoint_id or os.environ.get("ARK_ENDPOINT_ID")
            env_model = os.environ.get("ARK_MODEL_ID", "doubao-seed-2.0-code")

            def _looks_like_non_ark_placeholder(name: Optional[str]) -> bool:
                if not name:
                    return False
                lower = name.lower()
                return (
                    lower.startswith("gpt-")
                    or lower.startswith("o1")
                    or lower.startswith("o3")
                    or lower.startswith("claude-")
                    or lower.startswith("gemini-")
                )

            if self.endpoint_id:
                self.model = self.endpoint_id
            elif model and not _looks_like_non_ark_placeholder(model):
                self.model = model
            elif model and _looks_like_non_ark_placeholder(model):
                self.model = env_model
            else:
                self.model = env_model

        elif self.provider == "openai":
            # OpenAI
            self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
            self.base_url = base_url or "https://api.openai.com/v1"
            self.endpoint_id = None
            
        elif self.provider == "aliyun":
            # 阿里云
            self.model = model or os.environ.get("ALIYUN_MODEL", "qwen-max")
            self.api_key = api_key or os.environ.get("ALIYUN_API_KEY")
            self.base_url = base_url or "https://dashscope.aliyuncs.com/api/v1"
            self.endpoint_id = None

        elif self.provider == "baidu_vod":
            # 百度云 VOD 多模态大模型（Gemini generateContent）
            # API Key: https://vod.bj.baidubce.com/v3/chat/gc
            # AK/SK:  https://vod.bj.baidubce.com/v2/chat/gc
            self.api_key = api_key or os.environ.get("BAIDU_VOD_API_KEY")
            self.access_key_id = os.environ.get("BAIDU_ACCESS_KEY_ID")
            self.secret_access_key = os.environ.get("BAIDU_SECRET_ACCESS_KEY")
            auth_mode = (os.environ.get("BAIDU_VOD_AUTH_MODE") or "").strip().lower()
            if auth_mode not in ("apikey", "aksk"):
                auth_mode = "apikey" if self.api_key else "aksk"
            self.baidu_auth_mode = auth_mode
            default_base = (
                "https://vod.bj.baidubce.com/v3/chat/gc"
                if auth_mode == "apikey"
                else "https://vod.bj.baidubce.com/v2/chat/gc"
            )
            self.base_url = (base_url or os.environ.get("BAIDU_VOD_BASE_URL") or default_base).rstrip("/")
            env_model = os.environ.get("BAIDU_VOD_MODEL", "G3FP")

            def _looks_like_placeholder(name: Optional[str]) -> bool:
                if not name:
                    return False
                lower = name.lower()
                return (
                    lower.startswith("gpt-")
                    or lower.startswith("o1")
                    or lower.startswith("o3")
                    or lower.startswith("claude-")
                    or lower.startswith("doubao")
                    or lower.startswith("qwen")
                )

            if model and not _looks_like_placeholder(model):
                self.model = model
            elif model and _looks_like_placeholder(model):
                self.model = env_model
            else:
                self.model = env_model
            self.endpoint_id = None
            if auth_mode == "apikey" and not self.api_key:
                raise ValueError(
                    "BAIDU_VOD_API_KEY is required for apikey auth. "
                    "See https://cloud.baidu.com/doc/VOD/s/Mmmleact0"
                )
            if auth_mode == "aksk" and (not self.access_key_id or not self.secret_access_key):
                raise ValueError(
                    "BAIDU_ACCESS_KEY_ID and BAIDU_SECRET_ACCESS_KEY are required for aksk auth."
                )
            
        else:
            # 默认使用OpenAI格式
            self.model = model or "gpt-4o-mini"
            self.api_key = api_key
            self.base_url = base_url or "https://api.openai.com/v1"
            self.endpoint_id = None
        
        if self.provider == "baidu_vod" and getattr(self, "baidu_auth_mode", "") == "aksk":
            pass
        elif not self.api_key:
            raise ValueError(
                f"API key is required for {self.provider}. "
                f"Set environment variable or pass api_key parameter."
            )
    
    def _detect_provider(self) -> str:
        """自动检测提供商"""
        explicit = (os.environ.get("LLM_PROVIDER") or "").strip().lower()
        if explicit in ("baidu_vod", "baidu", "baidu-vod"):
            return "baidu_vod"
        if explicit in ("volcano", "ark", "doubao"):
            return "volcano"
        if explicit in ("aliyun", "dashscope"):
            return "aliyun"
        if explicit in ("openai",):
            return "openai"

        if os.environ.get("BAIDU_VOD_API_KEY") or (
            os.environ.get("BAIDU_ACCESS_KEY_ID") and os.environ.get("BAIDU_SECRET_ACCESS_KEY")
        ):
            return "baidu_vod"
        if os.environ.get("ARK_API_KEY"):
            return "volcano"
        elif os.environ.get("ALIYUN_API_KEY"):
            return "aliyun"
        else:
            return "openai"
    
    async def call(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
        system_message: Optional[str] = None,
        response_format: Optional[Dict] = None,
        image_data_urls: Optional[List[str]] = None,
        timeout_sec: Optional[float] = None,
    ) -> LLMResponse:
        """
        调用LLM
        
        Args:
            prompt: 用户提示
            temperature: 温度参数
            max_tokens: 最大token数
            system_message: 系统消息
            response_format: 响应格式要求
            image_data_urls: 可选 data:image/...;base64,... 截图列表（多模态）
        
        Returns:
            LLMResponse
        """
        start_time = asyncio.get_event_loop().time()
        req_timeout = timeout_sec if timeout_sec is not None else _default_llm_timeout_sec()
        
        try:
            if image_data_urls:
                response = await self._call_multimodal_data_urls(
                    prompt,
                    image_data_urls,
                    temperature,
                    max_tokens,
                    system_message,
                    response_format,
                )
            elif self.provider == "volcano":
                response = await self._call_volcano(
                    prompt, temperature, max_tokens, system_message, response_format, req_timeout
                )
            elif self.provider == "openai":
                response = await self._call_openai(
                    prompt, temperature, max_tokens, system_message, response_format
                )
            elif self.provider == "aliyun":
                response = await self._call_aliyun(
                    prompt, temperature, max_tokens, system_message, response_format
                )
            elif self.provider == "baidu_vod":
                response = await self._call_baidu_vod(
                    prompt, temperature, max_tokens, system_message, response_format
                )
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")
            
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            response.latency_ms = latency
            
            return response
            
        except Exception as e:
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            err = str(e).strip() or f"{type(e).__name__}（常见原因：请求超时 {req_timeout}s 或网络中断）"
            logger.warning(
                "LLM 调用异常 provider=%s model=%s endpoint_id=%s: %s",
                self.provider,
                self.model,
                getattr(self, "endpoint_id", None),
                err,
            )
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=latency,
                error=err,
            )
    
    async def _call_volcano(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        response_format: Optional[Dict],
        timeout_sec: float,
    ) -> LLMResponse:
        """调用火山引擎 (Doubao) API"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        
        # 火山引擎使用推理点ID作为model参数
        model_id = self.endpoint_id or self.model
        
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        # 方舟上许多豆包/接入点不支持 OpenAI 的 response_format=json_object（会返回 400 InvalidParameter）
        ark_json_mode = os.environ.get("ARK_USE_RESPONSE_FORMAT_JSON", "").lower() in ("1", "true", "yes")
        if response_format and ark_json_mode:
            payload["response_format"] = response_format
        
        pm = len(prompt)
        sm = len(system_message or "")
        logger.info(
            "火山 chat.completions 请求 model=%s prompt_chars=%d system_chars=%d max_tokens=%s temp=%s",
            model_id,
            pm,
            sm,
            max_tokens,
            temperature,
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout_sec,
            )
            
            if response.status_code != 200:
                error_text = response.text
                logger.warning(
                    "火山 HTTP 非 200 status=%s body_preview=%s",
                    response.status_code,
                    (error_text[:500] + "...") if len(error_text) > 500 else error_text,
                )
                raise Exception(f"火山API调用失败: {response.status_code} - {error_text}")
            
            data = response.json()

            choice0 = (data.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            raw = msg.get("content")

            if isinstance(raw, list):
                parts: List[str] = []
                for p in raw:
                    if isinstance(p, dict):
                        t = p.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                        elif isinstance(p.get("content"), str):
                            parts.append(str(p["content"]))
                    elif isinstance(p, str):
                        parts.append(p)
                content = "".join(parts)
            elif raw is None:
                content = ""
            else:
                content = str(raw)

            finish_reason = choice0.get("finish_reason")

            if not str(content).strip():
                reasoning = msg.get("reasoning_content") or msg.get("reasoning")
                if reasoning and str(reasoning).strip():
                    logger.warning(
                        "火山 message.content 为空，尝试使用 reasoning_content finish_reason=%r",
                        finish_reason,
                    )
                    content = str(reasoning)

            if not str(content).strip():
                logger.error(
                    "火山返回空正文 raw_type=%s finish_reason=%r usage=%r choice_preview=%s",
                    type(raw).__name__,
                    finish_reason,
                    data.get("usage"),
                    str(choice0)[:400],
                )
                raise Exception(
                    "火山模型返回正文为空 "
                    f"(finish_reason={finish_reason!r}, usage={data.get('usage')}). "
                    "多为评委上下文过长或被截断，请缩减被测输出或调节 max_judge_input_chars / QAUTO_JUDGE_INPUT_MAX_CHARS。"
                )
            usage = data.get("usage", {})
            model = data.get("model", self.model)

            logger.info(
                "火山 chat.completions 成功 content_chars=%d finish_reason=%r usage=%s",
                len(content),
                finish_reason,
                usage,
            )

            return LLMResponse(
                content=content,
                model=model,
                usage=usage,
                latency_ms=0,
                raw_response=data
            )

    async def _call_openai(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        response_format: Optional[Dict]
    ) -> LLMResponse:
        """调用OpenAI API"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0
            )
            
            if response.status_code != 200:
                error_text = response.text
                raise Exception(f"API call failed: {response.status_code} - {error_text}")
            
            data = response.json()
            
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            model = data.get("model", self.model)
            
            return LLMResponse(
                content=content,
                model=model,
                usage=usage,
                latency_ms=0,
                raw_response=data
            )
    
    async def _call_aliyun(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        response_format: Optional[Dict]
    ) -> LLMResponse:
        """调用阿里云百炼API"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "input": {
                "messages": messages
            },
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "result_format": "message"
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/services/aigc/text-generation/generation",
                headers=headers,
                json=payload,
                timeout=60.0
            )
            
            if response.status_code != 200:
                error_text = response.text
                raise Exception(f"阿里云API调用失败: {response.status_code} - {error_text}")
            
            data = response.json()
            
            # 阿里云返回格式不同
            content = data.get("output", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            
            return LLMResponse(
                content=content,
                model=self.model,
                usage=usage,
                latency_ms=0,
                raw_response=data
            )

    def _baidu_vod_request_headers(self, path: str, method: str = "POST") -> Dict[str, str]:
        if getattr(self, "baidu_auth_mode", "apikey") == "aksk":
            return _bce_auth_v1_headers(
                method,
                path,
                self.access_key_id,
                self.secret_access_key,
            )
        return {
            "Authorization": _normalize_baidu_bearer(self.api_key),
            "Content-Type": "application/json",
        }

    def _baidu_vod_generate_content_url(self) -> tuple:
        rel = f"/v1beta/models/{self.model}:generateContent"
        url = f"{self.base_url}{rel}"
        base_path = urlparse(self.base_url).path.rstrip("/")
        sign_path = f"{base_path}{rel}" if base_path else rel
        return url, sign_path

    @staticmethod
    def _parse_gemini_generate_content(data: Dict[str, Any]) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            err = data.get("error") or {}
            if err:
                raise Exception(
                    f"百度云 generateContent 错误: {err.get('message') or err}"
                )
            raise Exception(f"百度云 generateContent 无 candidates: {str(data)[:500]}")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        texts: List[str] = []
        for part in parts:
            if isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(part.get("thought"), str):
                    texts.append(part["thought"])
        return "".join(texts)

    async def _call_baidu_vod(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        response_format: Optional[Dict],
    ) -> LLMResponse:
        """调用百度云 VOD Gemini generateContent（/v1beta/models/{model}:generateContent）"""

        url, path = self._baidu_vod_generate_content_url()
        headers = self._baidu_vod_request_headers(path)

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_message:
            payload["systemInstruction"] = {
                "parts": [{"text": system_message}],
            }
        if response_format:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        thinking_level = os.environ.get("BAIDU_VOD_THINKING_LEVEL", "").strip()
        if thinking_level:
            payload["generationConfig"]["thinkingConfig"] = {
                "includeThoughts": os.environ.get(
                    "BAIDU_VOD_INCLUDE_THOUGHTS", ""
                ).lower()
                in ("1", "true", "yes"),
                "thinkingLevel": thinking_level.upper(),
            }

        logger.info(
            "百度云 generateContent 请求 model=%s auth=%s prompt_chars=%d max_output_tokens=%s",
            self.model,
            getattr(self, "baidu_auth_mode", "apikey"),
            len(prompt),
            max_tokens,
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=120.0,
            )

        if response.status_code != 200:
            body = response.text
            logger.warning(
                "百度云 HTTP 非 200 status=%s body_preview=%s",
                response.status_code,
                (body[:500] + "...") if len(body) > 500 else body,
            )
            raise Exception(
                f"百度云 generateContent 失败: {response.status_code} - {body}"
            )

        data = response.json()
        content = self._parse_gemini_generate_content(data)
        if not str(content).strip():
            raise Exception(
                "百度云模型返回正文为空，请缩减评委上下文或调高 max_tokens。"
            )

        usage_meta = data.get("usageMetadata") or {}
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount"),
            "completion_tokens": usage_meta.get("candidatesTokenCount"),
            "total_tokens": usage_meta.get("totalTokenCount"),
        }
        logger.info(
            "百度云 generateContent 成功 content_chars=%d usage=%s",
            len(content),
            usage,
        )
        return LLMResponse(
            content=content,
            model=self.model,
            usage=usage,
            latency_ms=0,
            raw_response=data,
        )
    
    async def _call_multimodal_data_urls(
        self,
        prompt: str,
        image_data_urls: List[str],
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        response_format: Optional[Dict],
    ) -> LLMResponse:
        """文本 + data URL 截图（Web chat 附件）。"""
        if self.provider == "baidu_vod":
            start_time = asyncio.get_event_loop().time()
            gemini_parts: List[Dict[str, Any]] = [{"text": prompt}]
            for url in image_data_urls:
                encoded = encode_data_url_for_gemini_api(url)
                if encoded:
                    gemini_parts.append(encoded)
            if len(gemini_parts) < 2:
                return LLMResponse(
                    content="",
                    model=self.model,
                    usage={},
                    latency_ms=0,
                    error="无有效截图可送入视觉模型",
                )
            url, path = self._baidu_vod_generate_content_url()
            headers = self._baidu_vod_request_headers(path)
            payload: Dict[str, Any] = {
                "contents": [{"role": "user", "parts": gemini_parts}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            }
            if system_message:
                payload["systemInstruction"] = {"parts": [{"text": system_message}]}
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=120.0)
            if response.status_code != 200:
                raise Exception(f"百度云视觉 API 失败: {response.status_code} - {response.text[:500]}")
            data = response.json()
            content = self._parse_gemini_generate_content(data)
            usage_meta = data.get("usageMetadata") or {}
            return LLMResponse(
                content=content,
                model=self.model,
                usage={
                    "prompt_tokens": usage_meta.get("promptTokenCount"),
                    "completion_tokens": usage_meta.get("candidatesTokenCount"),
                    "total_tokens": usage_meta.get("totalTokenCount"),
                },
                latency_ms=0,
                raw_response=data,
            )

        if self.provider == "aliyun":
            logger.warning("aliyun provider 暂不支持 chat 截图，将仅使用文本")
            return await self._call_aliyun(
                prompt + "\n\n（用户附带了截图，但当前 LLM 提供商不支持识图，请根据文字继续。）",
                temperature,
                max_tokens,
                system_message,
                response_format,
            )

        parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for url in image_data_urls:
            encoded = encode_data_url_for_vision_api(url)
            if encoded:
                parts.append(encoded)
        if len(parts) < 2:
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=0,
                error="无有效截图可送入视觉模型",
            )

        messages: List[Dict[str, Any]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": parts})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        model_id = getattr(self, "endpoint_id", None) or self.model
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        ark_json_mode = os.environ.get("ARK_USE_RESPONSE_FORMAT_JSON", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if response_format and (self.provider == "openai" or (self.provider == "volcano" and ark_json_mode)):
            payload["response_format"] = response_format

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120.0,
            )
        if response.status_code != 200:
            raise Exception(f"多模态 API 调用失败: {response.status_code} - {response.text[:500]}")
        data = response.json()
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        raw = msg.get("content")
        if isinstance(raw, list):
            text_parts: List[str] = []
            for p in raw:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    text_parts.append(p["text"])
            content = "".join(text_parts)
        else:
            content = str(raw or "")
        usage = data.get("usage", {})
        model = data.get("model", model_id)
        return LLMResponse(
            content=content,
            model=model,
            usage=usage,
            latency_ms=0,
            raw_response=data,
        )

    async def call_vision(
        self,
        text_prompt: str,
        image_paths: List[str],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        system_message: Optional[str] = None,
    ) -> LLMResponse:
        """
        多模态调用：文本 + 本地图片。
        支持 openai / volcano(方舟) chat/completions，以及 baidu_vod Gemini inlineData。
        """
        start_time = asyncio.get_event_loop().time()

        if self.provider == "baidu_vod":
            return await self._call_baidu_vod_vision(
                text_prompt,
                image_paths,
                temperature,
                max_tokens,
                system_message,
                start_time,
            )

        parts: List[Dict[str, Any]] = [{"type": "text", "text": text_prompt}]
        for p in image_paths:
            encoded = encode_image_for_vision_api(p)
            if encoded:
                parts.append(encoded)

        if len(parts) < 2:
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=0,
                error="无有效图片可送入视觉模型",
            )

        messages: List[Dict[str, Any]] = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": parts})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        model_id = getattr(self, "endpoint_id", None) or self.model
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        ark_json_mode = os.environ.get("ARK_USE_RESPONSE_FORMAT_JSON", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if self.provider == "volcano" and ark_json_mode:
            payload["response_format"] = {"type": "json_object"}
        elif self.provider == "openai":
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120.0,
                )
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            if response.status_code != 200:
                raise Exception(
                    f"视觉 API 调用失败: {response.status_code} - {response.text[:500]}"
                )
            data = response.json()
            choice0 = (data.get("choices") or [{}])[0]
            msg = choice0.get("message") or {}
            raw = msg.get("content")
            if isinstance(raw, list):
                content = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in raw
                )
            else:
                content = str(raw or "")
            if not content.strip():
                raise Exception("视觉模型返回空正文")
            return LLMResponse(
                content=content,
                model=data.get("model", self.model),
                usage=data.get("usage", {}),
                latency_ms=latency,
                raw_response=data,
            )
        except Exception as e:
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            logger.warning(
                "视觉 LLM 调用异常 provider=%s model=%s: %s",
                self.provider,
                self.model,
                e,
            )
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=latency,
                error=str(e),
            )

    async def _call_baidu_vod_vision(
        self,
        text_prompt: str,
        image_paths: List[str],
        temperature: float,
        max_tokens: int,
        system_message: Optional[str],
        start_time: float,
    ) -> LLMResponse:
        gemini_parts: List[Dict[str, Any]] = [{"text": text_prompt}]
        for p in image_paths:
            encoded = encode_image_for_gemini_api(p)
            if encoded:
                gemini_parts.append(encoded)

        if len(gemini_parts) < 2:
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=0,
                error="无有效图片可送入视觉模型",
            )

        url, path = self._baidu_vod_generate_content_url()
        headers = self._baidu_vod_request_headers(path)
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": gemini_parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_message:
            payload["systemInstruction"] = {"parts": [{"text": system_message}]}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=120.0,
                )
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            if response.status_code != 200:
                raise Exception(
                    f"百度云视觉 API 失败: {response.status_code} - {response.text[:500]}"
                )
            data = response.json()
            content = self._parse_gemini_generate_content(data)
            if not content.strip():
                raise Exception("百度云视觉模型返回空正文")
            usage_meta = data.get("usageMetadata") or {}
            return LLMResponse(
                content=content,
                model=self.model,
                usage={
                    "prompt_tokens": usage_meta.get("promptTokenCount"),
                    "completion_tokens": usage_meta.get("candidatesTokenCount"),
                    "total_tokens": usage_meta.get("totalTokenCount"),
                },
                latency_ms=latency,
                raw_response=data,
            )
        except Exception as e:
            latency = (asyncio.get_event_loop().time() - start_time) * 1000
            logger.warning(
                "百度云视觉 LLM 调用异常 model=%s: %s",
                self.model,
                e,
            )
            return LLMResponse(
                content="",
                model=self.model,
                usage={},
                latency_ms=latency,
                error=str(e),
            )

    async def call_batch(
        self,
        prompts: List[str],
        temperature: float = 0.1,
        max_tokens: int = 2000,
        system_message: Optional[str] = None,
        concurrency: int = 5
    ) -> List[LLMResponse]:
        """批量调用（并发控制）"""
        semaphore = asyncio.Semaphore(concurrency)
        
        async def call_with_limit(prompt):
            async with semaphore:
                return await self.call(prompt, temperature, max_tokens, system_message)
        
        return await asyncio.gather(*[call_with_limit(p) for p in prompts])


class JudgmentCache:
    """评判结果缓存 - 避免对相同输出重复评判"""
    
    def __init__(self, max_size: int = 10000):
        self.cache: Dict[str, Any] = {}
        self.max_size = max_size
    
    def _make_key(
        self,
        output: str,
        evaluator_type: str,
        config: Dict
    ) -> str:
        """生成缓存键"""
        import hashlib
        output_hash = hashlib.md5(output.encode()).hexdigest()[:16]
        config_str = json.dumps(config, sort_keys=True)
        config_hash = hashlib.md5(config_str.encode()).hexdigest()[:16]
        return f"{evaluator_type}:{output_hash}:{config_hash}"
    
    def get(
        self,
        output: str,
        evaluator_type: str,
        config: Dict
    ) -> Optional[Any]:
        """获取缓存结果"""
        key = self._make_key(output, evaluator_type, config)
        return self.cache.get(key)
    
    def set(
        self,
        output: str,
        evaluator_type: str,
        config: Dict,
        result: Any
    ):
        """设置缓存结果"""
        if len(self.cache) >= self.max_size:
            keys_to_remove = list(self.cache.keys())[:self.max_size // 10]
            for k in keys_to_remove:
                del self.cache[k]
        
        key = self._make_key(output, evaluator_type, config)
        self.cache[key] = result


# 全局缓存实例
_global_cache = JudgmentCache()


def get_global_cache() -> JudgmentCache:
    """获取全局缓存实例"""
    return _global_cache
