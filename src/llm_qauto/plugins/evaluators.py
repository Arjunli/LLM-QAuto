"""
评判器插件 - 对AI输出进行评判
"""

import re
import json
import asyncio
import os
import logging
from typing import Any, Dict, List, Optional
from abc import abstractmethod
from jinja2 import Template
import numpy as np

from . import Plugin, register_plugin, JudgeContext
from ..models import DimensionResult, TestInput
from ..llm_client import LLMClient, get_global_cache
from ..media import media_paths_for_judge

logger = logging.getLogger(__name__)


def parse_llm_judge_json(content: Optional[str]) -> Dict[str, Any]:
    """
    从评委 LLM 返回的正文中解析 JSON 对象。
    兼容：空响应、```json 代码块、正文前后说明文字、仅含一个 {...} 片段。
    """
    if content is None:
        raise ValueError("评委模型返回空内容（可能是输入过长或服务端丢弃了正文，请为 LLM 评委配置 max_judge_input_chars）")
    text = content.replace("\ufeff", "").strip()
    if not text:
        raise ValueError(
            "评委模型返回空内容，无法解析 JSON（常见于上下文过长导致模型输出被截为空；请减小 max_tokens 或对 output 启用 max_judge_input_chars）"
        )

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError(f"正文中未找到 JSON 对象，预览: {text[:240]!r}")

    depth = 0
    in_str = False
    esc = False
    quote = ""
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
            continue
        if c in "\"'":
            in_str = True
            quote = c
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                return json.loads(chunk)

    raise ValueError(f"无法从评委输出中解析完整 JSON，预览: {text[:240]!r}")


def normalize_judge_issues(raw: Any) -> List[str]:
    """评委 JSON 的 issues 可能是字符串数组或对象数组，统一转为 List[str]。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if not isinstance(raw, list):
        return [str(raw)]

    out: List[str] = []
    for item in raw:
        if item is None:
            continue
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append(s)
            continue
        if isinstance(item, dict):
            field = item.get("field") or item.get("pair") or item.get("area") or ""
            problem = item.get("problem") or item.get("message") or item.get("desc") or ""
            severity = item.get("severity") or ""
            label = str(field).strip() if field else ""
            detail = str(problem).strip() if problem else ""
            sev = str(severity).strip() if severity else ""
            if label and detail:
                line = f"{label}：{detail}"
            elif label:
                line = label
            elif detail:
                line = detail
            else:
                line = json.dumps(item, ensure_ascii=False)
            if sev:
                line = f"{line} [{sev}]"
            out.append(line)
            continue
        out.append(str(item))
    return out


def truncate_output_for_llm_judge(output: Optional[str], eval_config: Dict[str, Any]) -> str:
    """
    被测接口常返回超长 JSON；原样塞进评委易导致上下文超限，方舟/OpenAI 可能返回空 completion。
    """
    if output is None:
        return ""
    s = str(output)
    default_cap = int(os.environ.get("QAUTO_JUDGE_INPUT_MAX_CHARS", "48000"))
    cap_conf = eval_config.get("max_judge_input_chars")
    max_chars = default_cap if cap_conf is None else int(cap_conf)
    if max_chars <= 0 or len(s) <= max_chars:
        logger.debug(
            "LLM评委: 无需截断 output_len=%d max_chars=%d (yaml=%r env默认=%s)",
            len(s),
            max_chars,
            cap_conf,
            os.environ.get("QAUTO_JUDGE_INPUT_MAX_CHARS", "48000"),
        )
        return s
    reserve_tail = max(4096, min(max_chars // 4, 20000))
    head = max_chars - reserve_tail - 200
    if head < 4096:
        head = max(2048, max_chars - reserve_tail - 120)
    logger.warning(
        "LLM评委: 已截断被测输出 full_len=%d -> cap=%d (head≈%d + tail≈%d)，"
        "evaluator.max_judge_input_chars=%r env QAUTO_JUDGE_INPUT_MAX_CHARS=%s",
        len(s),
        max_chars,
        head,
        reserve_tail,
        cap_conf,
        os.environ.get("QAUTO_JUDGE_INPUT_MAX_CHARS", "48000"),
    )
    banner = (
        f"\n\n...[QAUTO: 评委上下文限制，已由 {len(s)} 字符截断为约 {max_chars} "
        f"（头 {head}+尾 {reserve_tail}）；可在 evaluator 下设置 max_judge_input_chars]...\n\n"
    )
    return s[:head] + banner + s[-reserve_tail:]


class BaseEvaluator(Plugin):
    """评判器基类"""
    
    @abstractmethod
    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext
    ) -> DimensionResult:
        """评判单个输出"""
        pass


@register_plugin("evaluator", "rule")
class RuleEvaluator(BaseEvaluator):
    """规则引擎评判器 - 零成本、毫秒级"""
    
    @property
    def name(self) -> str:
        return "rule"
    
    async def initialize(self, config: Dict[str, Any]):
        self.rules = config.get("rules", [])
    
    async def cleanup(self):
        pass
    
    def _evaluate_condition(self, condition: str, output: str, params: Dict) -> bool:
        """评估条件表达式"""
        if not isinstance(output, str):
            output = "" if output is None else str(output)
        # 简单的条件表达式求值
        # 支持: len(), contains(), not_contains(), not_contains_any(), is_valid_utf8(), regex_match()
        
        # 构建求值环境
        def _not_contains(s, substr):
            if isinstance(substr, (list, tuple)):
                return not any(sub in s for sub in substr)
            return substr not in s

        media_count = int(params.pop("_media_count", 0))
        media_ok = int(params.pop("_media_ok", 0))

        env = {
            "output": output,
            "len": len,
            "contains": lambda s, substr: substr in s,
            "not_contains": _not_contains,
            "contains_any": lambda s, substrs: any(sub in s for sub in substrs),
            "not_contains_any": lambda s, substrs: not any(sub in s for sub in substrs),
            "is_valid_utf8": lambda s: True,  # Python字符串总是有效的
            "regex_match": lambda s, pattern: bool(re.search(pattern, s)),
            "starts_with": lambda s, prefix: s.startswith(prefix),
            "ends_with": lambda s, suffix: s.endswith(suffix),
            "media_count": media_count,
            "media_ok": media_ok,
            "has_images": media_count > 0,
            "all_images_ok": media_count > 0 and media_ok == media_count,
        }
        env.update(params)
        
        try:
            # 安全求值 - 只允许特定函数
            result = eval(condition, {"__builtins__": {}}, env)
            return bool(result)
        except Exception as e:
            print(f"规则求值错误: {condition}, 错误: {e}")
            return False
    
    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext
    ) -> DimensionResult:
        """规则评判"""
        rules = config.get("rules", [])
        issues = []
        passed = True
        
        start_time = asyncio.get_event_loop().time()
        
        media_list = []
        if context.test_output is not None:
            media_list = getattr(context.test_output, "media", None) or []
        media_count = len(media_list)
        media_ok = sum(
            1 for m in media_list
            if getattr(m, "local_path", None) and not getattr(m, "error", None)
        )

        for rule in rules:
            name = rule.get("name")
            condition = rule.get("condition")
            params = dict(rule.get("params", {}))
            params["_media_count"] = media_count
            params["_media_ok"] = media_ok
            severity = rule.get("severity", "error")
            
            result = self._evaluate_condition(condition, output, params)
            
            if not result:
                issues.append(f"{name}: 未通过规则检查")
                if severity == "error":
                    passed = False
        
        judgment_time = (asyncio.get_event_loop().time() - start_time) * 1000
        
        # 分数计算
        score = 10.0 if passed else 0.0
        if issues and passed:  # 有警告但通过
            score = 7.0
        
        return DimensionResult(
            dimension_id=config.get("dimension_id", "rule_check"),
            evaluator_type="rule",
            passed=passed,
            score=score,
            categories=["format_compliant"] if passed else ["format_violation"],
            issues=issues,
            confidence=1.0,
            judgment_time_ms=judgment_time,
            metadata={"rules_checked": len(rules)}
        )


@register_plugin("evaluator", "llm")
class LLMEvaluator(BaseEvaluator):
    """LLM评判器 - 语义级评判"""
    
    @property
    def name(self) -> str:
        return "llm"
    
    async def initialize(self, config: Dict[str, Any]):
        self.model = config.get("model", "gpt-4o-mini")
        self.prompt_template = config.get("prompt_template", "")
        self.output_schema = config.get("output_schema", {})
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 2000)
        self.use_cache = config.get("use_cache", True)
        
        # 初始化LLM客户端
        try:
            self.client = LLMClient(model=self.model)
        except ValueError:
            # API key未设置，稍后处理
            self.client = None
        
        # 加载上下文文件
        self.context = {}
        for key, path in config.get("context", {}).items():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.context[key] = f.read()
            except:
                self.context[key] = path  # 直接使用字符串
    
    async def cleanup(self):
        pass
    
    async def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        if not self.client:
            # 延迟初始化客户端
            self.client = LLMClient(model=self.model)
        
        # 要求JSON格式响应
        response_format = {"type": "json_object"}
        
        llm_response = await self.client.call(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=response_format
        )
        
        if llm_response.error:
            raise Exception(f"LLM call failed: {llm_response.error}")
        
        return llm_response.content
    
    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext
    ) -> DimensionResult:
        """LLM评判"""
        start_time = asyncio.get_event_loop().time()
        
        # 检查缓存
        if self.use_cache:
            cache = get_global_cache()
            cached_result = cache.get(output, "llm", config)
            if cached_result:
                return cached_result
        
        # 渲染prompt（被测 output 可能极长，先截断再渲染防止评委侧空返回）
        clip = truncate_output_for_llm_judge(output, config)
        template = Template(self.prompt_template)
        
        # 构建模板变量
        template_vars = {
            "output": clip,
            "output_full_length": len(output or ""),
            "input": context.test_input,  # 传递整个input对象，可以访问 .prompt 和 .variables
            "prompt": context.test_input.prompt,  # 直接访问prompt
            "context": self.context,
        }
        # 展开variables方便直接访问
        template_vars.update(context.test_input.variables)
        
        prompt = template.render(**template_vars)

        logger.info(
            "LLM评委调用 model=%s dimension_id=%s rendered_prompt_chars=%d "
            "judge_output_clip_chars=%d output_full_length=%d",
            self.model,
            config.get("dimension_id", "llm_judge"),
            len(prompt),
            len(clip),
            len(output or ""),
        )

        # 调用LLM
        extras: Dict[str, Any] = {}
        try:
            llm_response = await self._call_llm(prompt)
            result_data = parse_llm_judge_json(llm_response)
            
            # 解析结果
            score = float(result_data.get("score", result_data.get("quality_score", 5)))
            categories = result_data.get("categories", [])
            if isinstance(categories, str):
                categories = [categories]
            issues = normalize_judge_issues(result_data.get("issues", []))
            evidence = result_data.get("evidence", "")
            confidence = float(result_data.get("confidence", 0.8))

            reserved = {
                "score",
                "quality_score",
                "categories",
                "issues",
                "evidence",
                "confidence",
            }
            extras = {
                k: v
                for k, v in result_data.items()
                if k not in reserved and v is not None
            }

            # 判断是否通过
            passed = score >= 6.0

        except Exception as e:
            logger.warning(
                "LLM评委失败 dimension_id=%s model=%s prompt_chars=%d: %s",
                config.get("dimension_id", "llm_judge"),
                self.model,
                len(prompt),
                e,
                exc_info=True,
            )
            score = 0
            categories = ["judge_error"]
            issues = [f"评判失败: {str(e)}"]
            evidence = ""
            confidence = 0.0
            passed = False
        
        judgment_time = (asyncio.get_event_loop().time() - start_time) * 1000
        
        result = DimensionResult(
            dimension_id=config.get("dimension_id", "llm_judge"),
            evaluator_type="llm",
            passed=passed,
            score=score,
            categories=categories,
            issues=issues,
            evidence=evidence,
            confidence=confidence,
            judgment_time_ms=judgment_time,
            metadata={"model": self.model, **extras},
        )
        
        # 存入缓存
        if self.use_cache and passed:  # 只缓存成功的评判
            cache = get_global_cache()
            cache.set(output, "llm", config, result)
        
        return result


LISTING_JUDGE_EXCERPT_KEYS = (
    "id",
    "sku",
    "site",
    "language",
    "productName",
    "productParameters",
    "dataCompleteness",
    "keywordRanking",
    "title",
    "titleTrans",
    "bulletPoints1",
    "bulletPoints2",
    "bulletPoints3",
    "bulletPoints4",
    "bulletPoints5",
    "bulletPointsTrans1",
    "bulletPointsTrans2",
    "bulletPointsTrans3",
    "bulletPointsTrans4",
    "bulletPointsTrans5",
    "description",
    "descriptionTrans",
    "searchTerms",
    "tag1",
    "tag2",
    "tag3",
    "tag4",
    "tag5",
)


def build_listing_judge_excerpt(
    output: Optional[str],
    eval_config: Dict[str, Any],
) -> str:
    """
    从被测 JSON 中抽取 Listing 质检相关字段，避免整包重复竞品长文塞满评委上下文。
    失败时回退为 truncate_output_for_llm_judge。
    """
    if not output:
        return ""
    s = str(output).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return truncate_output_for_llm_judge(output, eval_config)

    if not isinstance(data, dict):
        return truncate_output_for_llm_judge(output, eval_config)

    excerpt_mode = (eval_config.get("excerpt_mode") or "").strip().lower()
    if excerpt_mode == "listing":
        keys = LISTING_JUDGE_EXCERPT_KEYS
    elif eval_config.get("excerpt_keys") is not None:
        keys = list(eval_config.get("excerpt_keys") or [])
    else:
        return truncate_output_for_llm_judge(output, eval_config)

    excerpt = {k: data[k] for k in keys if k in data and data[k] not in (None, "")}
    if not excerpt:
        return truncate_output_for_llm_judge(output, eval_config)

    text = json.dumps(excerpt, ensure_ascii=False, indent=2)
    cap = eval_config.get("max_judge_input_chars")
    if cap is not None and len(text) > int(cap):
        return truncate_output_for_llm_judge(text, eval_config)
    return text


def _pass_threshold_for_dimension(dim_id: str, global_config: Dict[str, Any]) -> float:
    try:
        for item in (
            global_config.get("pass_criteria", {}).get("dimensions") or []
        ):
            if item.get("id") == dim_id and item.get("min_avg_score") is not None:
                return float(item["min_avg_score"])
    except (TypeError, ValueError):
        pass
    return 6.0


def _parse_single_dimension_payload(dim_id: str, raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"维度 {dim_id} 条目须为对象")
    score = float(raw.get("score", raw.get("quality_score", 0)))
    categories = raw.get("categories", [])
    if isinstance(categories, str):
        categories = [categories]
    return {
        "score": score,
        "categories": categories,
        "issues": normalize_judge_issues(raw.get("issues", [])),
        "evidence": raw.get("evidence", "") or "",
        "confidence": float(raw.get("confidence", 0.8)),
        "extras": {
            k: v
            for k, v in raw.items()
            if k
            not in (
                "score",
                "quality_score",
                "categories",
                "issues",
                "evidence",
                "confidence",
            )
            and v is not None
        },
    }


@register_plugin("evaluator", "llm_batch")
class LLMBatchEvaluator(BaseEvaluator):
    """单次全评：一次 LLM 调用输出多维度 JSON，由引擎拆分到各 dimension_results。"""

    @property
    def name(self) -> str:
        return "llm_batch"

    async def initialize(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "gpt-4o-mini")
        self.prompt_template = config.get("prompt_template", "")
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 4500)
        self.dimension_ids: List[str] = list(config.get("dimension_ids") or [])
        self.use_cache = config.get("use_cache", True)
        try:
            self.client = LLMClient(model=self.model)
        except ValueError:
            self.client = None
        self.context: Dict[str, str] = {}
        for key, path in (config.get("context") or {}).items():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.context[key] = f.read()
            except OSError:
                self.context[key] = str(path)

    async def cleanup(self):
        pass

    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext,
    ) -> DimensionResult:
        """单维度接口占位；请使用 judge_all。"""
        all_results = await self.judge_all(output, config or self.config, context)
        first_id = self.dimension_ids[0] if self.dimension_ids else "batch"
        return all_results.get(first_id) or DimensionResult(
            dimension_id=first_id,
            evaluator_type="llm_batch",
            passed=False,
            score=0.0,
            categories=["judge_error"],
            issues=["llm_batch 未返回任何维度结果"],
            evidence="",
            confidence=0.0,
            judgment_time_ms=0.0,
        )

    async def _call_llm(self, prompt: str) -> str:
        if not self.client:
            self.client = LLMClient(model=self.model)
        llm_response = await self.client.call(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
        )
        if llm_response.error:
            raise Exception(f"LLM batch call failed: {llm_response.error}")
        return llm_response.content

    def _extract_dimensions_payload(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(data.get("dimensions"), dict):
            return data["dimensions"]
        out: Dict[str, Any] = {}
        for dim_id in self.dimension_ids:
            if dim_id in data and isinstance(data[dim_id], dict):
                out[dim_id] = data[dim_id]
        return out

    async def judge_all(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext,
    ) -> Dict[str, DimensionResult]:
        cfg = config or self.config
        dim_ids = list(cfg.get("dimension_ids") or self.dimension_ids)
        if not dim_ids:
            raise ValueError("llm_batch 须配置 dimension_ids")

        start_time = asyncio.get_event_loop().time()
        cache_cfg = {**cfg, "dimension_ids": dim_ids}

        if self.use_cache:
            cached = get_global_cache().get(output, "llm_batch", cache_cfg)
            if isinstance(cached, dict) and cached:
                return cached

        excerpt = build_listing_judge_excerpt(output, cfg)
        template = Template(self.prompt_template)
        template_vars = {
            "output": excerpt,
            "listing_excerpt": excerpt,
            "output_full_length": len(output or ""),
            "input": context.test_input,
            "prompt": context.test_input.prompt,
            "context": self.context,
        }
        template_vars.update(context.test_input.variables)
        prompt = template.render(**template_vars)

        logger.info(
            "LLM单次全评 model=%s dimensions=%s prompt_chars=%d excerpt_chars=%d output_full_length=%d",
            self.model,
            len(dim_ids),
            len(prompt),
            len(excerpt),
            len(output or ""),
        )

        results: Dict[str, DimensionResult] = {}
        try:
            raw_text = await self._call_llm(prompt)
            parsed = parse_llm_judge_json(raw_text)
            dim_payload = self._extract_dimensions_payload(parsed)

            missing = [d for d in dim_ids if d not in dim_payload]
            if missing:
                raise ValueError(f"全评 JSON 缺少维度: {missing}")

            global_cfg = context.global_config or {}
            for dim_id in dim_ids:
                payload = _parse_single_dimension_payload(dim_id, dim_payload[dim_id])
                threshold = _pass_threshold_for_dimension(dim_id, global_cfg)
                passed = payload["score"] >= threshold
                results[dim_id] = DimensionResult(
                    dimension_id=dim_id,
                    evaluator_type="llm_batch",
                    passed=passed,
                    score=payload["score"],
                    categories=payload["categories"],
                    issues=payload["issues"],
                    evidence=payload["evidence"],
                    confidence=payload["confidence"],
                    judgment_time_ms=0.0,
                    metadata={
                        "model": self.model,
                        "batch": True,
                        **payload["extras"],
                    },
                )
        except Exception as e:
            logger.warning(
                "LLM单次全评失败 model=%s dimensions=%s prompt_chars=%d: %s",
                self.model,
                dim_ids,
                len(prompt),
                e,
                exc_info=True,
            )
            err_msg = str(e)
            for dim_id in dim_ids:
                results[dim_id] = DimensionResult(
                    dimension_id=dim_id,
                    evaluator_type="llm_batch",
                    passed=False,
                    score=0.0,
                    categories=["judge_error"],
                    issues=[f"单次全评失败: {err_msg}"],
                    evidence="",
                    confidence=0.0,
                    judgment_time_ms=0.0,
                    metadata={"model": self.model, "batch": True},
                )

        elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
        for r in results.values():
            r.judgment_time_ms = elapsed / max(len(results), 1)

        if self.use_cache and all(r.passed for r in results.values()):
            get_global_cache().set(output, "llm_batch", cache_cfg, results)

        logger.info(
            "LLM单次全评完成 dimensions=%d passed=%d",
            len(results),
            sum(1 for r in results.values() if r.passed),
        )
        return results


@register_plugin("evaluator", "embedding")
class EmbeddingEvaluator(BaseEvaluator):
    """向量相似度评判器"""
    
    @property
    def name(self) -> str:
        return "embedding"
    
    async def initialize(self, config: Dict[str, Any]):
        self.model = config.get("model", "text-embedding-3-small")
        self.similarity_threshold = config.get("similarity_threshold", 0.8)
        
        # 加载参考池
        reference_file = config.get("reference_pool")
        self.reference_embeddings = []
        try:
            with open(reference_file, 'r', encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line)
                    self.reference_embeddings.append({
                        "text": data.get("text", ""),
                        "embedding": data.get("embedding", []),
                        "category": data.get("category", "default")
                    })
        except Exception as e:
            print(f"警告: 无法加载参考池 {reference_file}: {e}")
    
    async def cleanup(self):
        pass
    
    async def _get_embedding(self, text: str) -> List[float]:
        """获取文本的embedding - 需要接入实际API"""
        # TODO: 接入实际embedding API
        await asyncio.sleep(0.05)
        return [0.0] * 1536  # 模拟embedding
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """计算余弦相似度"""
        a = np.array(a)
        b = np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
    
    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext
    ) -> DimensionResult:
        """向量相似度评判"""
        start_time = asyncio.get_event_loop().time()
        
        if not self.reference_embeddings:
            return DimensionResult(
                dimension_id=config.get("dimension_id", "embedding"),
                evaluator_type="embedding",
                passed=False,
                score=0,
                categories=["no_reference"],
                issues=["参考池为空"],
                confidence=0.0,
                judgment_time_ms=0
            )
        
        # 获取输出embedding
        output_emb = await self._get_embedding(output)
        
        # 计算与所有参考的相似度
        similarities = []
        categories = []
        for ref in self.reference_embeddings:
            sim = self._cosine_similarity(output_emb, ref["embedding"])
            similarities.append(sim)
            categories.append(ref["category"])
        
        # 取最高相似度
        max_sim = max(similarities)
        max_idx = similarities.index(max_sim)
        best_category = categories[max_idx]
        
        # 判断
        passed = max_sim >= self.similarity_threshold
        score = max_sim * 10  # 转换为0-10分
        
        judgment_time = (asyncio.get_event_loop().time() - start_time) * 1000
        
        return DimensionResult(
            dimension_id=config.get("dimension_id", "embedding"),
            evaluator_type="embedding",
            passed=passed,
            score=score,
            categories=[best_category],
            issues=[] if passed else [f"相似度{max_sim:.2f}低于阈值{self.similarity_threshold}"],
            evidence=f"最相似参考: {self.reference_embeddings[max_idx]['text'][:100]}...",
            confidence=max_sim,
            judgment_time_ms=judgment_time,
            metadata={"max_similarity": max_sim}
        )


@register_plugin("evaluator", "reference")
class ReferenceEvaluator(BaseEvaluator):
    """参考对比评判器"""
    
    @property
    def name(self) -> str:
        return "reference"
    
    async def initialize(self, config: Dict[str, Any]):
        self.method = config.get("method", "exact")
        reference_file = config.get("reference_file")
        
        self.references = {}
        try:
            with open(reference_file, 'r', encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line)
                    input_hash = data.get("input_hash")
                    self.references[input_hash] = {
                        "expected": data.get("expected_output"),
                        "acceptable": data.get("acceptable_outputs", [])
                    }
        except Exception as e:
            print(f"警告: 无法加载参考文件 {reference_file}: {e}")
    
    async def cleanup(self):
        pass
    
    def _compute_match(self, output: str, expected: str, method: str) -> float:
        """计算匹配度"""
        if method == "exact":
            return 1.0 if output.strip() == expected.strip() else 0.0
        
        elif method == "contains":
            return 1.0 if expected in output else 0.0
        
        elif method == "regex":
            return 1.0 if re.search(expected, output) else 0.0
        
        elif method == "semantic":
            # 简化的语义匹配 - 关键词覆盖
            expected_words = set(expected.lower().split())
            output_words = set(output.lower().split())
            if not expected_words:
                return 0.0
            return len(expected_words & output_words) / len(expected_words)
        
        return 0.0
    
    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext
    ) -> DimensionResult:
        """参考对比评判"""
        start_time = asyncio.get_event_loop().time()
        
        # 根据输入查找参考
        input_text = context.test_input.prompt
        input_hash = str(hash(input_text) % 10000)  # 简化hash
        
        reference = self.references.get(input_hash)
        
        if not reference:
            return DimensionResult(
                dimension_id=config.get("dimension_id", "reference"),
                evaluator_type="reference",
                passed=True,  # 无参考时默认通过
                score=5.0,
                categories=["no_reference"],
                issues=["未找到对应参考输出"],
                confidence=0.5,
                judgment_time_ms=0
            )
        
        # 计算匹配度
        expected = reference["expected"]
        match_score = self._compute_match(output, expected, self.method)
        
        # 检查可接受输出
        for acceptable in reference["acceptable"]:
            alt_score = self._compute_match(output, acceptable, self.method)
            match_score = max(match_score, alt_score)
        
        passed = match_score >= 0.8
        score = match_score * 10
        
        judgment_time = (asyncio.get_event_loop().time() - start_time) * 1000
        
        return DimensionResult(
            dimension_id=config.get("dimension_id", "reference"),
            evaluator_type="reference",
            passed=passed,
            score=score,
            categories=["match"] if passed else ["mismatch"],
            issues=[] if passed else [f"匹配度{match_score:.2f}低于0.8"],
            evidence=f"期望: {expected[:100]}...",
            confidence=match_score,
            judgment_time_ms=judgment_time
        )


@register_plugin("evaluator", "image_rule")
class ImageRuleEvaluator(BaseEvaluator):
    """图像产物规则评判器 — 检查是否成功生成、落盘、最小体积等（零 LLM 成本）"""

    @property
    def name(self) -> str:
        return "image_rule"

    async def initialize(self, config: Dict[str, Any]):
        self.rules = config.get("rules", [])

    async def cleanup(self):
        pass

    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext,
    ) -> DimensionResult:
        rules = config.get("rules", [])
        if not rules:
            rules = [
                {
                    "name": "至少一张图",
                    "condition": "media_count >= 1",
                    "severity": "error",
                },
                {
                    "name": "图片落盘成功",
                    "condition": "all_images_ok",
                    "severity": "error",
                },
            ]
        delegate = RuleEvaluator()
        await delegate.initialize({"rules": rules})
        return await delegate.judge(output, config, context)


@register_plugin("evaluator", "vision_llm")
class VisionLLMEvaluator(BaseEvaluator):
    """视觉 LLM 评判器 — 图文一致、画面质量、安全合规（需多模态模型）"""

    @property
    def name(self) -> str:
        return "vision_llm"

    async def initialize(self, config: Dict[str, Any]):
        self.model = config.get("model", "gpt-4o")
        self.prompt_template = config.get("prompt_template", "")
        self.temperature = config.get("temperature", 0.1)
        self.max_tokens = config.get("max_tokens", 2000)
        self.use_cache = config.get("use_cache", False)
        self.max_images = int(config.get("max_images", 4))
        self.system_message = config.get("system_message")
        try:
            self.client = LLMClient(model=self.model)
        except ValueError:
            self.client = None
        self.context = {}
        for key, path in config.get("context", {}).items():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.context[key] = f.read()
            except Exception:
                self.context[key] = path

    async def cleanup(self):
        pass

    async def judge(
        self,
        output: str,
        config: Dict[str, Any],
        context: JudgeContext,
    ) -> DimensionResult:
        start_time = asyncio.get_event_loop().time()

        test_output = context.test_output
        image_paths: List[str] = []
        if test_output is not None:
            image_paths = media_paths_for_judge(
                getattr(test_output, "media", None) or []
            )[: self.max_images]

        if not image_paths:
            return DimensionResult(
                dimension_id=config.get("dimension_id", "vision_llm"),
                evaluator_type="vision_llm",
                passed=False,
                score=0.0,
                categories=["no_image"],
                issues=["无可用本地图片，请配置 output_parser.media 并启用 download"],
                confidence=1.0,
                judgment_time_ms=0.0,
            )

        if self.use_cache:
            cache = get_global_cache()
            cache_key = output + "|" + "|".join(image_paths)
            cached = cache.get(cache_key, "vision_llm", config)
            if cached:
                return cached

        clip = truncate_output_for_llm_judge(output, config)
        template = Template(self.prompt_template)
        template_vars = {
            "output": clip,
            "output_full_length": len(output or ""),
            "input": context.test_input,
            "prompt": context.test_input.prompt,
            "context": self.context,
            "image_count": len(image_paths),
            "content_mode": getattr(test_output, "content_mode", "image") if test_output else "image",
        }
        template_vars.update(context.test_input.variables)
        text_prompt = template.render(**template_vars)

        if not self.client:
            self.client = LLMClient(model=self.model)

        try:
            llm_response = await self.client.call_vision(
                text_prompt=text_prompt,
                image_paths=image_paths,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                system_message=self.system_message,
            )
            if llm_response.error:
                raise Exception(llm_response.error)
            result_data = parse_llm_judge_json(llm_response.content)
            score = float(result_data.get("score", result_data.get("quality_score", 5)))
            categories = result_data.get("categories", [])
            if isinstance(categories, str):
                categories = [categories]
            issues = normalize_judge_issues(result_data.get("issues", []))
            evidence = result_data.get("evidence", "")
            confidence = float(result_data.get("confidence", 0.8))
            passed = score >= 6.0
            extras = {
                k: v
                for k, v in result_data.items()
                if k
                not in {
                    "score",
                    "quality_score",
                    "categories",
                    "issues",
                    "evidence",
                    "confidence",
                }
                and v is not None
            }
        except Exception as e:
            logger.warning(
                "视觉评委失败 dimension_id=%s model=%s: %s",
                config.get("dimension_id", "vision_llm"),
                self.model,
                e,
            )
            score = 0.0
            categories = ["judge_error"]
            issues = [f"视觉评判失败: {str(e)}"]
            evidence = ""
            confidence = 0.0
            passed = False
            extras = {}

        judgment_time = (asyncio.get_event_loop().time() - start_time) * 1000
        result = DimensionResult(
            dimension_id=config.get("dimension_id", "vision_llm"),
            evaluator_type="vision_llm",
            passed=passed,
            score=score,
            categories=categories,
            issues=issues,
            evidence=evidence,
            confidence=confidence,
            judgment_time_ms=judgment_time,
            metadata={"model": self.model, "images_judged": len(image_paths), **extras},
        )

        if self.use_cache and passed:
            cache = get_global_cache()
            cache.set(output + "|" + "|".join(image_paths), "vision_llm", config, result)

        return result
