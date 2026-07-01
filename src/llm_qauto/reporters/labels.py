"""报告中的维度展示名（id → 显示名称）。"""

from typing import Any, Dict, Iterable, List, Union

from ..models import TestReport


def build_dimension_display_names(dimensions: Iterable[Any]) -> Dict[str, str]:
    """从 evaluation.dimensions 构建 id → 显示名 映射。"""
    out: Dict[str, str] = {}
    for d in dimensions or []:
        if isinstance(d, dict):
            did = d.get("id")
            name = d.get("name")
        else:
            did = getattr(d, "id", None)
            name = getattr(d, "name", None)
        if not did:
            continue
        sid = str(did).strip()
        label = str(name).strip() if name is not None and str(name).strip() else sid
        out[sid] = label
    return out


def dimension_names_from_report(report: TestReport) -> Dict[str, str]:
    meta = report.suite_meta or {}
    names = meta.get("dimension_display_names")
    if isinstance(names, dict) and names:
        return {str(k): str(v) for k, v in names.items()}
    out: Dict[str, str] = {}
    for stat in report.dimension_stats or []:
        if stat.dimension_id:
            out[stat.dimension_id] = (
                stat.dimension_name.strip()
                if getattr(stat, "dimension_name", "") and stat.dimension_name.strip()
                else stat.dimension_id
            )
    return out


def dimension_display_label(
    report: TestReport,
    dim_id: str,
    *,
    names: Dict[str, str] | None = None,
) -> str:
    if not dim_id:
        return dim_id
    lookup = names if names is not None else dimension_names_from_report(report)
    return lookup.get(dim_id) or dim_id


def format_dimension_labels(
    report: TestReport,
    dim_ids: Union[str, Iterable[str], None],
    *,
    names: Dict[str, str] | None = None,
) -> str:
    if dim_ids is None:
        return ""
    if isinstance(dim_ids, str):
        return dimension_display_label(report, dim_ids, names=names)
    lookup = names if names is not None else dimension_names_from_report(report)
    return ", ".join(dimension_display_label(report, d, names=lookup) for d in dim_ids)
