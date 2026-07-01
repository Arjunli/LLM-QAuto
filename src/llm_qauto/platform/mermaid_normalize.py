"""Normalize / repair LLM-generated Mermaid for case design charts."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

MERMAID_CLASSDEF = """classDef root fill:#0284c7,stroke:#0369a1,color:#fff,stroke-width:2px
classDef mod fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e,stroke-width:1.5px
classDef tc fill:#fff,stroke:#cbd5e1,color:#334155,stroke-width:1px
classDef nf fill:#fef9c3,stroke:#eab308,color:#713f12,stroke-width:1px
classDef p0 fill:#fee2e2,stroke:#ef4444,color:#991b1b,stroke-width:1.5px"""

_TC_ID_RE = re.compile(r"TC-\d+", re.I)
_TC_LINE_RE = re.compile(r"^\s*\[?(TC-\d+)\]?\s*(.*)$", re.I)
_ROOT_RE = re.compile(r"root\s*\(\((.+?)\)\)|root\s*\((.+?)\)", re.I)


def _escape_label(text: str, max_len: int = 40) -> str:
    s = re.sub(r'["#\[\](){}<>|]', " ", str(text or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s or "节点"


def _node_id(tc_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", tc_id.upper()) or "TC"


def mindmap_to_flowchart(source: str, root_title: str = "测试范围") -> str:
    """Convert invalid flat mindmap (common LLM output) to flowchart TB."""
    text = (source or "").strip()
    if not re.match(r"^mindmap\b", text, re.I):
        return text

    root_label = root_title
    modules: List[Tuple[str, List[Tuple[str, str]]]] = []
    current_mod = "用例覆盖"
    bucket: List[Tuple[str, str]] = []

    for line in text.splitlines()[1:]:
        stripped = line.strip()
        if not stripped:
            continue

        root_m = _ROOT_RE.search(stripped)
        if root_m:
            root_label = (root_m.group(1) or root_m.group(2) or "").strip() or root_title
            continue

        tc_m = _TC_LINE_RE.match(stripped)
        if tc_m:
            bucket.append((tc_m.group(1).upper(), tc_m.group(2).strip()))
            continue

        if not _TC_ID_RE.search(stripped) and len(stripped) <= 24:
            if bucket:
                modules.append((current_mod, bucket))
                bucket = []
            current_mod = stripped

    if bucket:
        modules.append((current_mod, bucket))

    if not modules:
        return flowchart_from_table("", root_title)

    lines = ["flowchart TB", f'  R(["{_escape_label(root_label)}"]):::root']
    for i, (mod_name, items) in enumerate(modules):
        gid = f"G{i + 1}"
        mid = f"M{i + 1}"
        mod_label = _escape_label(mod_name, 14)
        lines.append(f'  subgraph {gid}["{mod_label}"]')
        lines.append("    direction TB")
        lines.append(f'    {mid}["{mod_label}"]:::mod')
        for tc_id, desc in items:
            nid = _node_id(tc_id)
            label = _escape_label(f"{tc_id} {desc}", 38)
            lines.append(f'    {nid}["{label}"]:::tc')
            lines.append(f"    {mid} --> {nid}")
        lines.append("  end")
        lines.append(f"  R --> {mid}")

    lines.append(MERMAID_CLASSDEF)
    return "\n".join(lines)


def flowchart_from_table(case_table: str, title: str = "测试范围") -> str:
    """Build a minimal coverage tree from the case table when Mermaid is missing/invalid."""
    rows: List[Tuple[str, str, str]] = []
    for line in (case_table or "").splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.match(r"^\|\s*[-:]+\s*\|", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        tc_id = cells[0].strip()
        if not _TC_ID_RE.fullmatch(tc_id):
            continue
        module = cells[1] if len(cells) > 1 else "用例"
        step_hint = cells[3][:20] if len(cells) > 3 else ""
        rows.append((tc_id.upper(), module, step_hint))

    if not rows:
        return f"flowchart TB\n  R([\"{_escape_label(title)}\"]):::root\n{MERMAID_CLASSDEF}"

    by_mod: dict[str, List[Tuple[str, str]]] = {}
    for tc_id, mod, hint in rows:
        by_mod.setdefault(mod or "用例", []).append((tc_id, hint))

    lines = ["flowchart TB", f'  R(["{_escape_label(title)}"]):::root']
    for i, (mod_name, items) in enumerate(by_mod.items()):
        gid = f"G{i + 1}"
        mid = f"M{i + 1}"
        mod_label = _escape_label(mod_name, 14)
        lines.append(f'  subgraph {gid}["{mod_label}"]')
        lines.append("    direction TB")
        lines.append(f'    {mid}["{mod_label}"]:::mod')
        for tc_id, hint in items:
            nid = _node_id(tc_id)
            label = _escape_label(f"{tc_id} {hint}", 38)
            lines.append(f'    {nid}["{label}"]:::tc')
            lines.append(f"    {mid} --> {nid}")
        lines.append("  end")
        lines.append(f"  R --> {mid}")

    lines.append(MERMAID_CLASSDEF)
    return "\n".join(lines)


def normalize_mermaid(
    source: Optional[str],
    *,
    title: str = "",
    case_table: str = "",
) -> str:
    s = (source or "").strip()
    root = title or "测试范围"

    if not s:
        return flowchart_from_table(case_table, root) if case_table else ""

    if re.match(r"^mindmap\b", s, re.I):
        s = mindmap_to_flowchart(s, root)

    if not re.match(r"^(flowchart|graph)\b", s, re.I):
        if case_table:
            return flowchart_from_table(case_table, root)
        return s

    if "classDef root" not in s:
        s = s + "\n" + MERMAID_CLASSDEF

    return s
