"""
FastAPI后端服务
"""

import os
import re
import json
import yaml
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# 导入核心模块
from ..config_loader import load_config, load_config_from_yaml_text
from ..engine import TestEngine, probe_suite_connectivity
from ..models import TestSuiteConfig, TestReport
from ..reporters import HTMLReporter, JSONReporter
from .chat_attachments import parse_request_attachments
from .assistant import run_assistant_chat
from .case_assistant import run_case_assistant_chat
from .ui_assistant import run_ui_assistant_chat
from ..platform.registry import get_modules, get_platform_meta
from ..platform import case_service, playwright_runner, workbench_service


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(".").resolve()


class _UvicornAccessDropStatsFilter(logging.Filter):
    """不记录对 /api/stats 的 access 行（前端轮询过密）。"""

    def filter(self, record):
        try:
            if "/api/stats" in record.getMessage():
                return False
        except Exception:
            pass
        return True


def _install_uvicorn_access_filters():
    acc = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _UvicornAccessDropStatsFilter) for f in acc.filters):
        acc.addFilter(_UvicornAccessDropStatsFilter())

# 全局状态
@dataclass
class RunningTest:
    """正在运行或刚结束的测试（企业级面板用详情字段）"""
    run_id: str
    project_name: str
    config_path: str
    status: str  # running, completed, failed, starting, stopped
    progress: int  # 0-100 粗粒度
    current_step: str
    report: Optional[TestReport] = None
    error: Optional[str] = None
    phase: str = "starting"  # starting | invoking | evaluating | aggregating | completed | failed
    planned_cases: int = 0
    invoke_completed: int = 0
    evaluate_completed: int = 0
    started_at: Optional[str] = None
    events: List[Dict[str, Any]] = field(default_factory=list)
    recent_cases: List[Dict[str, Any]] = field(default_factory=list)


def _append_run_event(test: RunningTest, kind: str, payload: Dict[str, Any], max_events: int = 400):
    test.events.append({
        "ts": datetime.now().isoformat(),
        "kind": kind,
        **payload,
    })
    if len(test.events) > max_events:
        test.events = test.events[-(max_events // 2) :]


def _append_recent_case(test: RunningTest, row: Dict[str, Any], max_rows: int = 80):
    test.recent_cases.append(row)
    if len(test.recent_cases) > max_rows:
        test.recent_cases = test.recent_cases[-max_rows:]


def _apply_live_event(test: RunningTest, kind: str, payload: Dict[str, Any]):
    """将引擎 live_hook 事件写入 RunningTest（活动日志 + 用例行）。"""
    if kind == "lifecycle":
        ph = str(payload.get("phase", "") or "")
        test.phase = ph or test.phase
        msg = payload.get("message")
        if isinstance(msg, str) and msg:
            test.current_step = msg
        if ph == "inputs_ready":
            n = int(payload.get("total") or 0)
            if n > 0:
                test.planned_cases = n
        ev = {"phase": ph, "message": msg}
        for k, v in payload.items():
            if k not in ("phase", "message"):
                ev[k] = v
        _append_run_event(test, "lifecycle", ev)
    elif kind == "invoke":
        test.phase = "invoking"
        d = int(payload.get("done") or 0)
        tot = int(payload.get("total") or 0)
        test.invoke_completed = d
        test.planned_cases = max(test.planned_cases, tot)
        if test.planned_cases > 0:
            test.progress = min(49, int(d / test.planned_cases * 50))
        lat = payload.get("latency_ms")
        test.current_step = f"调用被测模型 {d}/{tot}" + (f" · {lat}ms" if lat is not None else "")
        _append_run_event(test, "invoke", dict(payload))
        _append_recent_case(
            test,
            {
                "case_id": payload.get("case_id"),
                "latency_ms": lat,
                "error": payload.get("error"),
                "output_chars": payload.get("output_chars"),
            },
        )
    elif kind == "evaluate":
        test.phase = "evaluating"
        d = int(payload.get("done") or 0)
        tot = int(payload.get("total") or 0)
        test.evaluate_completed = d
        test.planned_cases = max(test.planned_cases, tot)
        if test.planned_cases > 0:
            test.progress = 50 + min(49, int(d / test.planned_cases * 50))
        passed = payload.get("passed")
        fd = payload.get("failed_dimensions") or []
        extra = " · 本用例未通过" if passed is False else (" · 本用例通过" if passed is True else "")
        test.current_step = f"评判输出 {d}/{tot}{extra}"
        _append_run_event(test, "evaluate", dict(payload))
        cid = payload.get("case_id")
        merged = False
        for row in reversed(test.recent_cases):
            if row.get("case_id") == cid:
                row["passed"] = passed
                row["failed_dimensions"] = list(fd) if isinstance(fd, (list, tuple)) else fd
                merged = True
                break
        if not merged:
            _append_recent_case(
                test,
                {"case_id": cid, "passed": passed, "failed_dimensions": fd},
            )


def _apply_report_to_running_test(test: RunningTest, report: TestReport) -> None:
    """根据 TestReport 同步面板状态（未通过须显示 failed，不能一律 completed）。"""
    test.report = report
    test.progress = 100
    rv = report.status.value if report else "failed"
    if getattr(report, "abort_reason", None) == "connectivity":
        test.status = "failed"
        test.phase = "connectivity_failed"
        test.current_step = "已中止：被测接口不可达（仅 JSON 记录，未生成 HTML 报告）"
        return
    total = report.total_cases or 0
    passed = report.passed_cases or 0
    if rv == "passed":
        test.status = "passed"
        test.phase = "completed"
        test.current_step = (
            f"通过：{passed}/{total} 用例达标，报告已写入 web_results"
            if total
            else "通过，报告已写入 web_results"
        )
    else:
        test.status = "failed"
        test.phase = "failed"
        test.current_step = (
            f"未通过：{report.failed_cases}/{total} 用例未达标，报告已写入 web_results"
            if total
            else "未通过，报告已写入 web_results"
        )


def _running_test_snapshot(test: RunningTest, events_tail: int = 48, cases_tail: int = 32) -> Dict[str, Any]:
    """供 HTTP / WebSocket 返回的精简快照。"""
    snap: Dict[str, Any] = {
        "run_id": test.run_id,
        "project_name": test.project_name,
        "config_path": test.config_path,
        "status": test.status,
        "progress": test.progress,
        "current_step": test.current_step,
        "phase": test.phase,
        "planned_cases": test.planned_cases,
        "invoke_completed": test.invoke_completed,
        "evaluate_completed": test.evaluate_completed,
        "started_at": test.started_at,
        "error": test.error,
        "events": test.events[-events_tail:],
        "recent_cases": test.recent_cases[-cases_tail:],
        "is_running": test.status in ("starting", "running"),
    }
    if test.report:
        snap["pass_rate"] = test.report.pass_rate
        snap["total_cases"] = test.report.total_cases
        snap["failed_cases"] = test.report.failed_cases
        snap["passed_cases"] = test.report.passed_cases
        snap["report_status"] = test.report.status.value
    return snap


# 运行中的测试管理
running_tests: Dict[str, RunningTest] = {}
test_history: List[Dict] = []

app = FastAPI(title="LLM-QAuto Web", version="1.0.0")


# API模型
class TestConfigRequest(BaseModel):
    """测试配置请求"""
    name: str
    config_yaml: str


class ConfigProbeRequest(BaseModel):
    """配置连通性探测"""
    config_yaml: str


class RunTestRequest(BaseModel):
    """运行测试请求"""
    config_path: str


class AssistantMessage(BaseModel):
    role: str
    content: str
    image_count: int = 0


class ChatAttachment(BaseModel):
    type: str = "image"
    data: str
    name: Optional[str] = None


class AssistantChatRequest(BaseModel):
    messages: List[AssistantMessage] = []
    collected: Optional[Dict[str, Any]] = None
    patch: Optional[Dict[str, Any]] = None
    attachments: List[ChatAttachment] = []


class AssistantSceneOption(BaseModel):
    id: str
    label: str
    suite_name: str
    hint: str = ""


class AssistantChatResponse(BaseModel):
    message: str
    phase: str = "collecting"
    collected: Dict[str, Any] = {}
    config_yaml: Optional[str] = None
    config_name: Optional[str] = None
    quick_replies: List[str] = []
    missing: List[str] = []
    scene_options: List[AssistantSceneOption] = []
    show_restart: bool = False


class TestResultSummary(BaseModel):
    """测试结果摘要"""
    run_id: str
    project_name: str
    status: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    start_time: str
    end_time: Optional[str] = None


class CaseChatResponse(BaseModel):
    message: str
    phase: str = "collecting"
    collected: Dict[str, Any] = {}
    quick_replies: List[str] = []
    missing: List[str] = []
    show_restart: bool = False
    title: Optional[str] = None
    assumptions: Optional[str] = None
    mermaid_review: Optional[str] = None
    mermaid_tree: Optional[str] = None
    case_table_markdown: Optional[str] = None


class UiChatResponse(BaseModel):
    message: str
    phase: str = "collecting"
    collected: Dict[str, Any] = {}
    quick_replies: List[str] = []
    missing: List[str] = []
    show_restart: bool = False
    spec_name: Optional[str] = None
    spec_content: Optional[str] = None


class CaseGenerateRequest(BaseModel):
    input_text: str = ""
    title: Optional[str] = None
    messages: List[AssistantMessage] = []


class CaseSessionSaveRequest(BaseModel):
    title: Optional[str] = None
    input_text: str = ""
    assumptions: str = ""
    mermaid_review: str = ""
    mermaid_tree: str = ""
    case_table_markdown: str = ""
    message: str = ""


class WorkbenchGenerateRequest(BaseModel):
    input_text: str = ""
    title: Optional[str] = None


class WorkbenchSessionSaveRequest(BaseModel):
    title: Optional[str] = None
    input_text: str = ""
    message: str = ""
    outputs: Dict[str, Any] = {}


class UiAutoGenerateRequest(BaseModel):
    description: str
    url: Optional[str] = None
    spec_name: Optional[str] = None


class UiAutoProbeRequest(BaseModel):
    url: str


class UiAutoSpecRequest(BaseModel):
    name: str
    content: str


class UiAutoRunRequest(BaseModel):
    spec_name: Optional[str] = None
    display_mode: str = "background"  # background | visible


# 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"
UPLOADS_DIR = Path("./web_uploads")
RESULTS_DIR = Path("./web_results")

# 确保目录存在
UPLOADS_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def root():
    """主页面"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse(content="<h1>LLM-QAuto Web</h1><p>Static files not found</p>")


@app.get("/api/projects")
async def list_projects():
    """列出所有测试项目"""
    projects = []
    
    # 从上传目录读取
    if UPLOADS_DIR.exists():
        for config_file in UPLOADS_DIR.glob("*.yaml"):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    config = yaml.safe_load(content)
                    
                projects.append({
                    "id": config_file.stem,
                    "name": config.get("meta", {}).get("name", config_file.stem),
                    "description": config.get("meta", {}).get("description", ""),
                    "created_at": datetime.fromtimestamp(config_file.stat().st_mtime).isoformat(),
                    "config_path": str(config_file),
                })
            except Exception as e:
                projects.append({
                    "id": config_file.stem,
                    "name": config_file.stem,
                    "error": str(e),
                    "config_path": str(config_file)
                })
    
    # 也扫描examples目录
    examples_dir = Path("./examples")
    if examples_dir.exists():
        for config_file in examples_dir.glob("*.yaml"):
            if not any(p["config_path"] == str(config_file) for p in projects):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        config = yaml.safe_load(content)
                        
                    projects.append({
                        "id": f"example_{config_file.stem}",
                        "name": config.get("meta", {}).get("name", config_file.stem),
                        "description": config.get("meta", {}).get("description", ""),
                        "is_example": True,
                        "config_path": str(config_file),
                    })
                except Exception as ex:
                    logger.warning("示例配置解析失败 %s: %s", config_file, ex)
                    projects.append({
                        "id": f"example_{config_file.stem}",
                        "name": config_file.stem,
                        "description": f"YAML 解析失败: {ex}",
                        "is_example": True,
                        "config_path": str(config_file),
                        "error": str(ex),
                    })
    
    return {"projects": sorted(projects, key=lambda x: x.get("created_at", ""), reverse=True)}


@app.post("/api/projects")
async def create_project(request: TestConfigRequest):
    """创建新项目"""
    try:
        # 验证YAML格式
        config = yaml.safe_load(request.config_yaml)
        
        # 确保有meta信息
        if "meta" not in config:
            config["meta"] = {}
        config["meta"]["name"] = request.name
        config["meta"]["created_at"] = datetime.now().isoformat()
        
        # 保存文件
        file_name = f"{request.name.replace(' ', '_').lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
        config_path = UPLOADS_DIR / file_name
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)
        
        return {
            "success": True,
            "id": config_path.stem,
            "config_path": str(config_path)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置保存失败: {str(e)}")


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """获取项目详情"""
    # 在上传目录和示例目录中查找
    config_path = UPLOADS_DIR / f"{project_id}.yaml"
    if not config_path.exists():
        config_path = UPLOADS_DIR / project_id  # 可能包含时间戳
    if not config_path.exists():
        # 尝试examples
        if project_id.startswith("example_"):
            config_path = Path("./examples") / f"{project_id[8:]}.yaml"
    
    if not config_path or not config_path.exists():
        raise HTTPException(status_code=404, detail="项目不存在")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        resolved = config_path.resolve()
        return {
            "id": project_id,
            "config_path": str(resolved),
            "config_yaml": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置失败: {str(e)}")


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, request: TestConfigRequest):
    """更新项目配置（示例项目首次保存会写入 web_uploads，不修改仓库内 examples）"""
    config_path = UPLOADS_DIR / f"{project_id}.yaml"
    if not config_path.exists():
        alt = UPLOADS_DIR / project_id
        if alt.exists():
            config_path = alt
        elif project_id.startswith("example_"):
            example_path = Path("./examples") / f"{project_id[8:]}.yaml"
            if example_path.exists():
                # 示例只读：把用户编辑结果保存到上传目录同名文件
                config_path = UPLOADS_DIR / f"{project_id}.yaml"
            else:
                raise HTTPException(status_code=404, detail="项目不存在")
        else:
            raise HTTPException(status_code=404, detail="项目不存在")
    
    try:
        yaml.safe_load(request.config_yaml)
        
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(request.config_yaml)
        
        return {"success": True, "config_path": str(config_path)}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 无效: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新失败: {str(e)}")


@app.post("/api/config/probe")
async def probe_config_connectivity(request: ConfigProbeRequest):
    """编辑配置时探测被测接口：用首条测试数据发一次请求，不跑评委。"""
    try:
        config = load_config_from_yaml_text(request.config_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 无效: {e}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置解析失败: {e}")

    try:
        result = await probe_suite_connectivity(config)
        return result
    except Exception as e:
        logger.exception("config probe failed")
        raise HTTPException(status_code=500, detail=f"探测失败: {e}")


@app.post("/api/assistant/chat", response_model=AssistantChatResponse)
async def assistant_chat(request: AssistantChatRequest):
    """配置助手：多轮对话收集 cURL / 场景信息并生成测试 YAML。"""
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        attachments = [a.model_dump() for a in request.attachments]
        result = await run_assistant_chat(messages, request.collected, request.patch, attachments=attachments)
        return AssistantChatResponse(**result)
    except Exception as e:
        logger.exception("assistant chat failed")
        raise HTTPException(status_code=500, detail=f"配置助手失败: {e}")


@app.post("/api/cases/chat", response_model=CaseChatResponse)
async def cases_chat(request: AssistantChatRequest):
    """用例设计助手：多轮对话收集 PRD / AC 并生成测试树与用例表。"""
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        attachments = [a.model_dump() for a in request.attachments]
        result = await run_case_assistant_chat(messages, request.collected, request.patch, attachments=attachments)
        return CaseChatResponse(**result)
    except Exception as e:
        logger.exception("case assistant chat failed")
        raise HTTPException(status_code=500, detail=f"用例助手失败: {e}")


@app.post("/api/ui-auto/chat", response_model=UiChatResponse)
async def ui_auto_chat(request: AssistantChatRequest):
    """UI 自动化助手：多轮对话收集流程描述并生成 Playwright 脚本。"""
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        attachments = [a.model_dump() for a in request.attachments]
        result = await run_ui_assistant_chat(
            messages,
            request.collected,
            request.patch,
            attachments=attachments,
            project_root=PROJECT_ROOT,
        )
        return UiChatResponse(**result)
    except Exception as e:
        logger.exception("ui assistant chat failed")
        raise HTTPException(status_code=500, detail=f"UI 助手失败: {e}")


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """删除项目"""
    config_path = UPLOADS_DIR / f"{project_id}.yaml"
    if not config_path.exists():
        config_path = UPLOADS_DIR / project_id
    
    if config_path.exists() and not str(config_path).startswith(str(Path("./examples"))):
        config_path.unlink()
        return {"success": True}
    
    raise HTTPException(status_code=404, detail="项目不存在或是示例项目")


def _run_list_sort_key(run: Dict[str, Any]) -> int:
    """
    列表按「最新在上」排序：优先从 run_id 中 run_YYYYMMDD_HHMMSS 解析；
    不可靠时用 start_time 字符串前 19 位兜底。越大越新。
    """
    rid = run.get("run_id") or ""
    m = re.search(r"run_(\d{8})_(\d{6})", rid)
    if m:
        try:
            return int(m.group(1) + m.group(2))
        except ValueError:
            pass
    st = run.get("start_time")
    if isinstance(st, str) and len(st) >= 19:
        try:
            return int(
                st[0:4] + st[5:7] + st[8:10] + st[11:13] + st[14:16] + st[17:19]
            )
        except ValueError:
            pass
    return 0


def _assert_safe_run_id(run_id: str) -> Path:
    """防止路径逃逸；返回位于 RESULTS_DIR 下的目录路径。"""
    if not run_id or ".." in run_id or "/" in run_id or "\\" in run_id:
        raise HTTPException(status_code=400, detail="无效的 run_id")
    if not re.match(r"^run_[A-Za-z0-9_\-\.]+$", run_id):
        raise HTTPException(status_code=400, detail="无效的 run_id")
    base = RESULTS_DIR.resolve()
    run_dir = (base / run_id).resolve()
    if run_dir.parent != base:
        raise HTTPException(status_code=400, detail="无效的 run_id")
    return run_dir


@app.delete("/api/runs/{run_id}/history")
async def delete_run_history(run_id: str):
    """
    永久删除一条运行记录：移除 web_results/<run_id> 目录，
    并清除内存中已结束的任务及 test_history 中的条目。
    运行中 / 启动中的任务须先「停止」。
    """
    run_dir = _assert_safe_run_id(run_id)
    had_disk = run_dir.is_dir()
    had_mem = run_id in running_tests

    if had_mem:
        test = running_tests[run_id]
        if test.status in ("running", "starting"):
            raise HTTPException(
                status_code=409,
                detail="任务仍在运行或启动中，请先点击「停止」后再删除",
            )
        del running_tests[run_id]

    test_history[:] = [h for h in test_history if h.get("run_id") != run_id]

    if had_disk:
        shutil.rmtree(run_dir, ignore_errors=False)

    if not had_mem and not had_disk:
        raise HTTPException(status_code=404, detail="运行记录不存在")

    logger.info("已删除运行记录 run_id=%s removed_dir=%s had_mem=%s", run_id, had_disk, had_mem)
    return {"success": True, "run_id": run_id, "removed_dir": had_disk}


@app.get("/api/runs")
async def list_runs():
    """列出测试运行历史"""
    runs = []
    
    # 正在运行的测试
    for run_id, test in running_tests.items():
        row: Dict[str, Any] = {
            "run_id": run_id,
            "project_name": test.project_name,
            "status": test.status,
            "progress": test.progress,
            "current_step": test.current_step,
            "is_running": test.status in ("starting", "running"),
            "phase": test.phase,
            "planned_cases": test.planned_cases,
            "invoke_completed": test.invoke_completed,
            "evaluate_completed": test.evaluate_completed,
        }
        if test.report:
            row["pass_rate"] = test.report.pass_rate
            row["total_cases"] = test.report.total_cases
            row["failed_cases"] = test.report.failed_cases
            row["report_status"] = test.report.status.value
        runs.append(row)
    
    running_ids = set(running_tests.keys())

    # 历史结果
    if RESULTS_DIR.exists():
        for result_dir in sorted(RESULTS_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if result_dir.name in running_ids:
                continue
            json_file = result_dir / "report.json"
            if json_file.exists():
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        report_data = json.load(f)
                    
                    status_raw = report_data.get("status")
                    if isinstance(status_raw, dict):
                        status_val = status_raw.get("value", "unknown")
                    else:
                        status_val = status_raw if status_raw is not None else "unknown"

                    runs.append({
                        "run_id": result_dir.name,
                        "project_name": report_data.get("project_name", "Unknown"),
                        "status": status_val,
                        "total_cases": report_data.get("total_cases", 0),
                        "passed_cases": report_data.get("passed_cases", 0),
                        "failed_cases": report_data.get("failed_cases", 0),
                        "pass_rate": report_data.get("pass_rate", 0),
                        "start_time": report_data.get("start_time"),
                        "end_time": report_data.get("end_time"),
                        "is_running": False,
                        "has_report": True
                    })
                except Exception:
                    pass

    runs.sort(key=_run_list_sort_key, reverse=True)

    return {"runs": runs}


@app.get("/api/runs/{run_id}/detail")
async def get_run_detail(run_id: str):
    """运行中任务的实时详情；已结束的可拉取报告摘要。"""
    if run_id in running_tests:
        return _running_test_snapshot(running_tests[run_id], events_tail=120, cases_tail=60)

    json_file = RESULTS_DIR / run_id / "report.json"
    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)
            status_raw = report_data.get("status")
            if isinstance(status_raw, dict):
                status_val = status_raw.get("value", "unknown")
            else:
                status_val = status_raw if status_raw is not None else "unknown"
            failed = status_val == "failed"
            total = int(report_data.get("total_cases") or 0)
            passed = int(report_data.get("passed_cases") or 0)
            step = (
                f"未通过：{report_data.get('failed_cases', 0)}/{total} 用例未达标"
                if failed and total
                else ("未通过" if failed else f"通过：{passed}/{total} 用例达标" if total else "已完成")
            )
            return {
                "run_id": run_id,
                "status": status_val,
                "is_running": False,
                "phase": "failed" if failed else "completed",
                "project_name": report_data.get("project_name"),
                "current_step": step,
                "progress": 100,
                "planned_cases": total,
                "invoke_completed": total,
                "evaluate_completed": total,
                "events": [],
                "recent_cases": [],
                "report_summary": {
                    "total_cases": report_data.get("total_cases"),
                    "passed_cases": report_data.get("passed_cases"),
                    "failed_cases": report_data.get("failed_cases"),
                    "pass_rate": report_data.get("pass_rate"),
                    "status": status_val,
                },
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=404, detail="运行不存在")


@app.get("/api/runs/{run_id}/report")
async def get_run_report(run_id: str):
    """获取测试报告"""
    json_file = RESULTS_DIR / run_id / "report.json"
    html_file = RESULTS_DIR / run_id / "report.html"

    # 只要已写入 report.json，就以落盘结果为准（completed 任务仍会暂留在 running_tests 中，
    # 若优先读内存会得到 status=completed、无 total_cases/html_url，前端会把摘要误判为失败且 KPI 全 0）
    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                report_data = json.load(f)

            mem = running_tests.get(run_id)
            report_data["is_running"] = (
                mem is not None and mem.status in ("starting", "running")
            )
            report_data["html_url"] = (
                f"/api/runs/{run_id}/report.html" if html_file.exists() else None
            )
            # 仍在跑时一般不会已有完整 json；若存在则附带内存里的近期事件便于「进行中」弹窗
            if mem is not None and report_data["is_running"]:
                snap = _running_test_snapshot(mem, events_tail=40, cases_tail=25)
                report_data["events"] = snap.get("events", [])
                report_data["recent_cases"] = snap.get("recent_cases", [])
            return report_data
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"读取报告失败: {str(e)}")

    if run_id in running_tests:
        test = running_tests[run_id]
        snap = _running_test_snapshot(test, events_tail=40, cases_tail=25)
        return {
            "run_id": run_id,
            "status": test.status,
            "progress": test.progress,
            "current_step": test.current_step,
            "is_running": snap.get(
                "is_running", test.status in ("starting", "running")
            ),
            "phase": snap.get("phase"),
            "planned_cases": snap.get("planned_cases"),
            "invoke_completed": snap.get("invoke_completed"),
            "evaluate_completed": snap.get("evaluate_completed"),
            "events": snap.get("events", []),
            "recent_cases": snap.get("recent_cases", []),
        }

    raise HTTPException(status_code=404, detail="报告不存在")


@app.get("/api/runs/{run_id}/report.html")
async def get_run_report_html(run_id: str):
    """获取HTML报告"""
    html_file = RESULTS_DIR / run_id / "report.html"
    if html_file.exists():
        return FileResponse(html_file)
    raise HTTPException(status_code=404, detail="HTML报告不存在")


async def run_test_task(run_id: str, config_path: str):
    """后台运行测试任务（engine.run 内已 initialize/cleanup，此处不得重复）。"""
    test = running_tests.get(run_id)
    if not test:
        logger.warning("run_test_task: run_id=%s 不在 running_tests，跳过", run_id)
        return

    logger.info(
        "run_test_task 开始 run_id=%s config_path=%s",
        run_id,
        config_path,
    )

    try:
        test.status = "running"
        test.phase = "starting"
        test.current_step = "加载配置…"
        test.progress = 0
        test.started_at = datetime.now().isoformat()
        test.error = None

        config = load_config(config_path)
        test.project_name = config.meta.get("name", "Unknown")
        logger.info(
            "run_test_task 配置已加载 run_id=%s project=%r",
            run_id,
            test.project_name,
        )

        run_dir = RESULTS_DIR / run_id
        run_dir.mkdir(exist_ok=True)

        engine = TestEngine(config)

        def progress_callback(current, total, phase=""):
            if total <= 0:
                return
            if phase == "evaluate":
                test.progress = 50 + min(49, int(current / total * 50))
                test.current_step = f"批次进度·评判 {current}/{total}"
            else:
                test.progress = min(49, int(current / total * 50))
                test.current_step = f"批次进度·调用 {current}/{total}"

        def live_hook(kind: str, payload: Dict[str, Any]):
            _apply_live_event(test, kind, payload)

        artifacts_path = str(run_dir / "artifacts")
        report = await engine.run(
            run_id=run_id,
            progress_callback=progress_callback,
            live_hook=live_hook,
            artifacts_dir=artifacts_path,
        )
        _apply_report_to_running_test(test, report)

        JSONReporter().generate(report, str(run_dir / "report.json"), {})
        if getattr(report, "abort_reason", None) != "connectivity":
            HTMLReporter().generate(report, str(run_dir / "report.html"), {})
            logger.info(
                "run_test_task 报告已写入 run_id=%s json+html cases=%d status=%s",
                run_id,
                report.total_cases,
                report.status.value,
            )
        else:
            logger.info(
                "run_test_task 仅写入 JSON（连通性预检失败）run_id=%s",
                run_id,
            )
        engine.save_artifacts(artifacts_path)
        logger.info("run_test_task artifacts 已保存 run_id=%s dir=%s", run_id, artifacts_path)

        test_history.append(
            {
                "run_id": run_id,
                "project_name": test.project_name,
                "status": test.status,
                "timestamp": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        logger.exception("run_test_task 失败 run_id=%s config_path=%s", run_id, config_path)
        if run_id in running_tests:
            t = running_tests[run_id]
            t.status = "failed"
            t.phase = "failed"
            t.error = str(e)
            t.current_step = f"错误: {str(e)}"
            _append_run_event(t, "error", {"message": str(e)})


@app.post("/api/runs")
async def start_run(request: RunTestRequest, background_tasks: BackgroundTasks):
    """启动测试"""
    config_path = Path(request.config_path)
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    if not config_path.exists():
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {config_path}")
    config_path = str(config_path)
    
    # 生成运行ID
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{Path(config_path).stem}"
    
    # 创建测试记录
    running_tests[run_id] = RunningTest(
        run_id=run_id,
        project_name="",
        config_path=config_path,
        status="starting",
        progress=0,
        current_step="启动中"
    )
    
    logger.info("启动测试 run_id=%s config=%s", run_id, config_path)

    # 后台执行
    background_tasks.add_task(run_test_task, run_id, config_path)
    
    return {
        "success": True,
        "run_id": run_id,
        "status": "starting"
    }


@app.delete("/api/runs/{run_id}")
async def stop_run(run_id: str):
    """停止运行中的测试（简化实现，只是标记）"""
    if run_id in running_tests:
        test = running_tests[run_id]
        if test.status == "running":
            test.status = "stopped"
            test.current_step = "用户停止"
            return {"success": True}
    
    raise HTTPException(status_code=404, detail="运行不存在或已完成")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时推送（含活动日志与用例摘要尾部）。"""
    await websocket.accept()

    try:
        last_serialized: Optional[str] = None

        while True:
            payload = {
                "running_tests": [
                    _running_test_snapshot(t, events_tail=36, cases_tail=24)
                    for t in running_tests.values()
                ],
                "timestamp": datetime.now().isoformat(),
            }
            serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
            if serialized != last_serialized:
                await websocket.send_json(payload)
                last_serialized = serialized

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")


@app.get("/api/stats")
async def get_stats():
    """获取全局统计"""
    total_tests = len(test_history) + len([t for t in running_tests.values() if t.status == "completed"])
    
    success_tests = len([t for t in running_tests.values() if t.status == "completed" and t.report and t.report.status.value == "passed"])
    success_tests += len([h for h in test_history if h.get("status") == "completed"])
    
    return {
        "total_projects": len(list(UPLOADS_DIR.glob("*.yaml"))),
        "total_tests": total_tests,
        "success_rate": success_tests / total_tests * 100 if total_tests > 0 else 0,
        "running_tests": len([t for t in running_tests.values() if t.status == "running"])
    }


@app.get("/api/health")
async def health():
    """健康检查（便于确认前后端联通）"""
    return {"ok": True, "service": "llm-qauto-web"}


@app.get("/api/platform/modules")
async def platform_modules():
    """平台模块清单（Web 与 Skill 共用 manifest）"""
    return {
        "platform": get_platform_meta(),
        "modules": get_modules(enabled_only=True),
    }


@app.post("/api/cases/generate")
async def cases_generate(request: CaseGenerateRequest):
    try:
        result = await case_service.generate_cases(
            input_text=request.input_text,
            title=request.title,
            messages=[m.model_dump() for m in request.messages],
        )
        return {"success": True, **result}
    except Exception as e:
        logger.exception("case generate failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/cases/sessions")
async def cases_list_sessions():
    return {"sessions": case_service.list_sessions(PROJECT_ROOT)}


@app.get("/api/cases/sessions/{session_id}")
async def cases_get_session(session_id: str):
    doc = case_service.get_session(PROJECT_ROOT, session_id)
    if not doc:
        raise HTTPException(status_code=404, detail="会话不存在")
    return doc


@app.post("/api/cases/sessions")
async def cases_save_session(request: CaseSessionSaveRequest, session_id: Optional[str] = None):
    doc = case_service.save_session(PROJECT_ROOT, request.model_dump(), session_id=session_id)
    return {"success": True, "session": doc}


@app.delete("/api/cases/sessions/{session_id}")
async def cases_delete_session(session_id: str):
    if not case_service.delete_session(PROJECT_ROOT, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True}


@app.get("/api/cases/sessions/{session_id}/export.csv")
async def cases_export_csv(session_id: str):
    doc = case_service.get_session(PROJECT_ROOT, session_id)
    if not doc:
        raise HTTPException(status_code=404, detail="会话不存在")
    from fastapi.responses import PlainTextResponse

    csv_text = case_service.markdown_to_csv(doc.get("case_table_markdown") or "")
    return PlainTextResponse(csv_text, media_type="text/csv; charset=utf-8")


def _workbench_kind(kind: str) -> str:
    try:
        return workbench_service.resolve_kind(kind)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/workbench/{kind}/generate")
async def workbench_generate(kind: str, request: WorkbenchGenerateRequest):
    module_key = _workbench_kind(kind)
    try:
        result = await workbench_service.generate(
            module_key, request.input_text, title=request.title
        )
        return {"success": True, **result}
    except Exception as e:
        logger.exception("workbench generate failed kind=%s", kind)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/workbench/{kind}/sessions")
async def workbench_list_sessions(kind: str):
    module_key = _workbench_kind(kind)
    return {"sessions": workbench_service.list_sessions(PROJECT_ROOT, module_key)}


@app.get("/api/workbench/{kind}/sessions/{session_id}")
async def workbench_get_session(kind: str, session_id: str):
    module_key = _workbench_kind(kind)
    doc = workbench_service.get_session(PROJECT_ROOT, module_key, session_id)
    if not doc:
        raise HTTPException(status_code=404, detail="会话不存在")
    return doc


@app.post("/api/workbench/{kind}/sessions")
async def workbench_save_session(kind: str, request: WorkbenchSessionSaveRequest):
    module_key = _workbench_kind(kind)
    doc = workbench_service.save_session(PROJECT_ROOT, module_key, request.model_dump())
    return {"success": True, "session": doc}


@app.delete("/api/workbench/{kind}/sessions/{session_id}")
async def workbench_delete_session(kind: str, session_id: str):
    module_key = _workbench_kind(kind)
    if not workbench_service.delete_session(PROJECT_ROOT, module_key, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True}


@app.get("/api/ui-auto/specs")
async def ui_auto_list_specs():
    return {"specs": playwright_runner.list_specs(PROJECT_ROOT)}


@app.get("/api/ui-auto/specs/{name}")
async def ui_auto_get_spec(name: str):
    try:
        content = playwright_runner.read_spec(PROJECT_ROOT, name)
        return {"name": name, "content": content}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/ui-auto/specs")
async def ui_auto_save_spec(request: UiAutoSpecRequest):
    meta = playwright_runner.write_spec(PROJECT_ROOT, request.name, request.content)
    return {"success": True, **meta}


@app.delete("/api/ui-auto/specs/{name}")
async def ui_auto_delete_spec(name: str):
    if not playwright_runner.delete_spec(PROJECT_ROOT, name):
        raise HTTPException(status_code=404, detail="脚本不存在")
    return {"success": True}


@app.post("/api/ui-auto/probe")
async def ui_auto_probe(request: UiAutoProbeRequest):
    """用 Playwright 打开 URL，提取可交互元素与截图，供脚本生成使用。"""
    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url 不能为空")
    try:
        probe = await asyncio.to_thread(playwright_runner.probe_page_url, PROJECT_ROOT, url)
        b64 = probe.pop("screenshot_base64", None)
        screenshot_data_url = f"data:image/png;base64,{b64}" if b64 else None
        return {"success": True, "page_probe": probe, "screenshot_data_url": screenshot_data_url}
    except Exception as e:
        logger.exception("ui-auto probe failed")
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/ui-auto/generate")
async def ui_auto_generate(request: UiAutoGenerateRequest):
    try:
        page_probe = None
        image_urls = None
        if request.url:
            try:
                probe = await asyncio.to_thread(
                    playwright_runner.probe_page_url, PROJECT_ROOT, request.url
                )
                b64 = probe.get("screenshot_base64")
                if b64:
                    image_urls = [f"data:image/png;base64,{b64}"]
                page_probe = {k: v for k, v in probe.items() if k != "screenshot_base64"}
            except Exception as e:
                logger.warning("generate 前页面探测失败: %s", e)
        result = await playwright_runner.generate_spec(
            request.description,
            url=request.url,
            spec_name=request.spec_name,
            image_data_urls=image_urls,
            page_probe=page_probe,
        )
        return {"success": True, **result, "page_probed": bool(page_probe)}
    except Exception as e:
        logger.exception("ui-auto generate failed")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ui-auto/run")
async def ui_auto_run(request: UiAutoRunRequest):
    try:
        meta = await playwright_runner.run_playwright_tests(
            PROJECT_ROOT,
            request.spec_name,
            display_mode=request.display_mode,
        )
        return {"success": meta.get("exit_code") == 0, **meta}
    except Exception as e:
        logger.exception("ui-auto run failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ui-auto/runs")
async def ui_auto_list_runs():
    return {"runs": playwright_runner.list_runs(PROJECT_ROOT)}


@app.get("/api/ui-auto/runs/{run_id}")
async def ui_auto_get_run(run_id: str):
    try:
        return playwright_runner.get_run(PROJECT_ROOT, run_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/ui-auto/runs/{run_id}/screenshot")
async def ui_auto_run_screenshot(run_id: str):
    try:
        path = playwright_runner.get_run_screenshot_path(PROJECT_ROOT, run_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if not path:
        raise HTTPException(status_code=404, detail="暂无失败截图")
    return FileResponse(path, media_type="image/png")


@app.delete("/api/ui-auto/runs/{run_id}")
async def ui_auto_delete_run(run_id: str):
    try:
        deleted = playwright_runner.delete_run(PROJECT_ROOT, run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return {"success": True, "run_id": run_id}


@app.get("/api/ui-auto/report/latest")
async def ui_auto_latest_report():
    report_dir = playwright_runner.get_latest_report_dir(PROJECT_ROOT)
    if not report_dir:
        raise HTTPException(status_code=404, detail="暂无报告")
    index = report_dir / "index.html"
    return FileResponse(index)


@app.post("/api/ui-auto/ci/generate-workflow")
async def ui_auto_generate_ci():
    try:
        result = playwright_runner.generate_github_workflow(PROJECT_ROOT)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _mount_static_files():
    """静态资源须在全部 API 路由注册之后再 mount，避免路由被吞"""
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


_mount_static_files()
_install_uvicorn_access_filters()


def start_web_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    reload: Optional[bool] = None,
):
    """
    启动 Web 服务。

    默认开启热重载（修改 ``src/llm_qauto`` 下代码后自动重启）；
    设置环境变量 ``QAUTO_WEB_RELOAD=0`` 可关闭。
    热重载通过 import 字符串加载 app，与 ``reload=False`` 时直接传 ``app`` 对象二选一。
    """
    import os

    import uvicorn

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    if reload is None:
        reload_env = os.environ.get("QAUTO_WEB_RELOAD")
        # Windows + uvicorn reload often leaves orphan workers after Ctrl+C (API hang).
        if reload_env is None and os.name == "nt":
            reload = False
        else:
            reload = (reload_env or "1").strip().lower() not in (
                "0",
                "false",
                "no",
                "off",
            )

    # .../src/llm_qauto/web/api.py -> parents[2] == src
    src_root = Path(__file__).resolve().parents[2]

    if reload:
        uvicorn.run(
            "llm_qauto.web.api:app",
            host=host,
            port=port,
            reload=True,
            reload_dirs=[str(src_root)],
        )
    else:
        uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_web_server()
