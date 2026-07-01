"""
测试执行引擎 - 核心编排逻辑
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from .models import (
    TestSuiteConfig, TestInput, TestOutput, TestCase,
    DimensionResult, DimensionStats, CategoryStats,
    TestReport, PassCriteriaResult, TestStatus, ReportCaseRollup,
)
from .plugins import load_plugin, JudgeContext
from .plugins.connectors import _traverse_dotted
from .statistics import compute_confidence_interval, wilson_score_interval
from .reporters.labels import build_dimension_display_names
from .media import (
    extract_and_persist_media,
    resolve_content_mode,
    relative_media_path,
)


logger = logging.getLogger(__name__)


def _is_transport_connectivity_failure(error_msg: str) -> bool:
    """
    判断连接器错误是否属于「网络/传输层不可达」，而非 HTTP 业务错误或解析错误。
    若为真，则不应继续批量调用与评委，避免无意义报告。
    """
    if not error_msg or not str(error_msg).strip():
        return False
    e = str(error_msg).lower()
    needles = (
        "connecterror",
        "connection refused",
        "connection reset",
        "connection aborted",
        "connection error",
        "name or service not known",
        "getaddrinfo",
        "temporary failure in name resolution",
        "network is unreachable",
        "no route to host",
        "connect timeout",
        "connection timed out",
        "ssl handshake",
        "certificate verify failed",
        "certificate has expired",
        "errno 110",   # ETIMEDOUT
        "errno 111",   # ECONNREFUSED
        "errno 113",   # EHOSTUNREACH
        "cannot connect",
        "failed to establish",
        "failed to resolve",
        "nodename nor servname",
        "gaierror",
        "newconnectionerror",
        "remote end closed",
        "unexpected_eof",
        "unexpected eof",
        "proxy",
        "tunnel connection failed",
    )
    return any(n in e for n in needles)


def _json_biz_code_ok(code: Any) -> bool:
    """常见 { code, msg, data } 中 code 视为成功的取值（不含的 body 视为不检查）。"""
    if code is None:
        return True
    if code in (0, "0", 200, "200"):
        return True
    return False


def _parsed_listing_has_content(content: str, keys: Optional[List[str]]) -> bool:
    """output_parser.keys 白名单解析后是否至少有一个非空字段。"""
    if not keys:
        return bool((content or "").strip())
    try:
        data = json.loads(content or "")
    except json.JSONDecodeError:
        return bool((content or "").strip())
    if not isinstance(data, dict):
        return False
    for k in keys:
        v = data.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, (list, dict)) and len(v) == 0:
            continue
        return True
    return False


def _regenerate_payload_is_async_ack(raw_data: Any) -> bool:
    """copy-info/regenerate 在 status=process 等场景常返回 { code:0, data:true }。"""
    if not isinstance(raw_data, dict):
        return False
    payload = raw_data.get("data")
    return payload is True or payload is False


def _render_poll_query(query_template: Any, test_input: TestInput) -> Dict[str, Any]:
    from jinja2 import Template

    if isinstance(query_template, dict):
        tpl = Template(json.dumps(query_template, ensure_ascii=False))
        rendered = tpl.render(input=test_input)
        return json.loads(rendered)
    if isinstance(query_template, str):
        tpl = Template(query_template)
        rendered = tpl.render(input=test_input)
        return json.loads(rendered) if rendered.strip().startswith("{") else {}
    return {}


def _summarize_body_for_log(body: Any, max_len: int = 600) -> str:
    try:
        text = json.dumps(body, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(body)
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _poll_response_diag(body: Dict[str, Any]) -> Dict[str, Any]:
    """从 copy-info GET 响应提取便于日志与快速失败判断的摘要。"""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    workflows = data.get("workflows") if isinstance(data.get("workflows"), list) else []
    wf_counts: Dict[str, int] = {}
    wf_failed_msgs: List[str] = []
    for w in workflows:
        if not isinstance(w, dict):
            continue
        st = str(w.get("workflowStatus") or "unknown")
        wf_counts[st] = wf_counts.get(st, 0) + 1
        if st in ("failed", "error") and w.get("errorMsg"):
            wf_failed_msgs.append(f"{w.get('workflowNode')}:{w.get('errorMsg')}")
    title = data.get("title")
    title_s = "" if title is None else str(title)
    return {
        "code": body.get("code"),
        "msg": body.get("msg"),
        "data_status": data.get("status"),
        "title_len": len(title_s.strip()),
        "title_preview": title_s.strip()[:100],
        "workflow_counts": wf_counts,
        "workflow_errors": wf_failed_msgs[:3],
    }


def _poll_terminal_error(body: Dict[str, Any], diag: Dict[str, Any]) -> Optional[str]:
    """工作流/业务态明确失败时立即结束轮询。"""
    data_status = str(diag.get("data_status") or "").lower()
    if data_status in ("failed", "error", "fail"):
        return f"copy-info 任务状态为 {diag.get('data_status')!r}，已停止等待"
    wf_counts = diag.get("workflow_counts") or {}
    if wf_counts.get("failed") or wf_counts.get("error"):
        errs = diag.get("workflow_errors") or []
        detail = f"；{errs[0]}" if errs else ""
        return f"工作流节点失败 {wf_counts}{detail}"
    return None


def _invoke_poll_active(poll_cfg: Dict[str, Any]) -> bool:
    """是否执行 regenerate 受理后的 GET Listing。默认关闭，设 QAUTO_INVOKE_POLL=1 且 yaml enabled 才开启。"""
    if not poll_cfg or not poll_cfg.get("enabled"):
        return False
    flag = os.environ.get("QAUTO_INVOKE_POLL", "0").strip().lower()
    return flag in ("1", "true", "yes")


async def _fetch_listing_after_async_ack(
    poll_cfg: Dict[str, Any],
    test_input: TestInput,
    headers: Dict[str, Any],
    *,
    case_id: str = "",
    live_hook=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    regenerate 已返回 HTTP 响应且 data:true 时，立即单次 GET 拉 Listing（默认不额外等待）。
    仅当配置 max_wait_sec>0 时，在查询前阻塞等待；不轮询。
    """
    import httpx
    from jinja2 import Template

    endpoint_tpl = poll_cfg.get("endpoint") or poll_cfg.get("url")
    if not endpoint_tpl:
        return None, "invoke_poll 未配置 endpoint"

    method = (poll_cfg.get("method") or "GET").upper()
    ready_path = (poll_cfg.get("ready_path") or "data.title").strip()
    max_wait_sec = float(poll_cfg.get("max_wait_sec") or poll_cfg.get("wait_sec") or 0)
    ui_tick_sec = float(poll_cfg.get("progress_tick_sec") or 5)

    endpoint = Template(str(endpoint_tpl)).render(input=test_input)
    # 去掉 endpoint 上残留的 ?id= 占位，统一走 query（与浏览器 curl 的 query 一致）
    if "?" in endpoint:
        endpoint = endpoint.split("?", 1)[0]
    query = _render_poll_query(poll_cfg.get("query") or poll_cfg.get("query_template") or {}, test_input)
    vid = test_input.variables.get("id")
    if vid is not None and str(vid).strip() != "" and "id" not in query:
        query = {**query, "id": vid}

    req_timeout = float(poll_cfg.get("timeout") or 30)
    loop = asyncio.get_event_loop()
    started = loop.time()

    if max_wait_sec > 0:
        logger.info(
            "[invoke_fetch] 异步受理已响应，额外等待 %ss 后查询 Listing case_id=%s",
            max_wait_sec,
            case_id or test_input.id,
        )
        while True:
            elapsed = loop.time() - started
            if elapsed >= max_wait_sec:
                break
            if live_hook:
                live_hook(
                    "lifecycle",
                    {
                        "phase": "invoke_wait",
                        "message": (
                            f"额外等待 Listing（已 {elapsed:.0f}s / {max_wait_sec:.0f}s）"
                        ),
                        "case_id": case_id or test_input.id,
                    },
                )
            await asyncio.sleep(min(ui_tick_sec, max_wait_sec - elapsed))
    else:
        logger.info(
            "[invoke_fetch] 异步受理已响应，立即查询 Listing case_id=%s fetch=%s ready_path=%s",
            case_id or test_input.id,
            endpoint,
            ready_path,
        )

    async with httpx.AsyncClient(timeout=httpx.Timeout(req_timeout)) as client:
        try:
            if method == "GET":
                resp = await client.get(endpoint, headers=headers, params=query)
            else:
                resp = await client.request(
                    method=method, url=endpoint, headers=headers, json=query
                )
        except httpx.TimeoutException:
            logger.warning(
                "[invoke_fetch] 查询 Listing 超时 case_id=%s endpoint=%s timeout=%ss",
                case_id or test_input.id,
                endpoint,
                req_timeout,
            )
            return None, f"查询 Listing 超时（>{req_timeout}s）"
        except Exception as e:
            logger.warning(
                "[invoke_fetch] 查询 Listing 异常 case_id=%s endpoint=%s err=%s",
                case_id or test_input.id,
                endpoint,
                e,
            )
            return None, f"查询 Listing 异常：{e}"

        body_text = resp.text or ""
        logger.info(
            "[invoke_fetch] 查询响应 case_id=%s http=%s preview=%r",
            case_id or test_input.id,
            resp.status_code,
            body_text[:600],
        )

        if resp.status_code in (401, 403):
            return None, (
                f"查询 Listing 鉴权失败 HTTP {resp.status_code}：{body_text[:300]}"
            )
        if resp.status_code >= 300:
            return None, (
                f"查询 Listing HTTP {resp.status_code}：{body_text[:300]!r}"
            )

        try:
            body = resp.json()
        except json.JSONDecodeError:
            return None, f"查询 Listing 响应不是 JSON：{body_text[:300]!r}"

        if isinstance(body, dict) and "code" in body and not _json_biz_code_ok(
            body.get("code")
        ):
            return None, (
                f"查询 Listing 业务失败 code={body.get('code')!r} msg={body.get('msg')!r}"
            )

        diag = _poll_response_diag(body) if isinstance(body, dict) else {}
        logger.info(
            "[invoke_fetch] 查询摘要 case_id=%s diag=%s",
            case_id or test_input.id,
            json.dumps(diag, ensure_ascii=False),
        )

        term_err = (
            _poll_terminal_error(body, diag) if isinstance(body, dict) else None
        )
        if term_err:
            return None, term_err

        node = (
            _traverse_dotted(body, ready_path)
            if ready_path and isinstance(body, dict)
            else body
        )
        if node is not None and str(node).strip() != "":
            logger.info(
                "[invoke_fetch] Listing 就绪 case_id=%s path=%s title_preview=%r",
                case_id or test_input.id,
                ready_path,
                diag.get("title_preview"),
            )
            return body, None

    waited = f"（已额外等待 {max_wait_sec:.0f}s）" if max_wait_sec > 0 else ""
    pending = str(diag.get("data_status") or "").lower() == "pending"
    hint = (
        "任务仍在服务端生成中（workflows 未结束），请增大 invoke_poll.max_wait_sec 或稍后重试。"
        if pending
        else "请确认 regenerate 参数与 copy-info id 是否正确。"
    )
    return None, (
        f"regenerate 已受理(data:true)，但查询 Listing 仍无有效内容{waited}"
        f"（ready_path={ready_path!r}，"
        f"data.status={diag.get('data_status')!r}，"
        f"workflows={diag.get('workflow_counts')!r}）。{hint}"
    )


def _preview_json(obj: Any, max_len: int = 1400) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        text = str(obj)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


async def probe_suite_connectivity(config: TestSuiteConfig) -> Dict[str, Any]:
    """
    编辑配置时单次探测：用首条测试数据调用被测接口，验证连通性与基本响应。
    不执行评委、不写入报告。
    """
    from .config_loader import _resolve_env_vars

    warnings: List[str] = []
    connector = None

    try:
        generator = load_plugin("generator", config.data_generator.strategy)
        await generator.initialize({})
        inputs = generator.generate(config.data_generator.model_dump())
        if not inputs:
            return {
                "success": False,
                "reachable": False,
                "has_content": False,
                "error": "无法生成测试入参：请在「测试数据取值」至少填一组 variables（或 JSON 批量行）",
                "message": "缺少测试数据",
                "warnings": [],
            }

        test_input = inputs[0]
        conn_cfg = _resolve_env_vars(dict(config.target.connector.config or {}))
        endpoint = str(conn_cfg.get("endpoint") or "").strip()
        method = str(conn_cfg.get("method") or "POST").upper()
        if not endpoint:
            return {
                "success": False,
                "reachable": False,
                "has_content": False,
                "error": "未配置被测接口 URL（target.connector.config.endpoint）",
                "message": "缺少接口地址",
                "warnings": [],
            }

        connector_type = config.target.connector.name
        connector = load_plugin("connector", connector_type)
        await connector.initialize(conn_cfg)

        try:
            formatted = connector.format_input(test_input, config.target.input_formatter)
        except Exception as exc:
            return {
                "success": False,
                "reachable": False,
                "has_content": False,
                "error": f"入参模板渲染失败: {exc}",
                "message": "入参模板有误",
                "variables_used": dict(test_input.variables or {}),
                "warnings": [],
            }

        resp = await connector.call(formatted)
        http_st = resp.get("status")
        latency_ms = resp.get("latency_ms")
        err = resp.get("error")
        raw_data = resp.get("data")

        result: Dict[str, Any] = {
            "success": False,
            "reachable": False,
            "has_content": False,
            "http_status": http_st,
            "latency_ms": latency_ms,
            "method": method,
            "endpoint": endpoint,
            "request_body_preview": _preview_json(formatted, 900),
            "variables_used": dict(test_input.variables or {}),
            "response_preview": _preview_json(raw_data if raw_data is not None else err, 1400),
            "parsed_preview": "",
            "message": "",
            "poll": None,
            "warnings": warnings,
            "error": None,
        }

        if err:
            result["error"] = str(err)
            result["message"] = "接口调用失败"
            if _is_transport_connectivity_failure(str(err)):
                result["message"] = "网络不可达或连接失败"
            return result

        result["reachable"] = bool(http_st is not None and int(http_st) < 300)

        biz_err: Optional[str] = None
        if isinstance(raw_data, dict) and "code" in raw_data and not _json_biz_code_ok(raw_data.get("code")):
            biz_err = f"业务 code={raw_data.get('code')} msg={raw_data.get('msg')!r}"

        poll_cfg = conn_cfg.get("invoke_poll") or {}
        poll_info: Optional[Dict[str, Any]] = None
        if (
            result["reachable"]
            and not biz_err
            and _invoke_poll_active(poll_cfg)
            and _regenerate_payload_is_async_ack(raw_data)
        ):
            headers = _resolve_env_vars(dict(conn_cfg.get("headers") or {}))
            polled, poll_err = await _fetch_listing_after_async_ack(
                poll_cfg,
                test_input,
                headers,
                case_id=test_input.id,
            )
            poll_info = {"latency_ms": None, "error": poll_err}
            if polled is not None:
                raw_data = polled
                resp = {**resp, "data": polled}
                poll_info["response_preview"] = _preview_json(polled, 900)
                poll_info["title_preview"] = (
                    _poll_response_diag(polled).get("title_preview") if isinstance(polled, dict) else None
                )
            elif poll_err:
                warnings.append(str(poll_err))
            result["poll"] = poll_info

        if biz_err:
            warnings.append(biz_err)
            if not _regenerate_payload_is_async_ack(raw_data):
                result["error"] = biz_err
                result["message"] = (
                    "接口可达，但业务返回失败（常见：Token 过期、tenant-id 缺失）"
                    if result["reachable"]
                    else "业务调用失败"
                )
                return result

        try:
            parsed = connector.parse_output(resp, config.target.output_parser)
            result["parsed_preview"] = (parsed or "")[:1400]
            parser_keys = config.target.output_parser.keys
            if parser_keys and _parsed_listing_has_content(parsed or "", parser_keys):
                result["has_content"] = True
            elif parsed and str(parsed).strip() and not parser_keys:
                result["has_content"] = True
        except Exception as exc:
            warnings.append(f"输出解析失败: {exc}")

        if not result["reachable"]:
            result["error"] = f"HTTP {http_st}"
            result["message"] = "HTTP 非成功状态"
            return result

        result["success"] = True
        if _regenerate_payload_is_async_ack(resp.get("data")) and not result.get("poll"):
            result["message"] = "regenerate 已受理（data:true），主接口连通正常"
        elif result["has_content"]:
            result["message"] = "接口可达，已返回可解析的正文"
        elif warnings:
            result["message"] = "接口可达，但有待确认项（见 warnings）"
        else:
            result["message"] = "接口可达，HTTP 与 JSON 正常"
        return result
    finally:
        if connector:
            try:
                await connector.cleanup()
            except Exception:
                pass


class TestEngine:
    """通用测试执行引擎"""
    
    def __init__(self, config: TestSuiteConfig):
        self.config = config
        self.connector = None
        self.generator = None
        self.evaluators = {}  # dimension_id -> List[evaluator instances]
        self.batch_llm_evaluator = None
        self.batch_llm_config: Optional[Dict] = None
        self.cases: List[TestCase] = []
        self.start_time: Optional[datetime] = None
        self.run_id: str = ""
        self.artifacts_dir: Optional[str] = None
        
    async def initialize(self):
        """初始化所有组件"""
        suite = self.config.meta.get("name", "未命名项目")
        endpoint = (self.config.target.connector.config or {}).get("endpoint", "")
        dim_ids = [d.id for d in self.config.evaluation.dimensions]

        # 加载连接器
        connector_type = self.config.target.connector.name
        logger.info(
            "[init] 套件=%r connector=%s endpoint=%s dimensions=%s",
            suite,
            connector_type,
            endpoint,
            dim_ids,
        )
        self.connector = load_plugin("connector", connector_type)
        await self.connector.initialize(self.config.target.connector.config)
        
        # 加载数据生成器
        generator_type = self.config.data_generator.strategy
        self.generator = load_plugin("generator", generator_type)
        await self.generator.initialize({})
        logger.info("[init] generator=%s", generator_type)
        
        # 单次全评（evaluation.batch_llm）
        batch_cfg = getattr(self.config.evaluation, "batch_llm", None)
        if batch_cfg:
            self.batch_llm_config = batch_cfg
            self.batch_llm_evaluator = load_plugin("evaluator", "llm_batch")
            await self.batch_llm_evaluator.initialize(batch_cfg)
            batch_dim_ids = batch_cfg.get("dimension_ids") or dim_ids
            if not batch_cfg.get("dimension_ids"):
                batch_cfg["dimension_ids"] = batch_dim_ids
            logger.info(
                "[init] 评委模式=batch_llm model=%s dims=%s excerpt_mode=%s",
                batch_cfg.get("model"),
                batch_dim_ids,
                batch_cfg.get("excerpt_mode"),
            )
        else:
            per_dim = sum(len(d.evaluators) for d in self.config.evaluation.dimensions)
            logger.info("[init] 评委模式=per_dimension evaluators=%d", per_dim)

        # 加载各维度评判器（batch 模式下维度 evaluators 通常为空）
        for dim in self.config.evaluation.dimensions:
            self.evaluators[dim.id] = []
            for eval_config in dim.evaluators:
                eval_type = eval_config.get("type")
                if eval_type:
                    evaluator = load_plugin("evaluator", eval_type)
                    await evaluator.initialize(eval_config)
                    self.evaluators[dim.id].append((evaluator, eval_config))
                    logger.info(
                        "[init] 维度评委 dim=%s type=%s model=%s",
                        dim.id,
                        eval_type,
                        eval_config.get("model"),
                    )
    
    async def cleanup(self):
        """清理资源"""
        if self.connector:
            await self.connector.cleanup()
        if self.batch_llm_evaluator:
            await self.batch_llm_evaluator.cleanup()
        for evaluators in self.evaluators.values():
            for evaluator, _ in evaluators:
                await evaluator.cleanup()
    
    def _dimension_name_map(self) -> Dict[str, str]:
        return build_dimension_display_names(self.config.evaluation.dimensions)

    def _dim_label(self, dim_id: str) -> str:
        return self._dimension_name_map().get(dim_id, dim_id)

    def generate_inputs(self) -> List[TestInput]:
        """生成测试输入"""
        dg = self.config.data_generator.model_dump()
        sampling = dg.get("sampling") or {}
        variables = [v.get("name") for v in (dg.get("variables") or []) if v.get("name")]
        inputs = self.generator.generate(dg)
        logger.info(
            "[inputs] 生成 %d 条用例 variables=%s sampling.total=%s seed=%s",
            len(inputs),
            variables,
            sampling.get("total"),
            sampling.get("seed"),
        )
        if inputs:
            logger.info(
                "[inputs] 首条 case_id=%s vars=%s",
                inputs[0].id,
                dict(inputs[0].variables or {}),
            )
        return inputs

    def _suite_has_llm_evaluator(self) -> bool:
        """套件是否配置了 type=llm / vision_llm 的评委（用于活动日志明示是否走大模型）。"""
        try:
            for dim in self.config.evaluation.dimensions:
                for ec in dim.evaluators:
                    if not isinstance(ec, dict):
                        continue
                    t = str(ec.get("type") or "").strip().lower()
                    if t in ("llm", "vision_llm"):
                        return True
            if getattr(self.config.evaluation, "batch_llm", None):
                return True
        except Exception:
            pass
        return False

    def _first_llm_eval_model_label(self) -> str:
        """首个 LLM / 视觉评委配置的 model，用于日志简述。"""
        try:
            for dim in self.config.evaluation.dimensions:
                for ec in dim.evaluators:
                    if not isinstance(ec, dict):
                        continue
                    t = str(ec.get("type") or "").strip().lower()
                    if t not in ("llm", "vision_llm"):
                        continue
                    m = ec.get("model") or ec.get("name")
                    if m:
                        return str(m)
        except Exception:
            pass
        return ""

    async def _probe_target_connectivity(self, inputs: List[TestInput]) -> Optional[str]:
        """
        使用首条用例发起单次调用，判断是否为网络/传输层不可达。
        返回错误文案表示应中止整次运行；返回 None 则继续正式批量。
        """
        cfg = self.config.target.connector.config or {}
        if cfg.get("skip_connectivity_check"):
            return None
        if not inputs:
            return None
        try:
            formatted = self.connector.format_input(
                inputs[0],
                self.config.target.input_formatter,
            )
        except Exception as e:
            logger.warning("[probe] 首条用例格式化失败，跳过连通性预检: %s", e)
            return None

        resp = await self.connector.call(formatted)
        err = resp.get("error")
        if not err:
            logger.info(
                "[probe] 被测接口可达 endpoint=%s http=%s latency_ms=%s",
                cfg.get("endpoint"),
                resp.get("status"),
                resp.get("latency_ms"),
            )
            return None
        es = str(err)
        if _is_transport_connectivity_failure(es):
            logger.error(
                "[probe] 被测接口连通性失败，中止批量任务 endpoint=%s err=%s",
                cfg.get("endpoint"),
                es,
            )
            return es
        logger.info(
            "[probe] 首包非传输层错误，继续批量 endpoint=%s err=%s",
            cfg.get("endpoint"),
            es[:400],
        )
        return None

    def _build_connectivity_abort_report(self, probe_err: str) -> TestReport:
        """接口不可达时返回最小报告（无样本、无评委）。"""
        end = datetime.now()
        start = self.start_time or end
        crit = PassCriteriaResult(
            criteria_id="target_connectivity",
            description="被测接口可达性（首包探测）",
            passed=False,
            actual_value=probe_err[:800],
            expected_value="可建立连接并完成调用",
            details=str(probe_err)[:2000],
        )
        return TestReport(
            run_id=self.run_id,
            project_name=self.config.meta.get("name", "未命名项目"),
            start_time=start,
            end_time=end,
            status=TestStatus.ERROR,
            total_cases=0,
            passed_cases=0,
            failed_cases=0,
            pass_rate=0.0,
            dimension_stats=[],
            criteria_results=[crit],
            suite_meta=dict(self.config.meta or {}),
            aggregation_method=self.config.evaluation.aggregation_method,
            cases=[],
            failed_examples=[],
            disputed_cases=[],
            summary=(
                "运行已中止：被测接口首包探测失败（网络或传输层不可达），"
                "未执行批量调用与评委，不生成完整评测报告。\n"
                f"详情: {probe_err}"
            ),
            recommendations=[
                "请检查 connector.endpoint、网络/VPN/防火墙、DNS、TLS 与超时；"
                f"连接器错误：{probe_err}"
            ],
            abort_reason="connectivity",
        )
    
    async def run_batch(
        self, 
        inputs: List[TestInput],
        progress_callback=None,
        live_hook=None,
    ) -> List[TestCase]:
        """批量执行测试"""
        cases = []
        
        # 批量调用被测AI
        batch_size = self.config.target.connector.config.get("concurrency", 5)
        logger.info(
            "[invoke] 开始批量调用 total=%d concurrency=%d batches=%d",
            len(inputs),
            batch_size,
            (len(inputs) + batch_size - 1) // max(batch_size, 1),
        )
        
        for i in range(0, len(inputs), batch_size):
            batch_inputs = inputs[i:i + batch_size]
            logger.info(
                "[invoke] 批次 %d/%d size=%d",
                i // batch_size + 1,
                (len(inputs) + batch_size - 1) // max(batch_size, 1),
                len(batch_inputs),
            )
            
            # 格式化输入
            formatted_inputs = [
                self.connector.format_input(
                    inp, 
                    self.config.target.input_formatter
                ) for inp in batch_inputs
            ]
            
            # 批量调用
            responses = await self.connector.call_batch(formatted_inputs)
            
            endpoint_hint = str(
                self.config.target.connector.config.get("endpoint") or ""
            )

            # 解析输出并创建TestCase
            for inp, resp in zip(batch_inputs, responses):
                err = resp.get("error")
                raw_data = resp.get("data")
                http_st = resp.get("status")

                if err:
                    logger.warning(
                        "[invoke] 连接器返回错误 case_id=%s http_status=%s endpoint=%s error=%s",
                        inp.id,
                        http_st,
                        endpoint_hint,
                        err,
                    )
                    output = TestOutput(
                        content="",
                        error=err,
                        latency_ms=resp.get("latency_ms", 0),
                        model_version=None,
                    )
                else:
                    biz_err: Optional[str] = None
                    if isinstance(raw_data, dict) and "code" in raw_data:
                        bc = raw_data.get("code")
                        if not _json_biz_code_ok(bc):
                            preview = json.dumps(raw_data, ensure_ascii=False)
                            if len(preview) > 700:
                                preview = preview[:680] + "…"
                            logger.warning(
                                "[invoke] 业务状态非成功（body 内 code，HTTP 可能仍为 2xx）"
                                " case_id=%s endpoint=%s http_status=%s body_code=%r msg=%r preview=%s",
                                inp.id,
                                endpoint_hint,
                                http_st,
                                bc,
                                raw_data.get("msg"),
                                preview,
                            )
                            biz_err = (
                                f"业务接口失败 HTTP={http_st} code={bc} "
                                f"msg={raw_data.get('msg')!r}"
                            )

                    parser_dump = self.config.target.output_parser.model_dump()
                    poll_cfg = (
                        self.config.target.connector.config.get("invoke_poll") or {}
                    )
                    if not biz_err and isinstance(raw_data, dict):
                        logger.info(
                            "[invoke] 被测接口返回 case_id=%s http=%s preview=%s",
                            inp.id,
                            http_st,
                            _summarize_body_for_log(raw_data),
                        )

                    if (
                        _invoke_poll_active(poll_cfg)
                        and not biz_err
                        and _regenerate_payload_is_async_ack(raw_data)
                    ):
                        logger.info(
                            "[invoke] regenerate 已响应(data=true)，立即查询 Listing case_id=%s",
                            inp.id,
                        )
                        from .config_loader import _resolve_env_vars

                        headers = _resolve_env_vars(
                            dict(
                                self.config.target.connector.config.get("headers") or {}
                            )
                        )
                        polled, poll_err = await _fetch_listing_after_async_ack(
                            poll_cfg,
                            inp,
                            headers,
                            case_id=inp.id,
                            live_hook=live_hook,
                        )
                        if poll_err:
                            biz_err = poll_err
                        elif polled is not None:
                            raw_data = polled
                            resp = {**resp, "data": polled}

                    content = self.connector.parse_output(
                        resp,
                        self.config.target.output_parser,
                    )
                    if not biz_err:
                        keys = parser_dump.get("keys")
                        if keys and not _parsed_listing_has_content(content, keys):
                            preview = (content or "")[:400]
                            biz_err = (
                                "被测接口未返回可评 Listing 正文（解析后字段均为空）。"
                                "常见原因：regenerate 仅返回 data:true 异步受理，需配置 "
                                "connector.config.invoke_poll（单次 GET）；或需调大 max_wait_sec。"
                                f" 解析预览: {preview!r}"
                            )
                            logger.warning(
                                "[invoke] Listing 正文为空 case_id=%s preview=%s",
                                inp.id,
                                preview,
                            )

                    media_list = await extract_and_persist_media(
                        raw_data if isinstance(raw_data, dict) else None,
                        parser_dump,
                        inp.id,
                        self.artifacts_dir,
                    )
                    mode = resolve_content_mode(parser_dump, content, media_list)
                    output = TestOutput(
                        content=content,
                        content_mode=mode,
                        media=media_list,
                        raw_response=raw_data,
                        latency_ms=resp.get("latency_ms", 0),
                        model_version=None,
                        error=biz_err,
                    )
                
                case = TestCase(
                    id=inp.id,
                    input=inp,
                    output=output
                )
                cases.append(case)

                if live_hook:
                    live_hook("invoke", {
                        "case_id": case.id,
                        "done": len(cases),
                        "total": len(inputs),
                        "latency_ms": round(case.output.latency_ms, 2),
                        "error": case.output.error,
                        "output_chars": len(case.output.content or ""),
                        "content_mode": case.output.content_mode,
                        "media_count": len(case.output.media or []),
                    })
            
            if progress_callback:
                self._safe_progress(progress_callback, len(cases), len(inputs), "invoke")

        err_cases = sum(1 for c in cases if c.output.error)
        logger.info(
            "[invoke] 调用完成 total=%d invoke_error=%d ok=%d",
            len(cases),
            err_cases,
            len(cases) - err_cases,
        )
        
        return cases
    
    @staticmethod
    def _safe_progress(progress_callback, current: int, total: int, phase: str = ""):
        if not progress_callback:
            return
        try:
            progress_callback(current, total, phase)
        except TypeError:
            progress_callback(current, total)

    async def _evaluate_invoke_failed_case(self, case: TestCase) -> None:
        """
        被测接口已失败（传输层或业务 body.code）时不再调用评委插件，避免无谓的 LLM/火山调用。
        为各维度写入占位结果供统计与报告使用。
        """
        err = case.output.error or "被测接口调用失败"
        case.failed_dimensions = []
        for dim in self.config.evaluation.dimensions:
            evs = self.evaluators.get(dim.id, [])
            if not evs and not self.batch_llm_evaluator:
                case.dimension_results[dim.id] = []
                continue
            eval_type = (
                "llm_batch"
                if self.batch_llm_evaluator
                else evs[0][1].get("type", "unknown")
            )
            stub = DimensionResult(
                dimension_id=dim.id,
                evaluator_type=eval_type,
                passed=False,
                score=0.0,
                categories=["invoke_error"],
                issues=[str(err)],
                evidence=(case.output.content or "")[:2000],
                confidence=1.0,
                judgment_time_ms=0.0,
                metadata={
                    "skipped_judge": True,
                    "reason": "invoke_or_business_error",
                },
            )
            case.dimension_results[dim.id] = [stub]
            case.failed_dimensions.append(dim.id)
        case.aggregated_score = 0.0
        case.passed = False

    async def evaluate_cases(
        self, 
        cases: List[TestCase],
        progress_callback=None,
        live_hook=None,
    ) -> List[TestCase]:
        """评判所有测试用例"""
        mode = "batch_llm" if self.batch_llm_evaluator else "per_dimension"
        logger.info(
            "[evaluate] 开始评判 cases=%d mode=%s model=%s",
            len(cases),
            mode,
            (self.batch_llm_config or {}).get("model") or self._first_llm_eval_model_label(),
        )

        for idx, case in enumerate(cases):
            if case.output.error:
                logger.info(
                    "[evaluate] 被测接口已失败，跳过评委（不调用 LLM）case_id=%s error=%s",
                    case.id,
                    case.output.error,
                )
                await self._evaluate_invoke_failed_case(case)
                if progress_callback:
                    self._safe_progress(progress_callback, idx + 1, len(cases), "evaluate")
                if live_hook:
                    live_hook("evaluate", {
                        "case_id": case.id,
                        "done": idx + 1,
                        "total": len(cases),
                        "passed": False,
                        "failed_dimensions": list(case.failed_dimensions),
                        "skipped_judge": True,
                        "llm_called": False,
                        "llm_configured": self._suite_has_llm_evaluator(),
                    })
                continue

            if self.batch_llm_evaluator and self.batch_llm_config:
                context = JudgeContext(
                    test_input=case.input,
                    test_output=case.output,
                    previous_results=[],
                    global_config=self.config.model_dump(),
                    artifacts_dir=self.artifacts_dir,
                )
                batch_results = await self.batch_llm_evaluator.judge_all(
                    case.output.content,
                    self.batch_llm_config,
                    context,
                )
                case.failed_dimensions = []
                for dim in self.config.evaluation.dimensions:
                    result = batch_results.get(dim.id)
                    if result is None:
                        logger.warning(
                            "[evaluate] 全评 JSON 缺少维度 dim=%s case_id=%s",
                            dim.id,
                            case.id,
                        )
                        result = DimensionResult(
                            dimension_id=dim.id,
                            evaluator_type="llm_batch",
                            passed=False,
                            score=0.0,
                            categories=["judge_error"],
                            issues=[f"单次全评未返回维度 {dim.id}"],
                            evidence="",
                            confidence=0.0,
                            judgment_time_ms=0.0,
                        )
                    result.dimension_id = dim.id
                    case.dimension_results[dim.id] = [result]
                    if not result.passed:
                        case.failed_dimensions.append(dim.id)
            else:
                for dim in self.config.evaluation.dimensions:
                    dim_results = []
                    failed_in_dimension = False

                    for evaluator, eval_config in self.evaluators.get(dim.id, []):
                        context = JudgeContext(
                            test_input=case.input,
                            test_output=case.output,
                            previous_results=dim_results,
                            global_config=self.config.model_dump(),
                            artifacts_dir=self.artifacts_dir,
                        )

                        result = await evaluator.judge(
                            case.output.content,
                            eval_config,
                            context,
                        )
                        result.dimension_id = dim.id
                        dim_results.append(result)

                        if dim.fail_fast and not result.passed:
                            failed_in_dimension = True
                            case.failed_dimensions.append(dim.id)
                            break

                    case.dimension_results[dim.id] = dim_results
            
            # 聚合维度结果得到最终判定 / 写入综合分（门禁 global_min_score 依赖 aggregated_score）
            case.aggregated_score = self._aggregate_case_score(case)
            case.passed = len(case.failed_dimensions) == 0

            logger.info(
                "[evaluate] case_id=%s passed=%s score=%.2f failed_dims=%s",
                case.id,
                case.passed,
                case.aggregated_score,
                case.failed_dimensions or [],
            )
            
            if progress_callback:
                self._safe_progress(progress_callback, idx + 1, len(cases), "evaluate")

            if live_hook:
                llm_suite = self._suite_has_llm_evaluator()
                live_hook("evaluate", {
                    "case_id": case.id,
                    "done": idx + 1,
                    "total": len(cases),
                    "passed": case.passed,
                    "failed_dimensions": list(case.failed_dimensions),
                    "llm_called": llm_suite,
                    "llm_configured": llm_suite,
                    "batch_llm": bool(self.batch_llm_evaluator),
                })

        passed_n = sum(1 for c in cases if c.passed)
        logger.info(
            "[evaluate] 评判完成 passed=%d/%d",
            passed_n,
            len(cases),
        )
        
        return cases
    
    def compute_stats(self, cases: List[TestCase]) -> List[DimensionStats]:
        """计算维度统计"""
        stats = []
        
        name_map = self._dimension_name_map()
        for dim in self.config.evaluation.dimensions:
            dim_id = dim.id
            
            # 收集该维度的所有结果
            results = []
            for case in cases:
                if dim_id in case.dimension_results:
                    # 取最后一个评判器的结果作为主要结果
                    results.append(case.dimension_results[dim_id][-1])
            
            if not results:
                continue
            
            # 基础统计
            scores = [r.score for r in results]
            passed_count = sum(1 for r in results if r.passed)
            
            # 类别分布统计
            category_counts: Dict[str, int] = {}
            for r in results:
                for cat in r.categories:
                    category_counts[cat] = category_counts.get(cat, 0) + 1
            
            total = len(results)
            category_stats = []
            for cat, count in category_counts.items():
                ci = wilson_score_interval(count, total, confidence=0.95)
                category_stats.append(CategoryStats(
                    category=cat,
                    count=count,
                    percentage=count / total * 100,
                    confidence_interval=ci
                ))
            
            # 失败原因统计
            fail_reasons: Dict[str, int] = {}
            for r in results:
                if not r.passed:
                    for issue in r.issues:
                        fail_reasons[issue] = fail_reasons.get(issue, 0) + 1
            
            dim_stats = DimensionStats(
                dimension_id=dim_id,
                dimension_name=name_map.get(dim_id, dim_id),
                total_cases=total,
                passed_cases=passed_count,
                failed_cases=total - passed_count,
                pass_rate=passed_count / total * 100,
                avg_score=sum(scores) / len(scores),
                min_score=min(scores),
                max_score=max(scores),
                std_score=float(__import__('numpy').std(scores)) if len(scores) > 1 else 0,
                category_distribution=category_stats,
                fail_reasons=fail_reasons
            )
            stats.append(dim_stats)
        
        return stats

    def _truncate_for_report(self, text: Optional[str], limit: int) -> str:
        if text is None:
            return ""
        if limit <= 0 or len(text) <= limit:
            return text
        return text[: max(0, limit - 20)].rstrip() + "\n…[已截断]"

    def _extract_parsed_fields(
        self, content: str, parser_keys: Optional[List[str]]
    ) -> Dict[str, Any]:
        keys = list(parser_keys or [])
        if not keys or not (content or "").strip():
            return {}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        return {k: data.get(k) for k in keys if k in data}

    def _build_case_rollups(self, cases: List[TestCase]) -> List[ReportCaseRollup]:
        """拼装 JSON 报告中逐条用例摘要（预览长度可由环境变量控制）."""
        preview = int(os.environ.get("QAUTO_REPORT_OUTPUT_PREVIEW_CHARS", "1600"))
        ev_cap = int(os.environ.get("QAUTO_REPORT_EVIDENCE_PREVIEW_CHARS", "1200"))
        raw_cap = int(os.environ.get("QAUTO_REPORT_RAW_PREVIEW_CHARS", "2400"))
        judge_cap = int(os.environ.get("QAUTO_REPORT_JUDGE_EXCERPT_CHARS", "8000"))
        parser_dump = self.config.target.output_parser.model_dump()
        parser_keys = list(parser_dump.get("keys") or [])
        rollout: List[ReportCaseRollup] = []

        batch_cfg = (
            dict(self.config.evaluation.batch_llm)
            if self.config.evaluation.batch_llm
            else {}
        )

        for case in cases:
            out = case.output.content or ""
            jt_total = sum(
                r.judgment_time_ms
                for seq in case.dimension_results.values()
                for r in seq
            )

            dims_summary: Dict[str, Dict[str, Any]] = {}
            for dim_id, seq in case.dimension_results.items():
                if not seq:
                    continue
                last = seq[-1]
                ev = self._truncate_for_report(last.evidence, ev_cap)
                dims_summary[dim_id] = {
                    "evaluator_type": last.evaluator_type,
                    "passed": last.passed,
                    "score": last.score,
                    "categories": last.categories,
                    "issues": list(last.issues),
                    "evidence": ev,
                    "confidence": last.confidence,
                    "judgment_time_ms": last.judgment_time_ms,
                    "metadata": dict(last.metadata or {}),
                    "evaluators_in_chain": len(seq),
                }

            media_paths: List[str] = []
            if self.artifacts_dir:
                for m in case.output.media or []:
                    if m.local_path:
                        media_paths.append(
                            relative_media_path(m.local_path, self.artifacts_dir)
                        )

            parsed_fields = self._extract_parsed_fields(out, parser_keys)
            judge_excerpt = ""
            if out.strip() and (batch_cfg or self._suite_has_llm_evaluator()):
                from .plugins.evaluators import build_listing_judge_excerpt

                judge_excerpt = build_listing_judge_excerpt(out, batch_cfg or {})

            raw = case.output.raw_response
            invoke_raw_preview = (
                _summarize_body_for_log(raw, raw_cap)
                if raw is not None
                else ""
            )

            rollout.append(
                ReportCaseRollup(
                    case_id=case.id,
                    passed=case.passed,
                    aggregated_score=float(case.aggregated_score),
                    input_prompt=str(case.input.prompt or ""),
                    input_variables=dict(case.input.variables or {}),
                    invoke_latency_ms=float(case.output.latency_ms or 0.0),
                    output_error=case.output.error,
                    content_mode=str(case.output.content_mode or "text"),
                    output_char_count=len(out),
                    output_preview=self._truncate_for_report(out, preview),
                    media_count=len(case.output.media or []),
                    media_preview_paths=media_paths,
                    judgment_latency_ms_total=float(jt_total),
                    failed_dimensions=list(case.failed_dimensions),
                    dimensions=dims_summary,
                    output_parser_keys=parser_keys,
                    parsed_fields=parsed_fields,
                    judge_excerpt=self._truncate_for_report(judge_excerpt, judge_cap),
                    invoke_raw_preview=invoke_raw_preview,
                )
            )
        return rollout

    def _aggregate_case_score(self, case: TestCase) -> float:
        """
        综合各维度分值（默认与 compute_stats 一致：维度内取评判链最后一个结果的 score）。
        """
        dims = self.config.evaluation.dimensions
        method = (self.config.evaluation.aggregation_method or "weighted_average").strip().lower()

        weighted_terms: List[float] = []
        weights: List[float] = []
        flat_scores: List[float] = []

        for dim in dims:
            seq = case.dimension_results.get(dim.id)
            if not seq:
                continue
            s = float(seq[-1].score)
            w = float(dim.weight if dim.weight is not None else 1.0)
            flat_scores.append(s)
            weighted_terms.append(s * w)
            weights.append(w)

        if not flat_scores:
            return 0.0

        if method == "min":
            return min(flat_scores)
        if method == "max":
            return max(flat_scores)
        if method == "sum":
            return sum(flat_scores)
        # weighted_average 及未知方法均按加权平均处理
        tw = sum(weights)
        return sum(weighted_terms) / tw if tw > 0 else 0.0

    def check_pass_criteria(
        self, 
        cases: List[TestCase],
        stats: List[DimensionStats]
    ) -> List[PassCriteriaResult]:
        """检查通过标准"""
        results = []
        criteria_config = self.config.pass_criteria
        
        # 全局检查
        global_criteria = criteria_config.global_criteria
        if global_criteria.min_total_score is not None and len(cases) > 0:
            avg_score = sum(c.aggregated_score for c in cases) / len(cases)
            passed = avg_score >= global_criteria.min_total_score
            results.append(PassCriteriaResult(
                criteria_id="global_min_score",
                description="全局平均分门槛",
                passed=passed,
                actual_value=avg_score,
                expected_value=global_criteria.min_total_score,
                details=f"平均得分: {avg_score:.2f}"
            ))
        
        # 维度检查
        stats_map = {s.dimension_id: s for s in stats}
        
        for dim_criteria in criteria_config.dimensions:
            dim_id = dim_criteria.id
            dim_stat = stats_map.get(dim_id)
            
            if not dim_stat:
                continue
            
            # 平均分检查
            dim_label = self._dim_label(dim_id)
            if dim_criteria.min_avg_score is not None:
                passed = dim_stat.avg_score >= dim_criteria.min_avg_score
                results.append(PassCriteriaResult(
                    criteria_id=f"{dim_id}_min_avg",
                    description=f"{dim_label}维度平均分",
                    passed=passed,
                    actual_value=dim_stat.avg_score,
                    expected_value=dim_criteria.min_avg_score,
                    details=f"维度「{dim_label}」平均得分: {dim_stat.avg_score:.2f}"
                ))
            
            # 失败率检查
            if dim_criteria.max_fail_rate is not None:
                fail_rate = 1 - dim_stat.pass_rate / 100
                passed = fail_rate <= dim_criteria.max_fail_rate
                results.append(PassCriteriaResult(
                    criteria_id=f"{dim_id}_max_fail_rate",
                    description=f"{dim_label}维度失败率",
                    passed=passed,
                    actual_value=fail_rate,
                    expected_value=dim_criteria.max_fail_rate,
                    details=f"失败率: {fail_rate:.2%}"
                ))
            
            # 类别分布检查
            for target in dim_criteria.category_distribution:
                cat_stat = next(
                    (s for s in dim_stat.category_distribution if s.category == target.category),
                    None
                )
                
                if not cat_stat:
                    continue
                
                percentage = cat_stat.percentage
                passed = True
                details = f"{target.category}: {percentage:.1f}%"
                
                if target.min_percent is not None and percentage < target.min_percent:
                    passed = False
                    details += f" (低于最小{target.min_percent}%)"
                
                if target.max_percent is not None and percentage > target.max_percent:
                    passed = False
                    details += f" (超过最大{target.max_percent}%)"
                    if target.fail_if_exceed:
                        details += " [关键指标]"
                
                results.append(PassCriteriaResult(
                    criteria_id=f"{dim_id}_category_{target.category}",
                    description=f"{dim_label}类别{target.category}占比",
                    passed=passed,
                    actual_value=percentage,
                    expected_value=f"{target.min_percent or 0}-{target.max_percent or '∞'}%",
                    details=details
                ))
        
        return results
    
    async def run(
        self,
        run_id: Optional[str] = None,
        progress_callback=None,
        live_hook=None,
        artifacts_dir: Optional[str] = None,
    ) -> TestReport:
        """执行完整测试流程"""
        self.run_id = run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        self.artifacts_dir = artifacts_dir
        if self.artifacts_dir:
            Path(self.artifacts_dir).mkdir(parents=True, exist_ok=True)

        logger.info(
            "[run] 开始 run_id=%s project=%r artifacts=%s",
            self.run_id,
            self.config.meta.get("name", "未命名项目"),
            self.artifacts_dir,
        )
        
        try:
            # 1. 初始化
            await self.initialize()
            if live_hook:
                live_hook("lifecycle", {"phase": "ready", "message": "组件初始化完成"})

            # 2. 生成输入
            inputs = self.generate_inputs()
            if live_hook:
                live_hook("lifecycle", {
                    "phase": "inputs_ready",
                    "message": f"已生成 {len(inputs)} 条用例输入",
                    "total": len(inputs),
                })

            # 2b. 首包连通性预检（避免接口不可达时仍跑完全部用例并生成「伪报告」）
            if live_hook:
                live_hook("lifecycle", {
                    "phase": "probing",
                    "message": "正在探测被测接口可达性…",
                })
            probe_err = await self._probe_target_connectivity(inputs)
            if probe_err:
                logger.error(
                    "[run] 连通性预检失败，中止 run_id=%s err=%s",
                    self.run_id,
                    probe_err,
                )
                if live_hook:
                    live_hook("lifecycle", {
                        "phase": "connectivity_failed",
                        "message": probe_err[:500],
                    })
                return self._build_connectivity_abort_report(probe_err)

            # 3. 执行调用
            if live_hook:
                live_hook("lifecycle", {"phase": "invoking", "message": "正在调用被测模型…"})
            self.cases = await self.run_batch(inputs, progress_callback, live_hook)

            # 4. 评判
            if live_hook:
                eval_msg = "正在评判输出…"
                if self._suite_has_llm_evaluator():
                    ml = self._first_llm_eval_model_label()
                    eval_msg = (
                        f"正在调用评判大模型对输出打分（{ml}）…"
                        if ml
                        else "正在调用评判大模型对输出打分…"
                    )
                live_hook("lifecycle", {"phase": "evaluating", "message": eval_msg})
            self.cases = await self.evaluate_cases(self.cases, progress_callback, live_hook)

            # 5. 统计
            if live_hook:
                live_hook("lifecycle", {"phase": "aggregating", "message": "聚合统计与门禁…"})
            stats = self.compute_stats(self.cases)
            
            # 6. 检查通过标准
            criteria_results = self.check_pass_criteria(self.cases, stats)
            failed_gates = [c for c in criteria_results if not c.passed]
            if failed_gates:
                for g in failed_gates:
                    logger.warning(
                        "[gate] 未通过 run_id=%s criteria=%s actual=%s expected=%s %s",
                        self.run_id,
                        g.criteria_id,
                        g.actual_value,
                        g.expected_value,
                        g.details,
                    )
            else:
                logger.info("[gate] 全部放行线通过 run_id=%s gates=%d", self.run_id, len(criteria_results))
            
            # 7. 收集失败示例（每类保留前3个）
            failed_examples = [c for c in self.cases if not c.passed][:20]
            
            # 8. 收集争议样本（置信度低的）
            disputed_cases = []
            for case in self.cases:
                for dim_results in case.dimension_results.values():
                    if dim_results and dim_results[-1].confidence < 0.7:
                        disputed_cases.append(case)
                        break
            disputed_cases = disputed_cases[:10]
            
            # 9. 生成报告
            all_passed = all(r.passed for r in criteria_results)
            status = TestStatus.PASSED if all_passed else TestStatus.FAILED
            
            passed_count = sum(1 for c in self.cases if c.passed)

            if live_hook:
                live_hook("lifecycle", {
                    "phase": "completed",
                    "message": f"测试完成：通过 {passed_count}/{len(self.cases)}",
                    "passed_cases": passed_count,
                    "total_cases": len(self.cases),
                })
            
            suite_meta = dict(self.config.meta or {})
            _pd = self.config.target.output_parser.model_dump()
            suite_meta["output_parser"] = {
                "path": _pd.get("path"),
                "keys": list(_pd.get("keys") or []),
            }
            suite_meta["dimension_display_names"] = self._dimension_name_map()

            report = TestReport(
                run_id=self.run_id,
                project_name=self.config.meta.get("name", "未命名项目"),
                start_time=self.start_time,
                end_time=datetime.now(),
                status=status,
                total_cases=len(self.cases),
                passed_cases=passed_count,
                failed_cases=len(self.cases) - passed_count,
                pass_rate=passed_count / len(self.cases) * 100 if self.cases else 0,
                dimension_stats=stats,
                criteria_results=criteria_results,
                suite_meta=suite_meta,
                aggregation_method=self.config.evaluation.aggregation_method,
                cases=self._build_case_rollups(self.cases),
                failed_examples=failed_examples,
                disputed_cases=disputed_cases,
                summary=self._generate_summary(stats, criteria_results),
                recommendations=self._generate_recommendations(stats, criteria_results),
                artifacts_path=self.artifacts_dir,
            )

            elapsed_s = (report.end_time - self.start_time).total_seconds()
            logger.info(
                "[run] 完成 run_id=%s status=%s cases=%d passed=%d pass_rate=%.1f%% "
                "gates_failed=%d elapsed=%.1fs",
                self.run_id,
                status.value,
                len(self.cases),
                passed_count,
                report.pass_rate,
                len(failed_gates),
                elapsed_s,
            )
            
            return report

        except Exception:
            logger.exception("[run] 执行异常 run_id=%s", self.run_id)
            raise
            
        finally:
            await self.cleanup()
            logger.info("[run] 资源已清理 run_id=%s", self.run_id)
    
    def _generate_summary(
        self, 
        stats: List[DimensionStats],
        criteria: List[PassCriteriaResult]
    ) -> str:
        """生成文本摘要"""
        passed_criteria = sum(1 for c in criteria if c.passed)
        total_criteria = len(criteria)
        
        summary = f"测试完成: {passed_criteria}/{total_criteria}项通过标准满足\n"
        
        for stat in stats:
            label = stat.dimension_name or stat.dimension_id
            summary += f"- {label}: 通过率{stat.pass_rate:.1f}%, 平均分{stat.avg_score:.2f}\n"
        
        return summary
    
    def _generate_recommendations(
        self,
        stats: List[DimensionStats],
        criteria: List[PassCriteriaResult]
    ) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        # 检查失败的维度
        for stat in stats:
            label = stat.dimension_name or stat.dimension_id
            if stat.pass_rate < 80:
                recommendations.append(
                    f"「{label}」维度通过率较低({stat.pass_rate:.1f}%)，建议检查评判标准或被测模型"
                )
            
            # 检查是否有集中的失败原因
            if stat.fail_reasons:
                top_reason = max(stat.fail_reasons.items(), key=lambda x: x[1])
                if top_reason[1] > stat.total_cases * 0.1:
                    recommendations.append(
                        f"「{label}」维度主要失败原因: {top_reason[0]} ({top_reason[1]}次)"
                    )
        
        # 检查未满足的门禁
        for c in criteria:
            if not c.passed:
                recommendations.append(f"未通过: {c.description} - {c.details}")
        
        return recommendations
    
    def save_artifacts(self, run_dir: str):
        """保存原始数据"""
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        config_path = os.path.join(run_dir, "config.json")
        raw_path = os.path.join(run_dir, "raw_outputs.jsonl")
        
        # 保存配置
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config.model_dump(), f, indent=2, default=str)
        
        # 保存原始输出
        with open(raw_path, 'w', encoding='utf-8') as f:
            for case in self.cases:
                record = {
                    "id": case.id,
                    "input": case.input.model_dump(),
                    "output": case.output.model_dump(),
                    "dimension_results": {
                        k: [r.model_dump() for r in v]
                        for k, v in case.dimension_results.items()
                    }
                }
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        logger.info(
            "[artifacts] 已写入 cases=%d config=%s raw=%s",
            len(self.cases),
            config_path,
            raw_path,
        )
