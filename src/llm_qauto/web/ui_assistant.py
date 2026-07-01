"""
UI 自动化助手 — 多轮对话收集页面流程并生成 Playwright 脚本。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json
from ..platform import playwright_runner
from .chat_attachments import parse_request_attachments

logger = logging.getLogger(__name__)

UI_ASSISTANT_SYSTEM = """你是「UI 自动化助手」。帮助测试人员描述页面流程并生成 Playwright TypeScript 脚本。

## 你的工作
1. 友好中文对话，一次最多追问 1～2 项。
2. 维护 collected 对象。
3. 信息足够时设置 request_generate=true；用户说「生成脚本」也可触发。

## collected 字段
- url: 被测页面 URL（可选但建议有；生成前会自动用 Playwright 探测页面元素）
- description: 测试流程描述（必填）
- login_required: 是否需要登录（true/false，可选）
- assertions: 关键断言说明（可选）
- spec_name: 脚本文件名，如 login.spec.ts（可选）

## 何时 request_generate=true
- description 能支撑写出至少 1 条完整测试
- 关键步骤（入口、操作、断言）已明确

## 输出格式（仅一个 JSON 对象）
{
  "message": "中文回复",
  "collected": { ... },
  "request_generate": false,
  "quick_replies": ["需要登录", "测表单校验", "生成脚本"]
}
"""


def _merge_collected(prev: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(prev or {})
    for k, v in (new or {}).items():
        if v is not None and v != "":
            out[k] = v
    return out


def _extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://[^\s\)\]\"']+", text or "")
    return m.group(0).rstrip(".,;") if m else None


def _auto_enrich_collected(collected: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    text = (user_text or "").strip()
    if not text:
        return collected
    url = _extract_url(text)
    if url and not collected.get("url"):
        collected["url"] = url
    if len(text) >= 20 and not collected.get("description"):
        if url and text.replace(url, "").strip():
            collected["description"] = text
        elif not url:
            collected["description"] = text
    if "登录" in text or "login" in text.lower():
        collected["login_required"] = True
    return collected


def _enrich_from_messages(collected: Dict[str, Any], messages: List[Dict[str, str]]) -> Dict[str, Any]:
    for m in messages:
        if m.get("role") == "user":
            collected = _auto_enrich_collected(collected, m.get("content") or "")
    return collected


def _missing_fields(collected: Dict[str, Any]) -> List[str]:
    miss: List[str] = []
    desc = (collected.get("description") or "").strip()
    if len(desc) < 15:
        miss.append("description")
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


def _build_generation_description(collected: Dict[str, Any]) -> str:
    parts: List[str] = []
    if collected.get("url"):
        parts.append(f"目标 URL: {collected['url']}")
    if collected.get("login_required"):
        parts.append("需要登录后再操作")
    if collected.get("assertions"):
        parts.append(f"断言: {collected['assertions']}")
    parts.append(collected.get("description") or "")
    return "\n".join(parts)


UI_FIX_SYSTEM = """你是 Playwright 测试修复专家。用户提供了运行失败的日志和现有脚本，请分析根因并输出修复后的完整 TypeScript 脚本。

规则：
- 使用 @playwright/test
- 修正选择器、等待策略、超时、登录步骤等导致失败的问题
- 保留原测试意图；必要时增加 waitFor、更稳健的定位方式
- 不要硬编码敏感信息；继续用 process.env
- 若日志显示元素找不到，优先改用 role/text/data-testid 等更稳的选择器

输出 JSON（无 markdown 包裹）：
{
  "message": "中文说明：失败原因 + 具体修改点",
  "spec_name": "xxx.spec.ts",
  "spec_content": "完整修复后的 .spec.ts 文件"
}
"""


async def _fix_spec_from_run(
    fix_ctx: Dict[str, Any],
    attachments: Optional[List[Dict[str, Any]]] = None,
    user_note: str = "",
) -> Dict[str, Any]:
    spec_name = str(fix_ctx.get("spec_name") or "fixed.spec.ts")
    spec_content = str(fix_ctx.get("spec_content") or "").strip()
    failure_log = str(fix_ctx.get("failure_log") or fix_ctx.get("log") or "")[-12000:]
    error_summary = str(fix_ctx.get("error_summary") or "")

    try:
        client = LLMClient()
    except ValueError as e:
        raise RuntimeError(f"LLM 未配置: {e}") from e

    prompt = f"""运行 ID: {fix_ctx.get("run_id") or "未知"}

错误摘要:
{error_summary}

失败日志（节选）:
```
{failure_log}
```

当前脚本 ({spec_name}):
```typescript
{spec_content or "// （脚本库中未找到，请根据日志重写）"}
```

用户补充说明:
{user_note or "（无）"}

请输出修复后的完整脚本 JSON。"""
    image_urls = parse_request_attachments(attachments)
    if image_urls:
        prompt += f"\n\n（附带 {len(image_urls)} 张失败截图，请结合界面状态修复选择器与断言。）"

    resp = await client.call(
        prompt=prompt,
        system_message=UI_FIX_SYSTEM,
        temperature=0.15,
        max_tokens=6000,
        response_format={"type": "json_object"},
        image_data_urls=image_urls or None,
    )
    if resp.error:
        raise RuntimeError(resp.error)
    parsed = parse_llm_judge_json(resp.content)
    name = playwright_runner._safe_spec_name(str(parsed.get("spec_name") or spec_name))
    return {
        "message": str(parsed.get("message") or "脚本已修复"),
        "spec_name": name,
        "spec_content": str(parsed.get("spec_content") or ""),
    }


    return "\n".join(parts)


async def _ensure_page_probe(
    base: Path,
    collected: Dict[str, Any],
    force: bool = False,
) -> tuple[Dict[str, Any], Optional[str]]:
    """Probe URL for interactive elements; returns (collected, screenshot_data_url)."""
    url = (collected.get("url") or "").strip()
    if not url:
        return collected, None
    if collected.get("page_probe") and not force:
        b64 = (collected.get("page_probe") or {}).get("screenshot_base64")
        data_url = f"data:image/png;base64,{b64}" if b64 else None
        return collected, data_url

    try:
        probe = await asyncio.to_thread(playwright_runner.probe_page_url, base, url)
        stored = {k: v for k, v in probe.items() if k != "screenshot_base64"}
        collected["page_probe"] = stored
        collected.pop("page_probe_error", None)
        b64 = probe.get("screenshot_base64")
        data_url = f"data:image/png;base64,{b64}" if b64 else None
        return collected, data_url
    except Exception as e:
        logger.warning("页面探测失败 url=%s: %s", url, e)
        collected["page_probe_error"] = str(e)
        return collected, None


def _merge_image_urls(*groups: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    seen = set()
    for group in groups:
        for u in group or []:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
    return out


async def run_ui_assistant_chat(
    messages: List[Dict[str, str]],
    collected: Optional[Dict[str, Any]] = None,
    patch: Optional[Dict[str, Any]] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    collected = dict(collected or {})
    base = (project_root or Path(".")).resolve()
    if patch:
        collected = _merge_collected(collected, patch)
    fix_ctx = collected.get("fix_context") if isinstance(collected.get("fix_context"), dict) else None
    if patch and isinstance(patch.get("fix_context"), dict):
        fix_ctx = patch["fix_context"]
        collected["fix_context"] = fix_ctx
        if fix_ctx.get("spec_name"):
            collected["spec_name"] = fix_ctx["spec_name"]

    if not messages:
        return {
            "message": "你好，我是 **UI 自动化助手**。描述要测的页面流程（URL、步骤、断言），我会生成 Playwright `.spec.ts` 脚本。",
            "phase": "collecting",
            "collected": collected,
            "quick_replies": ["测登录流程", "测表单提交", "我有目标 URL"],
            "show_restart": False,
        }

    user_turns = sum(1 for m in messages if m.get("role") == "user")
    collected = _enrich_from_messages(collected, messages)
    last_user = messages[-1].get("content", "") if messages[-1].get("role") == "user" else ""
    collected = _auto_enrich_collected(collected, last_user)
    miss = _missing_fields(collected)

    auto_fix = bool(patch and patch.get("auto_fix"))
    want_fix = fix_ctx and (
        auto_fix
        or "修复" in last_user
        or "直接修复" in last_user
        or "重新生成" in last_user
    )
    if want_fix:
        try:
            fixed = await _fix_spec_from_run(fix_ctx, attachments, last_user)
            return {
                "message": fixed["message"]
                + "\n\n✅ **脚本已修复**，可在右侧预览；保存后回到脚本管理再次运行验证。",
                "phase": "ready",
                "collected": collected,
                "spec_name": fixed.get("spec_name"),
                "spec_content": fixed.get("spec_content"),
                "quick_replies": ["再优化选择器", "增加等待时间", "保存并运行"],
                "missing": [],
                "show_restart": True,
            }
        except Exception as e:
            logger.exception("UI 脚本修复失败")
            return {
                "message": f"修复失败：{e}\n\n你可以补充页面结构或期望步骤后，再回复「修复脚本」。",
                "phase": "collecting",
                "collected": collected,
                "quick_replies": ["修复脚本", "打开脚本管理"],
                "missing": miss,
                "show_restart": user_turns > 0,
            }

    if fix_ctx and user_turns <= 1 and not want_fix:
        return {
            "message": (
                f"已载入运行 **{fix_ctx.get('run_id', '')}** 的失败信息。\n\n"
                f"**错误摘要：** {fix_ctx.get('error_summary', '测试失败')}\n\n"
                "我会结合失败日志"
                + ("与截图" if fix_ctx.get("has_screenshot") else "")
                + "修复当前脚本。可直接回复 **「修复脚本」**，或补充你的说明后再修复。"
            ),
            "phase": "collecting",
            "collected": collected,
            "quick_replies": ["修复脚本", "选择器改成 getByRole", "增加登录等待"],
            "missing": [],
            "show_restart": False,
        }

    try:
        client = LLMClient()
    except ValueError as e:
        return {
            "message": f"LLM 未配置，无法使用 UI 助手。请在 .env 设置 LLM_PROVIDER 与 API Key。\n\n错误：{e}",
            "phase": "error",
            "collected": collected,
        }

    prompt = _format_prompt(messages, collected)
    image_urls = parse_request_attachments(attachments)
    if image_urls:
        prompt += f"\n\n（用户附带了 {len(image_urls)} 张 UI 截图，请根据界面元素编写 Playwright 步骤。）"
    try:
        resp = await client.call(
            prompt=prompt,
            system_message=UI_ASSISTANT_SYSTEM,
            temperature=0.2,
            max_tokens=2500,
            response_format={"type": "json_object"},
            image_data_urls=image_urls or None,
        )
        if resp.error:
            raise RuntimeError(resp.error)
        parsed = parse_llm_judge_json(resp.content)
    except Exception as e:
        logger.warning("UI 助手 LLM 失败: %s", e)
        hint = "、".join(miss) if miss else "确认后回复「生成脚本」"
        return {
            "message": f"模型暂时无法回复（{e}）。\n\n仍缺：**{hint}**",
            "phase": "collecting",
            "collected": collected,
            "missing": miss,
            "show_restart": user_turns > 0,
        }

    message = str(parsed.get("message") or "请继续描述测试流程。")
    collected = _merge_collected(collected, parsed.get("collected") or {})
    miss = _missing_fields(collected)

    quick_replies = parsed.get("quick_replies") or []
    if isinstance(quick_replies, str):
        quick_replies = [quick_replies]

    want_generate = bool(parsed.get("request_generate")) or "生成脚本" in last_user or "开始生成" in last_user
    force_probe = "重新探测" in last_user or "刷新页面" in last_user

    if want_generate and not miss:
        probe_note = ""
        probe_shot = None
        if collected.get("url"):
            collected, probe_shot = await _ensure_page_probe(base, collected, force=force_probe)
            if collected.get("page_probe"):
                n = collected["page_probe"].get("element_count", 0)
                probe_note = f"\n\n🔍 已自动探测页面（{n} 个可交互元素），脚本将基于真实 DOM 生成。"
            elif collected.get("page_probe_error"):
                probe_note = f"\n\n⚠️ 页面探测失败（{collected['page_probe_error']}），将仅根据描述生成；可检查 URL/网络或稍后重试。"
        try:
            desc = _build_generation_description(collected)
            gen_images = _merge_image_urls(
                image_urls,
                [probe_shot] if probe_shot else None,
            )
            gen = await playwright_runner.generate_spec(
                desc,
                url=collected.get("url"),
                spec_name=collected.get("spec_name"),
                image_data_urls=gen_images or None,
                page_probe=collected.get("page_probe"),
            )
            return {
                "message": message + probe_note + "\n\n✅ **脚本已生成**，可在右侧预览；点击下方保存到脚本库或进入编辑器。",
                "phase": "ready",
                "collected": collected,
                "spec_name": gen.get("spec_name"),
                "spec_content": gen.get("spec_content"),
                "quick_replies": quick_replies,
                "missing": [],
                "show_restart": user_turns > 0,
            }
        except Exception as e:
            message += f"\n\n⚠️ 生成脚本失败：{e}"
            want_generate = False

    if miss:
        message += f"\n\n📋 仍缺：**{'、'.join(miss)}**"

    return {
        "message": message,
        "phase": "collecting",
        "collected": collected,
        "quick_replies": quick_replies if user_turns > 0 else [],
        "missing": miss,
        "show_restart": user_turns > 0,
    }
