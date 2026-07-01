"""Test case design service (PRD → tree + table)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json
from .mermaid_normalize import MERMAID_CLASSDEF, normalize_mermaid

logger = logging.getLogger(__name__)

CASE_GEN_RETRIES = int(os.environ.get("QAUTO_CASE_GEN_RETRIES", "3"))
CASE_GEN_TIMEOUT = float(os.environ.get("QAUTO_CASE_GEN_TIMEOUT_SEC", "180"))

CASE_SYSTEM = """你是测试设计专家。根据 PRD、用户故事或验收标准输出**完整、可执行**的测试用例（功能 + 非功能维度）。

输出格式（仅一个 JSON 对象，无 markdown 包裹）：
{
  "assumptions": "假设与缺口（markdown bullets，须含「覆盖维度」小节）",
  "mermaid_review": "评审用逻辑/覆盖图 mermaid（flowchart，不含 ``` 围栏）",
  "mermaid_tree": "完整测试覆盖树 mermaid（不含 ``` 围栏）",
  "case_table_markdown": "用例表 markdown（含表头）",
  "message": "给用户的简短中文说明"
}

## 交付顺序
1. assumptions → 2. mermaid_review（评审图）→ 3. mermaid_tree（覆盖树）→ 4. 用例表；TC 编号在三处一致。

## 用例表表头（固定）
| 编号 | 模块 | 前置条件 | 步骤 | 测试数据 | 期望结果 | 优先级 | 类型 | 关联需求 ID | 风险/备注 |

- 优先级仅 P0 / P1 / P2
- 类型从下列选最接近的一项（可多行拆分）：功能、边界、异常、权限、安全、兼容、性能、弱网、稳定性、并发、易用性、数据一致性

## 覆盖维度（必须逐项评估；适用则写具体用例行，不适用在 assumptions 的「覆盖维度」中说明跳过原因）

### A. 功能（必有）
- 主流程正向、关键分支、状态切换、取消/回退

### B. 边界与异常（必有，至少 2 条或与功能点数量匹配）
- 空值/极值/非法输入、重复操作、操作中断、部分失败

### C. 权限与安全（涉及登录/角色/敏感数据时必有）
- 不同角色行为差异、无权限访问、越权、敏感信息展示

### D. 网络与稳定性（Web/移动端/接口场景默认必有，至少 2 条）
- **弱网/高延迟**：加载态、超时提示、防重复提交、操作可重试
- **断网/恢复**：失败提示明确、本地草稿/选择不丢失、恢复后可继续或重试
- **接口失败/超时**：错误码或 Toast、不影响已填数据、幂等不重复写入

### E. 并发与一致性（涉及提交/复制/批量操作时评估）
- 快速连点、双开 Tab 重复提交、并发编辑冲突提示

### F. 兼容与体验（Web 场景至少 1 条或说明 N/A）
- 主流浏览器/分辨率、空态/loading、关键文案与按钮可用性

### G. 性能（PRD 有 SLA、大数据量、导出/列表时评估）
- 分页/批量上限、响应时间可感知阈值

## 数量建议
- 简单功能（如单一按钮）：≥8 条（含至少 2 条非功能：弱网/稳定性/异常等）
- 中等模块（如表格+操作）：≥15 条
- 复杂流程：按 AC 逐条展开，不合并为「测所有场景」

## Mermaid 规则

### mermaid_review（评审逻辑图 — 必出，flowchart TB）
- **目的**：评审会快速过覆盖，不必逐条读表；一图看清主流程 + 测什么。
- **禁止 mindmap**；统一 `flowchart TB`。
- 上半：业务主流程 3～8 步（节点用 `(["步骤"]`)` 圆角或 `["步骤"]`）。
- 下半：subgraph 按 **类型**（功能/边界/弱网/稳定性/权限）分组，组内 `TC-xxx` 短标题。
- 文件末尾固定样式（必须原样附上）：
```
classDef root fill:#0284c7,stroke:#0369a1,color:#fff,stroke-width:2px
classDef mod fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e,stroke-width:1.5px
classDef tc fill:#fff,stroke:#cbd5e1,color:#334155,stroke-width:1px
classDef nf fill:#fef9c3,stroke:#eab308,color:#713f12,stroke-width:1px
classDef p0 fill:#fee2e2,stroke:#ef4444,color:#991b1b,stroke-width:1.5px
```
- 根节点 `:::root`，模块节点 `:::mod`，用例叶子 `:::tc`；弱网/稳定性组内节点 `:::nf`；P0 加 `:::p0`。

### mermaid_tree（测试覆盖树 — 必出，**禁止 mindmap**）
- **统一 `flowchart TB`** + subgraph 按模块分组；不用 mindmap（排版乱、难读）。
- 结构模板：
```
flowchart TB
  R(["测试范围：短标题"]):::root
  subgraph G1["模块A"]
    direction TB
    G1M["功能点说明"]:::mod
    TC001["TC-001 短标题"]:::tc
    G1M --> TC001
  end
  R --> G1M
  subgraph G2["非功能/网络稳定性"]
    direction TB
    ...
  end
  classDef root ...（同上 5 行 classDef）
```
- 每个 TC 独立节点 `["TC-xxx 短标题"]:::tc`；P0 用 `:::p0`；非功能用 `:::nf`。
- subgraph 标题 ≤12 字；单组 ≤8 个 TC，多了拆 subgraph。

## 写作要求
- 步骤用 1. 2. 3. 编号；期望结果可观测（UI 文案、状态、HTTP 码），禁止「系统正常」
- 测试数据写具体值或 N/A（附原因）
- 不要臆造 PRD 未提及的业务规则；缺口写入 assumptions
"""

CASE_SYSTEM_TABLE = """你是测试设计专家。根据 PRD / 验收标准生成**用例表**（本步不生成 Mermaid 图）。

输出格式（仅一个 JSON 对象，无 markdown 包裹）：
{
  "assumptions": "假设与缺口（markdown bullets，含「覆盖维度」）",
  "case_table_markdown": "用例表 markdown（含表头）",
  "message": "给用户的简短中文说明"
}

## 用例表表头（固定）
| 编号 | 模块 | 前置条件 | 步骤 | 测试数据 | 期望结果 | 优先级 | 类型 | 关联需求 ID | 风险/备注 |

- 优先级 P0/P1/P2；类型含：功能、边界、异常、权限、安全、弱网、稳定性、并发等
- Web 场景默认含弱网/稳定性用例；简单功能 ≥8 条，中等 ≥15 条
- TC-001 起连续编号；步骤与期望结果可执行、可判定
"""

CASE_SYSTEM_DIAGRAMS = f"""你是测试设计专家。根据**已给出的用例表**生成两张 Mermaid 图（flowchart TB，禁止 mindmap）。

输出格式（仅一个 JSON 对象）：
{{
  "mermaid_review": "评审概览图：主流程 + 按类型/模块分组的 TC",
  "mermaid_tree": "覆盖树：subgraph 按模块，叶子 TC-xxx",
  "message": "简短说明"
}}

规则：
- TC 编号必须与用例表完全一致，不得新增或遗漏
- 两张图文末均附以下 classDef（原样）：
{MERMAID_CLASSDEF}
- 根节点 :::root，模块 :::mod，用例 :::tc，非功能 :::nf，P0 :::p0
"""


def _sessions_dir(base: Path) -> Path:
    d = base / "case_sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_sessions(base: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    root = _sessions_dir(base)
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
            logger.warning("skip case session %s: %s", p, e)
    return out


def get_session(base: Path, session_id: str) -> Optional[Dict[str, Any]]:
    p = _sessions_dir(base) / f"{session_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_session(base: Path, payload: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    sid = session_id or str(uuid.uuid4())[:12]
    now = datetime.now().isoformat()
    doc = {
        "id": sid,
        "title": payload.get("title") or "未命名用例会话",
        "input_text": payload.get("input_text") or "",
        "assumptions": payload.get("assumptions") or "",
        "mermaid_review": payload.get("mermaid_review") or "",
        "mermaid_tree": payload.get("mermaid_tree") or "",
        "case_table_markdown": payload.get("case_table_markdown") or "",
        "message": payload.get("message") or "",
        "updated_at": now,
        "created_at": payload.get("created_at") or now,
    }
    p = _sessions_dir(base) / f"{sid}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def delete_session(base: Path, session_id: str) -> bool:
    p = _sessions_dir(base) / f"{session_id}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def _build_generation_prompt(
    input_text: str,
    title: Optional[str],
    messages: Optional[List[Dict[str, str]]],
    image_data_urls: Optional[List[str]],
    scope: Optional[str],
    excluded: Optional[str],
    priority_focus: Optional[str],
) -> str:
    parts: List[str] = []
    if title:
        parts.append(f"标题：{title}")
    if scope:
        parts.append(f"覆盖范围：{scope}")
    if excluded:
        parts.append(f"明确不测：{excluded}")
    if priority_focus:
        parts.append(f"优先级重点：{priority_focus}")
    for m in messages or []:
        role = "用户" if m.get("role") == "user" else "助手"
        parts.append(f"{role}：{m.get('content', '')}")
    if input_text and (not messages or messages[-1].get("content") != input_text):
        parts.append(f"用户：{input_text}")
    if image_data_urls:
        parts.append(f"（附带 {len(image_data_urls)} 张截图，请结合界面信息生成用例。）")
    parts.append("\n请输出 JSON（见系统说明）。")
    return "\n\n".join(parts)


def _parse_llm_case_json(resp) -> Dict[str, Any]:
    if resp.error or not (resp.content or "").strip():
        raise RuntimeError(resp.error or "模型返回空内容")
    try:
        return parse_llm_judge_json(resp.content)
    except ValueError as e:
        finish_reason = None
        raw = getattr(resp, "raw_response", None) or {}
        choices = raw.get("choices") or []
        if choices:
            finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            raise RuntimeError(
                "模型输出被截断（finish_reason=length），JSON 不完整；系统将自动重试分步生成"
            ) from e
        raise RuntimeError(f"无法解析模型 JSON：{e}") from e


async def _llm_json(
    client: LLMClient,
    prompt: str,
    system_message: str,
    *,
    max_tokens: int = 12000,
) -> Dict[str, Any]:
    resp = await client.call(
        prompt=prompt,
        system_message=system_message,
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        timeout_sec=CASE_GEN_TIMEOUT,
    )
    return _parse_llm_case_json(resp)


def _pack_case_result(
    parsed: Dict[str, Any],
    *,
    title: Optional[str],
    input_text: str,
) -> Dict[str, Any]:
    table = str(parsed.get("case_table_markdown") or "").strip()
    if not table or "| 编号 |" not in table:
        raise ValueError("生成结果缺少有效用例表")
    title_val = title or _guess_title(input_text)
    review_raw = str(parsed.get("mermaid_review") or "")
    tree_raw = str(parsed.get("mermaid_tree") or "")
    return {
        "assumptions": str(parsed.get("assumptions") or ""),
        "mermaid_review": normalize_mermaid(review_raw, title=title_val, case_table=table),
        "mermaid_tree": normalize_mermaid(tree_raw, title=title_val, case_table=table),
        "case_table_markdown": table,
        "message": str(parsed.get("message") or "用例已生成"),
        "title": title_val,
    }


async def _generate_cases_full(client: LLMClient, prompt: str, image_data_urls: Optional[List[str]]) -> Dict[str, Any]:
    if image_data_urls:
        resp = await client.call(
            prompt=prompt,
            system_message=CASE_SYSTEM,
            temperature=0.2,
            max_tokens=16000,
            response_format={"type": "json_object"},
            image_data_urls=image_data_urls,
            timeout_sec=CASE_GEN_TIMEOUT,
        )
        parsed = _parse_llm_case_json(resp)
    else:
        parsed = await _llm_json(client, prompt, CASE_SYSTEM, max_tokens=16000)
    return parsed


async def _generate_cases_split(
    client: LLMClient,
    prompt: str,
    image_data_urls: Optional[List[str]],
) -> Dict[str, Any]:
    """分两步：先表后图，降低单次 JSON 体积与超时概率。"""
    if image_data_urls:
        resp = await client.call(
            prompt=prompt,
            system_message=CASE_SYSTEM_TABLE,
            temperature=0.2,
            max_tokens=12000,
            response_format={"type": "json_object"},
            image_data_urls=image_data_urls,
            timeout_sec=CASE_GEN_TIMEOUT,
        )
        phase1 = _parse_llm_case_json(resp)
    else:
        phase1 = await _llm_json(client, prompt, CASE_SYSTEM_TABLE, max_tokens=12000)

    table = str(phase1.get("case_table_markdown") or "").strip()
    if not table:
        raise ValueError("分步生成：第一阶段未产出用例表")

    diagram_prompt = (
        f"{prompt}\n\n【已生成用例表】\n{table}\n\n"
        "请仅根据上表生成 mermaid_review 与 mermaid_tree，TC 编号必须与表一致。"
    )
    phase2 = await _llm_json(client, diagram_prompt, CASE_SYSTEM_DIAGRAMS, max_tokens=8000)
    merged = {**phase1, **phase2}
    return merged


async def generate_cases(
    input_text: str,
    title: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
    image_data_urls: Optional[List[str]] = None,
    scope: Optional[str] = None,
    excluded: Optional[str] = None,
    priority_focus: Optional[str] = None,
) -> Dict[str, Any]:
    if not (input_text or "").strip() and not messages:
        raise ValueError("请提供 PRD、用户故事或验收标准")

    try:
        client = LLMClient()
    except ValueError as e:
        raise ValueError(f"LLM 未配置: {e}") from e

    prompt = _build_generation_prompt(
        input_text, title, messages, image_data_urls, scope, excluded, priority_focus
    )

    last_err: Optional[Exception] = None
    for attempt in range(1, CASE_GEN_RETRIES + 1):
        use_split = attempt > 1
        mode = "分步(表→图)" if use_split else "一次性"
        try:
            logger.info("用例生成 第 %d/%d 次 mode=%s", attempt, CASE_GEN_RETRIES, mode)
            if use_split:
                parsed = await _generate_cases_split(client, prompt, image_data_urls)
            else:
                parsed = await _generate_cases_full(client, prompt, image_data_urls)
            return _pack_case_result(parsed, title=title, input_text=input_text)
        except Exception as e:
            last_err = e
            logger.warning("用例生成失败 第 %d/%d 次 mode=%s: %s", attempt, CASE_GEN_RETRIES, mode, e)
            if attempt < CASE_GEN_RETRIES:
                await asyncio.sleep(min(2.0 * attempt, 6.0))

    raise RuntimeError(
        f"用例生成失败（已重试 {CASE_GEN_RETRIES} 次，含分步生成）。最后错误：{last_err}"
    ) from last_err


def _guess_title(text: str) -> str:
    line = (text or "").strip().split("\n")[0][:40]
    return line or "用例设计"


def markdown_to_csv(case_table_markdown: str) -> str:
    """Simple markdown table → CSV for export."""
    lines = [ln.strip() for ln in (case_table_markdown or "").splitlines() if ln.strip()]
    rows = []
    for ln in lines:
        if ln.startswith("|") and not re.match(r"^\|\s*[-:]+\s*\|", ln):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            rows.append(",".join(f'"{c.replace(chr(34), chr(34)+chr(34))}"' for c in cells))
    return "\n".join(rows)
