"""
从 collected 字段 + cURL 生成 LLM-QAuto 测试套件 YAML（供配置助手 / 向导复用）。
"""

from __future__ import annotations

import copy
import json
import re
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "examples"

PROMPT_REWRITE_DIMS = [
    ("intent_fidelity", "意图保真", 0.25, "原始诉求完整保留、无曲解遗漏"),
    ("pos_neg_decouple", "正反向解耦", 0.20, "正向无否定词，反向无肯定诉求；比例类转正向构图"),
    ("format_compliance", "格式规范", 0.10, "含「正向提示词」「反向提示词」或约定格式"),
    ("professional_rewrite", "专业化改写", 0.15, "口语转商业摄影/构图等专业表达"),
    ("compliance_coverage", "电商合规", 0.15, "覆盖无文字/Logo/水印/促销标签等"),
    ("no_hallucination", "无臆造", 0.15, "不臆造颜色/材质/数量/改变产品本质的元素"),
]

GENERIC_DIMS = [
    ("content_quality", "内容质量", 0.4, "准确、完整、可读，无明显错误或胡编"),
    ("safety_compliance", "安全合规", 0.35, "无违法违规、歧视、隐私泄露或不当内容"),
    ("format_check", "格式规范", 0.25, "符合预期格式与字段齐全"),
]

IMAGE_GEN_VISION_PROMPT = (
    "你是视觉质检员。根据待评 prompt 与生成图片，评估图文一致性、画面质量、电商合规（无文字水印）。\n\n"
    "待评 prompt / 接口字段（含 lastPrompt、productName 等）：\n{{ output }}\n\n"
    '返回 JSON：{"score":0-10,"categories":[],"issues":[],"evidence":""}'
)

DEFAULT_IMAGE_MEDIA_URLS_PATH = "subTasks.0.images"


def parse_id_values(text: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return ["1914"]
    m = re.match(r"^(\d+)\s*[-–—]\s*(\d+)$", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= b and b - a <= 500:
            return [str(i) for i in range(a, b + 1)]
    parts = re.split(r"[\n,;|\s]+", t)
    return [p.strip() for p in parts if p.strip()]


def _tokenize_curl(rest: str) -> List[str]:
    try:
        return shlex.split(rest, posix=True)
    except ValueError:
        return rest.split()


def _strip_url_quotes(url: str) -> str:
    u = (url or "").strip()
    if len(u) >= 2 and u[0] == u[-1] and u[0] in ("'", '"'):
        return u[1:-1]
    return u


def is_parseable_curl(raw: str) -> bool:
    try:
        parse_browser_curl(raw)
        return True
    except ValueError:
        return False


def parse_browser_curl(raw: str) -> Dict[str, Any]:
    text = (raw or "").replace("\r\n", "\n").replace("\\\n", "").strip()
    if not text:
        raise ValueError("不是有效的 curl 命令")
    bare = re.match(r"^(https?://\S+)$", text, re.I)
    if bare:
        return {"url": _strip_url_quotes(bare.group(1)), "method": "GET", "headers": {}, "body": None}
    if not text.lower().startswith("curl"):
        raise ValueError("不是有效的 curl 命令")
    if re.search(r";\s*curl\b", text, re.I):
        parts = re.split(r";\s*(?=curl\b)", text, flags=re.I)
        text = parts[0].strip()

    rest = re.sub(r"^\s*curl(\.exe)?\s+", "", text, flags=re.I).strip()
    tokens = _tokenize_curl(rest)
    method = None
    body = None
    headers: Dict[str, str] = {}
    url = None
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request") and i + 1 < len(tokens):
            method = tokens[i + 1].upper()
            i += 2
            continue
        if t in ("-H", "--header") and i + 1 < len(tokens):
            hv = tokens[i + 1]
            idx = hv.find(":")
            if idx > 0:
                headers[hv[:idx].strip()] = hv[idx + 1 :].strip()
            i += 2
            continue
        if t in ("--data-raw", "--data", "--data-binary", "-d", "--json") and i + 1 < len(tokens):
            body = tokens[i + 1]
            if t == "--json" and not method:
                method = "POST"
            i += 2
            continue
        if t in ("-G", "--get"):
            method = "GET"
            i += 1
            continue
        if t.startswith("-") and t not in ("-X", "-H", "-d"):
            i += 1
            continue
        if re.match(r"^https?://", t, re.I):
            url = _strip_url_quotes(t)
        i += 1

    if not url:
        raise ValueError("未解析到 URL")
    if not method:
        method = "POST" if body else "GET"
    return {"url": url, "method": method, "headers": headers, "body": body}


def filter_curl_headers(raw: Dict[str, str]) -> Dict[str, str]:
    skip = {
        "host",
        "content-length",
        "connection",
        "accept-encoding",
        "origin",
        "referer",
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "cache-control",
        "pragma",
    }
    out: Dict[str, str] = {}
    auth = None
    for k, v in (raw or {}).items():
        lk = k.lower()
        if lk in skip:
            continue
        if lk == "authorization":
            auth = v
            continue
        if lk == "content-type":
            continue
        out[k] = v
    if auth and str(auth).strip():
        a = str(auth).strip()
        out["Authorization"] = a if re.match(r"^bearer\s+", a, re.I) else f"Bearer {a}"
    return out


def apply_env_headers(headers: Dict[str, str], use_env: bool = True) -> Dict[str, str]:
    h = dict(headers or {})
    if use_env:
        h["Authorization"] = "Bearer ${ZHIYUAN_BEARER_TOKEN}"
        if not any(k.lower() == "tenant-id" for k in h):
            h["tenant-id"] = "${TENANT_ID}"
    return h


def _curl_var_placeholder(name: str, value: Any) -> str:
    if name == "id" and (isinstance(value, int) or re.match(r"^\d+$", str(value))):
        return "{{ input.variables.id | int }}"
    return f"{{{{ input.variables.{name} }}}}"


def apply_curl_to_target(obj: Dict[str, Any], curl_text: str) -> None:
    parsed = parse_browser_curl(curl_text)
    url = parsed["url"]
    method = parsed["method"]
    body = parsed.get("body")
    parsed_url = urlparse(url)

    target = obj.setdefault("target", {"type": "api"})
    conn = target.setdefault("connector", {"name": "httpx", "config": {}})
    cfg = conn.setdefault("config", {})
    ifm = target.setdefault("input_formatter", {"name": "json_payload"})

    if method == "GET" and parsed_url.query:
        endpoint = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
        query_obj = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed_url.query).items()}
        template = {}
        vars_list = []
        for k, v in query_obj.items():
            template[k] = _curl_var_placeholder(k, v)
            nv = int(v) if isinstance(v, str) and v.isdigit() else v
            vars_list.append({"name": k, "type": "enum", "values": [nv]})
        ifm["template"] = template
        dg = obj.setdefault("data_generator", {})
        dg["strategy"] = "template_cartesian"
        dg["variables"] = vars_list
        dg["prompt_template"] = "{{ vars." + vars_list[0]["name"] + " }}" if vars_list else "{{ vars.id }}"
    else:
        endpoint = url.split("#")[0]
        if body and str(body).strip():
            if str(body).strip().startswith("@"):
                raise ValueError("不支持 @ 文件请求体")
            body_obj = json.loads(body)
            if isinstance(body_obj, dict) and not isinstance(body_obj, list):
                row = {k: v for k, v in body_obj.items() if v is None or not isinstance(v, (dict, list))}
                template = copy.deepcopy(body_obj)
                vars_list = []
                for k in row:
                    template[k] = _curl_var_placeholder(k, row[k])
                    nv = int(row[k]) if isinstance(row[k], str) and str(row[k]).isdigit() else row[k]
                    vars_list.append({"name": k, "type": "enum", "values": [nv]})
                ifm["template"] = template
                if vars_list:
                    dg = obj.setdefault("data_generator", {})
                    dg["strategy"] = "template_cartesian"
                    dg["variables"] = vars_list
                    keys = [v["name"] for v in vars_list]
                    dg["prompt_template"] = (
                        "{{ vars." + keys[0] + " }}"
                        if len(keys) == 1
                        else " / ".join(f"{{{{ vars.{k} }}}}" for k in keys)
                    )
            else:
                ifm["template"] = body_obj
        elif method == "GET":
            ifm["template"] = {}

    cfg["endpoint"] = endpoint
    cfg["method"] = method
    cfg["headers"] = filter_curl_headers(parsed.get("headers") or {})
    cfg.setdefault("timeout", 120)
    cfg.setdefault("retry", 2)
    cfg.setdefault("concurrency", 2)


def _batch_tail(ids: List[str]) -> str:
    skeleton = ",".join(f'"{i}":{{"score":0-10,"categories":[],"issues":[],"evidence":""}}' for i in ids)
    return (
        "【待评接口返回】（已按配置截取，可能是 JSON 或纯文本）\n{{ output }}\n\n"
        "只输出一个 JSON 对象（不要 markdown 代码块）：\n"
        f'{{"dimensions":{{{skeleton}}},"summary":{{"overall_comment":"","risk_flags":[]}}}}'
    )


def _ensure_skeleton(obj: Dict[str, Any]) -> None:
    obj.setdefault("meta", {})
    obj.setdefault("target", {"type": "api"})
    obj["target"].setdefault("connector", {"name": "httpx", "config": {}})
    obj["target"].setdefault("input_formatter", {"name": "json_payload"})
    obj["target"].setdefault("output_parser", {"name": "json_extractor", "path": "data"})
    obj.setdefault("data_generator", {"strategy": "template_cartesian", "variables": [], "sampling": {}})
    obj.setdefault("evaluation", {"aggregation_method": "weighted_average", "dimensions": []})
    obj.setdefault(
        "pass_criteria",
        {
            "global_criteria": {"min_total_score": 6.0},
            "dimensions": [],
            "statistical": {"confidence_level": 0.95, "min_sample_size": 1},
        },
    )


def _apply_id_values_to_generator(obj: Dict[str, Any], id_values: List[str]) -> None:
    dg = obj.setdefault("data_generator", {})
    vars_list = list(dg.get("variables") or [])
    names = {v.get("name") for v in vars_list if v.get("name")}
    target_name = "designTaskId" if "designTaskId" in names else ("id" if "id" in names else None)
    if target_name:
        for v in vars_list:
            if v.get("name") == target_name:
                v["values"] = id_values
    else:
        vars_list = _merge_vars(vars_list, [{"name": "id", "type": "enum", "values": id_values}])
    dg["variables"] = vars_list
    dg["sampling"] = {"total": len(id_values)}
    primary = target_name or "id"
    dg["prompt_template"] = f"{{{{ vars.{primary} }}}}"


def _merge_vars(existing: List[Dict], incoming: List[Dict]) -> List[Dict]:
    mp = {v["name"]: v for v in existing if v.get("name")}
    for v in incoming:
        n = v.get("name")
        if not n:
            continue
        if n in mp:
            mp[n] = {**mp[n], "values": v.get("values", mp[n].get("values"))}
        else:
            mp[n] = v
    return list(mp.values())


def scaffold_prompt_rewrite(collected: Dict[str, Any]) -> Dict[str, Any]:
    obj: Dict[str, Any] = {"target": {"type": "api"}}
    _ensure_skeleton(obj)
    apply_curl_to_target(obj, collected["target_curl"])
    obj["target"]["connector"]["config"]["headers"] = apply_env_headers(
        obj["target"]["connector"]["config"].get("headers", {}),
        collected.get("use_env_token", False),
    )

    obj["meta"]["name"] = collected.get("suite_name") or "prompt-rewrite-qc"
    obj["meta"]["version"] = "1.0.0"
    obj["meta"]["description"] = collected.get("suite_desc") or "帮写 Prompt L1 文本质检"

    obj["target"]["output_parser"]["path"] = collected.get("output_path") or "data"

    raw_field = collected.get("raw_prompt_field") or "rawPrompt"
    img_field = collected.get("image_type_field") or "imageType"
    id_values = parse_id_values(collected.get("id_values", "1914"))

    tpl = obj["target"]["input_formatter"].get("template") or {}
    if isinstance(tpl, dict):
        if raw_field not in tpl:
            tpl[raw_field] = f"{{{{ input.variables.{raw_field} }}}}"
        if img_field not in tpl:
            tpl[img_field] = f"{{{{ input.variables.{img_field} }}}}"
        if "site" not in tpl:
            tpl["site"] = "{{ input.variables.site }}"
        obj["target"]["input_formatter"]["template"] = tpl

    extra_vars = [
        {"name": "id", "type": "enum", "values": id_values},
        {"name": raw_field, "type": "enum", "values": [collected.get("sample_raw_prompt") or "要欧美模特，不要文字"]},
        {"name": img_field, "type": "enum", "values": [collected.get("sample_image_type") or "场景图"]},
        {"name": "site", "type": "enum", "values": [collected.get("sample_site") or "DE"]},
    ]
    if collected.get("include_product_name"):
        extra_vars.append(
            {
                "name": "productName",
                "type": "enum",
                "values": [collected.get("sample_product_name") or "锚点产品名"],
            }
        )
    obj["data_generator"]["variables"] = _merge_vars(obj["data_generator"].get("variables") or [], extra_vars)
    obj["data_generator"]["prompt_template"] = "{{ vars.id }}"
    obj["data_generator"]["sampling"] = {"total": len(id_values)}

    anchor = [
        f"【原始口语】{{{{ {raw_field} }}}}",
        f"【图类型】{{{{ {img_field} }}}}",
        "【站点】{{ site }}",
    ]
    if collected.get("include_product_name"):
        anchor.append("【产品锚点】{{ productName }}")

    lines = [
        f"{i + 1}. {d[0]}（{d[1]}，权重 {int(d[2] * 100)}%）：{d[3]}"
        for i, d in enumerate(PROMPT_REWRITE_DIMS)
    ]
    intro = (
        "你是 AI 帮写 Prompt 质检员。对比【原始口语】与【帮写 API 返回】，按维度 0～10 打分。\n"
        "硬门槛：intent_fidelity≥8.0、no_hallucination≥8.0、pos_neg_decouple≥7.5。\n\n"
        + "\n".join(anchor)
        + "\n\n【各维检查要点】\n"
        + "\n".join(lines)
    )
    dim_ids = [d[0] for d in PROMPT_REWRITE_DIMS]
    obj["evaluation"]["batch_llm"] = {
        "model": "gemini-3.1-pro-preview",
        "temperature": 0.08,
        "max_tokens": 4000,
        "max_judge_input_chars": 14000,
        "use_cache": True,
        "dimension_ids": dim_ids,
        "prompt_template": intro + "\n\n" + _batch_tail(dim_ids),
    }
    obj["evaluation"]["dimensions"] = [
        {"id": d[0], "name": d[1], "description": d[3], "weight": d[2], "evaluators": []}
        for d in PROMPT_REWRITE_DIMS
    ]
    obj["pass_criteria"] = {
        "global_criteria": {"min_total_score": float(collected.get("min_total_score") or 7.0)},
        "dimensions": [
            {"id": "intent_fidelity", "min_avg_score": 8.0},
            {"id": "no_hallucination", "min_avg_score": 8.0},
            {"id": "pos_neg_decouple", "min_avg_score": 7.5},
        ],
        "statistical": {"confidence_level": 0.95, "min_sample_size": 1},
    }
    return obj


def scaffold_listing(collected: Dict[str, Any]) -> Dict[str, Any]:
    example_path = EXAMPLES_DIR / "de_copyinfo_regenerate_listing_qc_rubric_batch.yaml"
    if not example_path.exists():
        raise FileNotFoundError(f"Listing 模板不存在: {example_path}")
    with open(example_path, "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
    apply_curl_to_target(obj, collected["target_curl"])
    obj["target"]["connector"]["config"]["headers"] = apply_env_headers(
        obj["target"]["connector"]["config"].get("headers", {}),
        collected.get("use_env_token", False),
    )
    obj["meta"]["name"] = collected.get("suite_name") or obj["meta"].get("name")
    if collected.get("suite_desc"):
        obj["meta"]["description"] = collected["suite_desc"]
    if collected.get("id_values"):
        id_values = parse_id_values(collected["id_values"])
        vars_list = obj.get("data_generator", {}).get("variables") or []
        for v in vars_list:
            if v.get("name") == "id":
                v["values"] = id_values
        obj.setdefault("data_generator", {})["sampling"] = {"total": len(id_values)}
    if collected.get("async_poll") and collected.get("poll_curl"):
        poll = parse_browser_curl(collected["poll_curl"])
        pu = urlparse(poll["url"])
        obj["target"]["connector"]["config"]["invoke_poll"] = {
            "enabled": True,
            "endpoint": f"{pu.scheme}://{pu.netloc}{pu.path}",
            "method": poll.get("method") or "GET",
            "query": {"id": "{{ input.variables.id }}"},
            "ready_path": collected.get("ready_path") or "data.title",
            "timeout": 30,
        }
    return obj


def scaffold_image_gen(collected: Dict[str, Any]) -> Dict[str, Any]:
    obj: Dict[str, Any] = {"target": {"type": "api"}}
    _ensure_skeleton(obj)
    apply_curl_to_target(obj, collected["target_curl"])
    obj["target"]["connector"]["config"]["headers"] = apply_env_headers(
        obj["target"]["connector"]["config"].get("headers", {}),
        collected.get("use_env_token", False),
    )
    obj["meta"]["name"] = collected.get("suite_name") or "image-gen-qc"
    obj["meta"]["version"] = "1.0.0"
    obj["meta"]["description"] = collected.get("suite_desc") or "生图质量测评"
    obj["target"]["output_parser"] = {
        "name": "json_extractor",
        "path": collected.get("output_path") or "data",
        "keys": ["lastPrompt", "productName"],
        "content_mode": "image",
        "media": {
            "urls_path": collected.get("media_urls_path") or DEFAULT_IMAGE_MEDIA_URLS_PATH,
            "download": True,
            "max_images": 4,
        },
    }
    id_values = parse_id_values(collected.get("id_values", "1914"))
    _apply_id_values_to_generator(obj, id_values)
    obj["evaluation"]["dimensions"] = [
        {
            "id": "image_delivery",
            "name": "图片交付",
            "weight": 0.3,
            "evaluators": [
                {
                    "type": "image_rule",
                    "rules": [
                        {"name": "至少一张图", "condition": "media_count >= 1", "severity": "error"},
                        {"name": "图片落盘", "condition": "all_images_ok", "severity": "error"},
                    ],
                }
            ],
        },
        {
            "id": "vision_quality",
            "name": "画面质量与一致",
            "weight": 0.7,
            "evaluators": [
                {
                    "type": "vision_llm",
                    "model": "gpt-4o",
                    "temperature": 0.1,
                    "max_tokens": 1800,
                    "max_images": 2,
                    "prompt_template": IMAGE_GEN_VISION_PROMPT,
                }
            ],
        },
    ]
    obj["pass_criteria"]["global_criteria"]["min_total_score"] = 6.0
    obj["pass_criteria"]["dimensions"] = [{"id": "vision_quality", "min_avg_score": 6.0}]
    return obj


def scaffold_generic(collected: Dict[str, Any]) -> Dict[str, Any]:
    obj: Dict[str, Any] = {"target": {"type": "api"}}
    _ensure_skeleton(obj)
    apply_curl_to_target(obj, collected["target_curl"])
    obj["target"]["connector"]["config"]["headers"] = apply_env_headers(
        obj["target"]["connector"]["config"].get("headers", {}),
        collected.get("use_env_token", False),
    )
    obj["meta"]["name"] = collected.get("suite_name") or "generic-api-qc"
    obj["meta"]["version"] = "1.0.0"
    obj["meta"]["description"] = collected.get("suite_desc") or "通用接口质检"
    obj["target"]["output_parser"]["path"] = collected.get("output_path") or "data"
    id_values = parse_id_values(collected.get("id_values", "1914"))
    obj["data_generator"]["variables"] = _merge_vars(
        obj["data_generator"].get("variables") or [],
        [{"name": "id", "type": "enum", "values": id_values}],
    )
    obj["data_generator"]["sampling"] = {"total": len(id_values)}
    dim_ids = [d[0] for d in GENERIC_DIMS]
    lines = [f"{i + 1}. {d[0]}（{d[1]}，权重 {int(d[2] * 100)}%）：{d[3]}" for i, d in enumerate(GENERIC_DIMS)]
    intro = "你是内容质检员。请根据接口返回，一次性完成下列全部维度的评分（0～10）。\n\n【各维检查要点】\n" + "\n".join(lines)
    obj["evaluation"]["batch_llm"] = {
        "model": "gemini-3.1-pro-preview",
        "temperature": 0.1,
        "max_tokens": 3000,
        "max_judge_input_chars": 14000,
        "use_cache": True,
        "dimension_ids": dim_ids,
        "prompt_template": intro + "\n\n" + _batch_tail(dim_ids),
    }
    obj["evaluation"]["dimensions"] = [
        {"id": d[0], "name": d[1], "description": d[3], "weight": d[2], "evaluators": []} for d in GENERIC_DIMS
    ]
    obj["pass_criteria"]["global_criteria"]["min_total_score"] = float(collected.get("min_total_score") or 6.0)
    return obj


def required_fields_for_scene(scene: str) -> List[str]:
    base = ["scene", "target_curl", "suite_name"]
    extra = {
        "prompt_rewrite_qc": [],
        "listing_qc": [],
        "image_gen": [],
        "generic": [],
    }
    return base + extra.get(scene, [])


def missing_fields(collected: Dict[str, Any]) -> List[str]:
    scene = collected.get("scene") or ""
    missing = [f for f in required_fields_for_scene(scene) if not collected.get(f)]
    if scene == "listing_qc" and collected.get("async_poll") and not collected.get("poll_curl"):
        missing.append("poll_curl")
    return missing


def scaffold_config(collected: Dict[str, Any]) -> str:
    scene = collected.get("scene")
    if not scene:
        raise ValueError("缺少 scene")
    miss = missing_fields(collected)
    if miss:
        raise ValueError("仍缺少字段: " + ", ".join(miss))

    if scene == "listing_qc":
        obj = scaffold_listing(collected)
    elif scene == "prompt_rewrite_qc":
        obj = scaffold_prompt_rewrite(collected)
    elif scene == "image_gen":
        obj = scaffold_image_gen(collected)
    elif scene == "generic":
        obj = scaffold_generic(collected)
    else:
        raise ValueError(f"未知场景: {scene}")

    return yaml.dump(obj, allow_unicode=True, sort_keys=False, width=120)


def detect_curl_in_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(?is)\bcurl\b.+", text)
    if not m:
        return None
    block = m.group(0).strip()
    lines = block.splitlines()
    kept: List[str] = []
    for i, line in enumerate(lines):
        ls = line.strip()
        if i == 0:
            kept.append(line)
            continue
        if (
            ls.endswith("\\")
            or ls.startswith("-")
            or ls.startswith("--")
            or re.search(r"https?://", ls)
            or ls.startswith("'")
            or ls.startswith('"')
            or ls.startswith("{")
            or ls.startswith("}")
        ):
            kept.append(line)
        elif re.match(r"^[\u4e00-\u9fff]", ls):
            break
        else:
            kept.append(line)
    out = "\n".join(kept).strip()
    return out if out.lower().startswith("curl") else None
