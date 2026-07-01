"""
用例设计助手 — 多轮对话收集 PRD / 验收标准并生成测试树与用例表。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json
from ..platform import case_service
from .chat_attachments import parse_request_attachments

logger = logging.getLogger(__name__)

CASE_ASSISTANT_SYSTEM = """你是「用例设计助手」。帮助测试人员从 PRD、用户故事或验收标准生成**完整**测试用例（含弱网、稳定性、边界等非功能场景）。

## 你的工作
1. 友好中文对话，一次最多追问 1～2 项，不要问卷轰炸。
2. 维护并更新 collected 对象（已确认的需求信息）。
3. 信息足够时设置 request_generate=true；用户说「生成用例」也可触发。
4. 生成前确认范围与优先级，不要臆造未提及的业务规则。
5. 默认生成的用例表应覆盖：功能主流程、边界/异常、弱网/断网/超时、权限（如适用）、并发重复操作（如适用）。

## collected 字段
- title: 用例会话标题（短名）
- prd_text: PRD / 用户故事 / 验收标准正文（必填，尽量完整）
- scope: 本次覆盖范围说明（可选）
- priority_focus: 重点测 P0/P1 的模块（可选）
- excluded: 明确不测的范围（可选，如「不测性能压测」）

## 何时 request_generate=true
- prd_text 已有实质内容（通常 ≥80 字或含清晰 AC 条目）
- 关键缺口已追问过，或用户明确要求生成
- 不要在 prd_text 为空时 request_generate=true

## 输出格式（仅一个 JSON 对象，无 markdown 包裹）
{
  "message": "给用户的中文回复，支持简短 markdown",
  "collected": { ...合并后的字段... },
  "request_generate": false,
  "quick_replies": ["补充弱网/稳定性", "补充边界场景", "生成用例"]
}
"""


def _merge_collected(prev: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(prev or {})
    for k, v in (new or {}).items():
        if v is not None and v != "":
            out[k] = v
    return out


def _looks_like_prd(text: str) -> bool:
    t = (text or "").strip()
    if len(t) >= 80:
        return True
    markers = ("验收", "AC", "用户故事", "PRD", "需求", "作为", "期望", "Given", "When", "Then", "| 编号 |")
    return any(m in t for m in markers)


def _auto_enrich_collected(collected: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    text = (user_text or "").strip()
    if not text:
        return collected
    if _looks_like_prd(text) and not collected.get("prd_text"):
        collected["prd_text"] = text
    elif len(text) > 200 and not collected.get("prd_text"):
        collected["prd_text"] = text
    if not collected.get("title") and collected.get("prd_text"):
        collected["title"] = case_service._guess_title(collected["prd_text"])
    if re.search(r"不测|排除|out of scope", text, re.I) and not collected.get("excluded"):
        collected["excluded"] = text[:500]
    return collected


def _enrich_from_messages(collected: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    for m in messages:
        if m.get("role") == "user":
            collected = _auto_enrich_collected(collected, m.get("content") or "")
    return collected


def _missing_fields(collected: Dict[str, Any]) -> List[str]:
    miss: List[str] = []
    prd = (collected.get("prd_text") or "").strip()
    if len(prd) < 30:
        miss.append("prd_text")
    if not (collected.get("title") or "").strip() and prd:
        collected["title"] = case_service._guess_title(prd)
    return miss


def _format_prompt(messages: List[Dict[str, str]], collected: Dict[str, Any]) -> str:
    parts: List[str] = []
    if collected:
        parts.append("【当前 collected 状态】\n" + json.dumps(collected, ensure_ascii=False, indent=2))
    for m in messages[:-1]:
        role = "用户" if m.get("role") == "user" else "助手"
        parts.append(f"{role}：{m.get('content', '')}")
    last = messages[-1] if messages else {"role": "user", "content": ""}
    parts.append(f"用户：{last.get('content', '')}")
    parts.append("\n请输出 JSON（见系统说明）。")
    return "\n\n".join(parts)


async def run_case_assistant_chat(
    messages: List[Dict[str, str]],
    collected: Optional[Dict[str, Any]] = None,
    patch: Optional[Dict[str, Any]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    collected = dict(collected or {})
    if patch:
        collected = _merge_collected(collected, patch)

    if not messages:
        return {
            "message": "你好，我是 **用例设计助手**。粘贴 PRD、用户故事或验收标准，我会追问缺口后生成测试树与用例表。",
            "phase": "collecting",
            "collected": collected,
            "quick_replies": ["我有 PRD 文档", "只有验收标准列表", "先帮我列假设"],
            "show_restart": False,
        }

    user_turns = sum(1 for m in messages if m.get("role") == "user")
    collected = _enrich_from_messages(collected, messages)
    last_user = messages[-1].get("content", "") if messages[-1].get("role") == "user" else ""
    collected = _auto_enrich_collected(collected, last_user)
    miss = _missing_fields(collected)

    try:
        client = LLMClient()
    except ValueError as e:
        return {
            "message": f"LLM 未配置，无法使用用例助手。请在 .env 设置 LLM_PROVIDER 与 API Key。\n\n错误：{e}",
            "phase": "error",
            "collected": collected,
        }

    prompt = _format_prompt(messages, collected)
    image_urls = parse_request_attachments(attachments)
    if image_urls:
        prompt += f"\n\n（用户附带了 {len(image_urls)} 张截图，请结合界面信息理解需求。）"
    try:
        resp = await client.call(
            prompt=prompt,
            system_message=CASE_ASSISTANT_SYSTEM,
            temperature=0.2,
            max_tokens=2500,
            response_format={"type": "json_object"},
            image_data_urls=image_urls or None,
        )
        if resp.error:
            raise RuntimeError(resp.error)
        parsed = parse_llm_judge_json(resp.content)
    except Exception as e:
        logger.warning("用例助手 LLM 失败: %s", e)
        hint = "、".join(miss) if miss else "确认后回复「生成用例」"
        return {
            "message": f"模型暂时无法回复（{e}）。\n\n仍缺：**{hint}**",
            "phase": "collecting",
            "collected": collected,
            "missing": miss,
            "show_restart": user_turns > 0,
        }

    message = str(parsed.get("message") or "请继续提供需求信息。")
    collected = _merge_collected(collected, parsed.get("collected") or {})
    miss = _missing_fields(collected)

    quick_replies = parsed.get("quick_replies") or []
    if isinstance(quick_replies, str):
        quick_replies = [quick_replies]

    want_generate = bool(parsed.get("request_generate")) or "生成用例" in last_user or "开始生成" in last_user

    if want_generate and not miss:
        try:
            gen = await case_service.generate_cases(
                input_text=collected.get("prd_text") or "",
                title=collected.get("title"),
                messages=messages,
                image_data_urls=image_urls or None,
                scope=collected.get("scope"),
                excluded=collected.get("excluded"),
                priority_focus=collected.get("priority_focus"),
            )
            return {
                "message": message + "\n\n✅ **用例已生成**，可在右侧预览；点击下方保存到服务端或导出 CSV。",
                "phase": "ready",
                "collected": collected,
                "title": gen.get("title") or collected.get("title"),
                "assumptions": gen.get("assumptions") or "",
                "mermaid_review": gen.get("mermaid_review") or "",
                "mermaid_tree": gen.get("mermaid_tree") or "",
                "case_table_markdown": gen.get("case_table_markdown") or "",
                "quick_replies": quick_replies,
                "missing": [],
                "show_restart": user_turns > 0,
            }
        except Exception as e:
            message += f"\n\n⚠️ 生成用例失败：{e}"
            want_generate = False

    if miss:
        message += f"\n\n📋 仍缺：**{'、'.join(miss)}**"

    reply_chips = quick_replies if user_turns > 0 else []

    return {
        "message": message,
        "phase": "collecting",
        "collected": collected,
        "quick_replies": reply_chips,
        "missing": miss,
        "show_restart": user_turns > 0,
    }
