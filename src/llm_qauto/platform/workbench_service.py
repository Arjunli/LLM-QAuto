"""Generic LLM workbench for contract / perf / mock modules."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json

logger = logging.getLogger(__name__)

WB_RETRIES = int(os.environ.get("QAUTO_WORKBENCH_RETRIES", "2"))
WB_TIMEOUT = float(os.environ.get("QAUTO_WORKBENCH_TIMEOUT_SEC", "180"))

# URL/API path segment -> internal key
KIND_ALIASES = {
    "contract": "api_contract",
    "perf": "perf_test",
    "mock": "mock_data",
}

PROMPTS: Dict[str, str] = {
    "api_contract": """你是 API 契约测试专家。根据 OpenAPI/Swagger 或接口描述输出契约测试产物。

输出格式（仅一个 JSON 对象）：
{
  "assumptions": "假设与范围（markdown bullets）",
  "contract_matrix_markdown": "契约矩阵 markdown 表：| 方法 | 路径 | 场景 | 期望状态码 | 关键断言 |",
  "pytest_skeleton": "pytest + httpx 骨架代码（字符串）",
  "message": "简短中文说明"
}

规则：含正向 + 401/403 + 缺必填/类型错误等契约负向；Token 用 os.environ；断言具体可执行。""",

    "perf_test": """你是 k6 性能测试专家。根据场景描述生成可运行脚本与验收阈值。

输出格式（仅一个 JSON 对象）：
{
  "scenario_summary": "场景与加压模型说明（markdown）",
  "k6_script": "完整 k6 JS 脚本（字符串，含 import 与 export default function）",
  "run_command": "k6 run 命令示例",
  "thresholds_note": "p95/错误率阈值说明",
  "message": "简短中文说明"
}

规则：setup 登录用环境变量；含 thresholds；注明勿对生产默认全速压测。""",

    "mock_data": """你是 API Mock 与测试数据专家。根据接口描述或 OpenAPI 片段生成 Mock 方案。

输出格式（仅一个 JSON 对象）：
{
  "assumptions": "Mock 策略与假设（markdown）",
  "mock_spec_markdown": "Mock 清单表：| 方法 | 路径 | 场景 | 响应要点 | 状态码 |",
  "mock_server_code": "Python FastAPI mock 服务代码或 MSW handlers（字符串，优先 FastAPI）",
  "sample_responses_json": "示例响应 JSON 字符串（可格式化）",
  "message": "简短中文说明"
}

规则：覆盖成功/空列表/错误码；敏感字段用占位符；代码可直接保存为 mock_server.py 运行。""",
}


def resolve_kind(kind: str) -> str:
    k = (kind or "").strip()
    if k in KIND_ALIASES:
        return KIND_ALIASES[k]
    if k in PROMPTS:
        return k
    raise ValueError(f"未知工作台类型: {kind}")


def _sessions_dir(base: Path, module_key: str) -> Path:
    d = base / "workbench_sessions" / module_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_sessions(base: Path, module_key: str) -> List[Dict[str, Any]]:
    root = _sessions_dir(base, module_key)
    out: List[Dict[str, Any]] = []
    for p in sorted(root.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": p.stem,
                    "title": data.get("title") or p.stem,
                    "updated_at": data.get("updated_at"),
                    "preview": (data.get("message") or "")[:120],
                }
            )
        except Exception as e:
            logger.warning("skip workbench session %s: %s", p, e)
    return out


def get_session(base: Path, module_key: str, session_id: str) -> Optional[Dict[str, Any]]:
    p = _sessions_dir(base, module_key) / f"{session_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(
    base: Path,
    module_key: str,
    payload: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    sid = session_id or str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    doc = {
        "id": sid,
        "module": module_key,
        "title": payload.get("title") or "未命名",
        "input_text": payload.get("input_text") or "",
        "message": payload.get("message") or "",
        "outputs": payload.get("outputs") or {},
        "updated_at": now,
        "created_at": payload.get("created_at") or now,
    }
    p = _sessions_dir(base, module_key) / f"{sid}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def delete_session(base: Path, module_key: str, session_id: str) -> bool:
    p = _sessions_dir(base, module_key) / f"{session_id}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def _guess_title(text: str) -> str:
    line = (text or "").strip().split("\n")[0][:40]
    return line or "工作台会话"


def _parse_response(resp) -> Dict[str, Any]:
    if resp.error or not (resp.content or "").strip():
        raise RuntimeError(resp.error or "模型返回空内容")
    return parse_llm_judge_json(resp.content)


async def generate(module_key: str, input_text: str, title: Optional[str] = None) -> Dict[str, Any]:
    module_key = resolve_kind(module_key)
    text = (input_text or "").strip()
    if not text:
        raise ValueError("请提供输入内容")

    system = PROMPTS.get(module_key)
    if not system:
        raise ValueError(f"未配置 prompt: {module_key}")

    try:
        client = LLMClient()
    except ValueError as e:
        raise ValueError(f"LLM 未配置: {e}") from e

    parts = []
    if title:
        parts.append(f"标题：{title}")
    parts.append(text)
    parts.append("\n请输出 JSON（见系统说明）。")
    prompt = "\n\n".join(parts)

    last_err: Optional[Exception] = None
    for attempt in range(1, WB_RETRIES + 1):
        try:
            resp = await client.call(
                prompt=prompt,
                system_message=system,
                temperature=0.2,
                max_tokens=12000,
                response_format={"type": "json_object"},
                timeout_sec=WB_TIMEOUT,
            )
            parsed = _parse_response(resp)
            outputs = {k: v for k, v in parsed.items() if k != "message"}
            return {
                "title": title or _guess_title(text),
                "input_text": text,
                "message": str(parsed.get("message") or "已生成"),
                "outputs": outputs,
                **outputs,
            }
        except Exception as e:
            last_err = e
            logger.warning("workbench %s 第 %d 次失败: %s", module_key, attempt, e)
            if attempt < WB_RETRIES:
                await asyncio.sleep(2.0 * attempt)

    raise RuntimeError(f"生成失败（已重试 {WB_RETRIES} 次）: {last_err}") from last_err
