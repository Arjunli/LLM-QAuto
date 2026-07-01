"""
Web 配置助手 — 多轮对话收集信息并生成测试项目 YAML。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import yaml

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json
from .config_scaffold import detect_curl_in_text, is_parseable_curl, missing_fields, scaffold_config
from .chat_attachments import parse_request_attachments

logger = logging.getLogger(__name__)

SCENE_CHOICES = [
    {
        "id": "listing_qc",
        "label": "Listing 七维质检",
        "suite_name": "listing-qc-batch",
        "hint": "德国/亚马逊 Listing 文案 CDQ 七维",
    },
    {
        "id": "prompt_rewrite_qc",
        "label": "帮写 Prompt L1",
        "suite_name": "prompt-rewrite-qc-batch",
        "hint": "AI 帮写正向/反向提示词文本质检",
    },
    {
        "id": "generic",
        "label": "通用三维质检",
        "suite_name": "copy-info-content-check",
        "hint": "内容质量 / 安全 / 格式",
    },
    {
        "id": "image_gen",
        "label": "生图测评",
        "suite_name": "image-gen-qc-batch",
        "hint": "图片交付 + 视觉评委",
    },
]

ASSISTANT_SYSTEM = """你是 LLM-QAuto 的「配置助手」。帮助运营/测试人员从浏览器 cURL 创建 YAML 测试项目。

## 你的工作
1. 友好中文对话，一次最多追问 1～2 项，不要问卷轰炸。
2. 维护并更新 collected 对象（已确认的配置字段）。
3. 信息足够时设置 request_scaffold=true，不要自己写完整 YAML（后端会生成）。

## collected 字段说明
- scene（必填）: listing_qc | prompt_rewrite_qc | image_gen | generic
- target_curl（必填）: 被测 HTTPS 接口的 curl 全文
- suite_name（必填）: 套件短名，如 prompt-rewrite-qc-batch
- suite_desc: 描述
- id_values: 测试 id，如 1914 或 8001-8050
- output_path: 响应 JSON 根路径，默认 data
- use_env_token: 默认 false，保留 cURL 里 Authorization 原文；不要问用户是否改 .env
- prompt_rewrite_qc 可选: raw_prompt_field, image_type_field, sample_raw_prompt, sample_image_type
- listing_qc 可选: async_poll, poll_curl, ready_path
- image_gen 可选: media_urls_path

## 场景速查
- prompt_rewrite_qc: AI 帮写正向/反向提示词 L1 文本质检
- listing_qc: 德国/亚马逊 Listing 七维（复用 CDQ 模板）
- image_gen: 出图 + vision_llm
- generic: 内容/安全/格式三维

## 禁止
- 猜测 Token 明文、臆造 JSON 字段 path
- 询问「是否把 Token 换成 ${ZHIYUAN_BEARER_TOKEN} / .env」——默认沿用 cURL，无需确认
- 在 collected 未齐时 request_scaffold=true

## 输出格式（仅输出一个 JSON 对象，无 markdown 包裹）
{
  "message": "给用户的中文回复，支持简短 markdown",
  "collected": { ... 合并后的字段 ... },
  "request_scaffold": false,
  "quick_replies": ["帮写测评", "Listing七维", "单条试跑 id=1914"]
}
"""


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


def _pick_better_curl(prev: Optional[str], new: Optional[str]) -> Optional[str]:
    if not prev:
        return new or None
    if not new:
        return prev
    prev_ok = is_parseable_curl(prev)
    new_ok = is_parseable_curl(new)
    if prev_ok and not new_ok:
        return prev
    if new_ok and not prev_ok:
        return new
    if prev_ok and new_ok:
        return new if len(new) > len(prev) else prev
    if re.search(r"https?://", new, re.I):
        return new
    if re.search(r"https?://", prev, re.I):
        return prev
    return new if len(new) > len(prev) else prev


def _merge_collected(prev: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(prev or {})
    for k, v in (new or {}).items():
        if v is None or v == "":
            continue
        if k == "target_curl":
            out[k] = _pick_better_curl(out.get(k), v)
        elif k == "poll_curl":
            out[k] = _pick_better_curl(out.get(k), v)
        else:
            out[k] = v
    return out


def _resolve_target_curl(collected: Dict[str, Any], messages: List[Dict[str, str]]) -> None:
    current = collected.get("target_curl")
    if current and is_parseable_curl(current):
        return
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        curl = detect_curl_in_text(m.get("content") or "")
        if curl and is_parseable_curl(curl):
            collected["target_curl"] = curl
            return


def _auto_enrich_collected(collected: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    curl = detect_curl_in_text(user_text)
    if curl and not collected.get("target_curl"):
        collected["target_curl"] = curl
    lower = (user_text or "").lower()
    if not collected.get("scene"):
        if "帮写" in user_text or ("prompt" in lower and "rewrite" in lower):
            collected["scene"] = "prompt_rewrite_qc"
        elif "listing" in lower or "七维" in user_text or "regenerate" in lower:
            collected["scene"] = "listing_qc"
        elif "生图" in user_text or ("image" in lower and "gen" in lower):
            collected["scene"] = "image_gen"
        elif "通用" in user_text or "三维" in user_text or "内容安全" in user_text:
            collected["scene"] = "generic"
        else:
            for opt in SCENE_CHOICES:
                if opt["label"] in user_text or opt["id"] in user_text:
                    collected["scene"] = opt["id"]
                    break
    if not collected.get("suite_name") and collected.get("scene"):
        for opt in SCENE_CHOICES:
            if opt["id"] == collected["scene"]:
                collected["suite_name"] = opt["suite_name"]
                break
        if not collected.get("suite_name"):
            collected["suite_name"] = {
                "prompt_rewrite_qc": "prompt-rewrite-qc-batch",
                "listing_qc": "listing-qc-batch",
                "image_gen": "image-gen-qc-batch",
                "generic": "generic-api-qc-batch",
            }.get(collected["scene"], "my-test-suite")
    if re.search(r"copy-info-content-check", user_text or "", re.I):
        collected.setdefault("suite_name", "copy-info-content-check")
        collected.setdefault("scene", "generic")
    if "8001" in user_text and "8050" in user_text and not collected.get("id_values"):
        collected["id_values"] = "8001-8050"
    m_id = re.search(r"(?:id|任务)\s*[=＝]\s*(\d+(?:\s*[-–—]\s*\d+)?(?:\s*,\s*\d+)*)", user_text or "", re.I)
    if m_id and not collected.get("id_values"):
        collected["id_values"] = m_id.group(1).replace(" ", "")
    if not collected.get("id_values"):
        m_range = re.search(r"(\d+)\s*[-–—]\s*(\d+)", user_text or "")
        if m_range:
            collected["id_values"] = f"{m_range.group(1)}-{m_range.group(2)}"
    return collected


def _enrich_collected_from_messages(collected: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    for m in messages:
        if m.get("role") == "user":
            collected = _auto_enrich_collected(collected, m.get("content", "") or "")
    return collected


async def run_assistant_chat(
    messages: List[Dict[str, str]],
    collected: Optional[Dict[str, Any]] = None,
    patch: Optional[Dict[str, Any]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    collected = dict(collected or {})
    collected.setdefault("use_env_token", False)
    if patch:
        collected = _merge_collected(collected, patch)

    if not messages:
        return {
            "message": "你好，我是 **配置助手**。粘贴被测接口的 cURL，或告诉我你要测什么（帮写 / Listing / 生图）。",
            "phase": "collecting",
            "collected": collected,
            "quick_replies": [],
            "scene_options": [],
            "show_restart": False,
        }

    user_turns = sum(1 for m in messages if m.get("role") == "user")

    collected = _enrich_collected_from_messages(collected, messages)
    last_user = messages[-1].get("content", "") if messages[-1].get("role") == "user" else ""
    collected = _auto_enrich_collected(collected, last_user)

    try:
        client = LLMClient()
    except ValueError as e:
        return {
            "message": f"评委 LLM 未配置，无法使用配置助手。请在 .env 设置 LLM_PROVIDER 与 API Key。\n\n错误：{e}",
            "phase": "error",
            "collected": collected,
        }

    prompt = _format_prompt(messages, collected)
    image_urls = parse_request_attachments(attachments)
    try:
        resp = await client.call(
            prompt=prompt,
            system_message=ASSISTANT_SYSTEM,
            temperature=0.15,
            max_tokens=2500,
            response_format={"type": "json_object"},
            image_data_urls=image_urls or None,
        )
        if resp.error:
            raise RuntimeError(resp.error)
        parsed = parse_llm_judge_json(resp.content)
    except Exception as e:
        logger.warning("配置助手 LLM 失败: %s", e)
        miss = missing_fields(collected) if collected.get("scene") else ["scene", "target_curl", "suite_name"]
        hint = "、".join(miss) if miss else "确认无误后回复「生成配置」"
        return {
            "message": f"模型暂时无法回复（{e}）。\n\n当前已收集：{json.dumps(collected, ensure_ascii=False)}\n\n仍缺：{hint}",
            "phase": "collecting",
            "collected": collected,
            "show_restart": user_turns > 0,
        }

    message = str(parsed.get("message") or "请继续提供信息。")
    collected = _merge_collected(collected, parsed.get("collected") or {})
    _resolve_target_curl(collected, messages)
    if not re.search(r"环境变量|ZHIYUAN_BEARER|use_env|\.env", last_user, re.I):
        collected["use_env_token"] = False
    quick_replies = parsed.get("quick_replies") or []
    if isinstance(quick_replies, str):
        quick_replies = [quick_replies]

    want_scaffold = bool(parsed.get("request_scaffold")) or "生成配置" in last_user or "生成项目" in last_user
    miss = missing_fields(collected)

    if want_scaffold and not miss:
        _resolve_target_curl(collected, messages)
        try:
            yaml_text = scaffold_config(collected)
            yaml.safe_load(yaml_text)
            return {
                "message": message
                + "\n\n✅ **配置已生成**，可点击下方按钮创建测试项目，或打开编辑器微调。",
                "phase": "ready",
                "collected": collected,
                "config_yaml": yaml_text,
                "config_name": collected.get("suite_name"),
                "quick_replies": quick_replies,
                "scene_options": [],
                "show_restart": user_turns > 0,
            }
        except Exception as e:
            message += f"\n\n⚠️ 生成配置失败：{e}"
            want_scaffold = False

    if miss and collected.get("scene"):
        message += f"\n\n📋 仍缺：**{ '、'.join(miss) }**"

    scene_options = SCENE_CHOICES if user_turns > 0 and not collected.get("scene") else []
    reply_chips = quick_replies if user_turns > 0 and not scene_options else []

    return {
        "message": message,
        "phase": "collecting" if miss or not want_scaffold else "ready",
        "collected": collected,
        "quick_replies": reply_chips,
        "missing": miss,
        "scene_options": scene_options,
        "show_restart": user_turns > 0,
    }
