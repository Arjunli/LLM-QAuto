"""Playwright UI automation: specs, local run, reports."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm_client import LLMClient
from ..plugins.evaluators import parse_llm_judge_json

logger = logging.getLogger(__name__)

PLAYWRIGHT_GENERATE_SYSTEM = """你是 Playwright 测试专家。根据用户描述生成 TypeScript Playwright 测试脚本。

输出 JSON（无 markdown 包裹）：
{
  "spec_name": "login.spec.ts",
  "spec_content": "完整 .spec.ts 文件内容",
  "message": "中文说明"
}

规则：
- 使用 @playwright/test
- import { test, expect } from '@playwright/test'
- 测试名清晰，步骤带注释
- 不要硬编码敏感 token；可用 process.env
"""


def ui_tests_root(base: Path) -> Path:
    root = base / "ui_tests"
    (root / "specs").mkdir(parents=True, exist_ok=True)
    (root / "runs").mkdir(parents=True, exist_ok=True)
    return root


def _safe_spec_name(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9._-]", "-", name or "test.spec.ts")
    if not n.endswith(".spec.ts"):
        n = n.rstrip(".") + ".spec.ts"
    return n[:80]


def list_specs(base: Path) -> List[Dict[str, Any]]:
    root = ui_tests_root(base)
    out = []
    for p in sorted((root / "specs").glob("*.spec.ts"), key=lambda x: x.stat().st_mtime, reverse=True):
        out.append(
            {
                "name": p.name,
                "path": str(p.relative_to(root)),
                "size": p.stat().st_size,
                "updated_at": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
            }
        )
    return out


def read_spec(base: Path, name: str) -> str:
    safe = _safe_spec_name(name)
    p = ui_tests_root(base) / "specs" / safe
    if not p.exists():
        raise FileNotFoundError(f"脚本不存在: {safe}")
    return p.read_text(encoding="utf-8")


def write_spec(base: Path, name: str, content: str) -> Dict[str, Any]:
    safe = _safe_spec_name(name)
    p = ui_tests_root(base) / "specs" / safe
    p.write_text(content or "", encoding="utf-8")
    return {"name": safe, "path": str(p.relative_to(ui_tests_root(base)))}


def delete_spec(base: Path, name: str) -> bool:
    safe = _safe_spec_name(name)
    p = ui_tests_root(base) / "specs" / safe
    if p.exists():
        p.unlink()
        return True
    return False


def ensure_playwright_config(base: Path) -> Path:
    root = ui_tests_root(base)
    cfg = root / "playwright.config.ts"
    if not cfg.exists():
        cfg.write_text(
            """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  timeout: 60000,
  use: { headless: true, screenshot: 'only-on-failure', trace: 'on-first-retry' },
  reporter: [['html', { open: 'never', outputFolder: '../runs/latest-report' }], ['list']],
});
""",
            encoding="utf-8",
        )
    pkg = root / "package.json"
    if not pkg.exists():
        pkg.write_text(
            json.dumps(
                {
                    "name": "llm-qauto-ui-tests",
                    "private": True,
                    "devDependencies": {"@playwright/test": "^1.49.0"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return root


def format_page_probe(probe: Dict[str, Any]) -> str:
    lines = [
        f"页面标题: {probe.get('title') or '（无）'}",
        f"最终 URL: {probe.get('final_url') or probe.get('url') or '（无）'}",
    ]
    headings = probe.get("headings") or []
    if headings:
        lines.append("页面标题元素: " + " | ".join(headings[:6]))
    lines.append(f"可交互元素（共探测 {probe.get('element_count', len(probe.get('elements') or []))} 个，节选）:")
    for el in (probe.get("elements") or [])[:30]:
        bits = [
            el.get("tag"),
            el.get("type") and f'type="{el["type"]}"',
            el.get("name") and f'name="{el["name"]}"',
            el.get("id") and f'id="{el["id"]}"',
            el.get("testId") and f'data-testid="{el["testId"]}"',
            el.get("role") and f'role="{el["role"]}"',
            el.get("placeholder") and f'placeholder="{el["placeholder"][:30]}"',
            el.get("text") and f'text="{el["text"][:30]}"',
        ]
        lines.append("  - " + " ".join(str(b) for b in bits if b))
    return "\n".join(lines)


def probe_page_url(base: Path, url: str) -> Dict[str, Any]:
    """Open URL with Playwright and extract interactive elements + screenshot."""
    root = ensure_playwright_config(base)
    _ensure_npm_deps(root)
    script = root / "scripts" / "probe_page.mjs"
    if not script.is_file():
        raise RuntimeError("缺少页面探测脚本 ui_tests/scripts/probe_page.mjs")

    node = shutil.which("node")
    if not node:
        raise RuntimeError("未找到 node，请先安装 Node.js")

    env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}
    result = subprocess.run(
        [node, str(script), url.strip()],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        err = (result.stderr or "probe 无输出").strip()
        raise RuntimeError(err[:800])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"probe 输出解析失败: {e}") from e
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "页面探测失败"))

    probe_text = format_page_probe(data)
    stored = {k: v for k, v in data.items() if k != "screenshot_base64"}
    stored["probe_text"] = probe_text
    stored["screenshot_base64"] = data.get("screenshot_base64")
    return stored


async def generate_spec(
    description: str,
    url: Optional[str] = None,
    spec_name: Optional[str] = None,
    image_data_urls: Optional[List[str]] = None,
    page_probe: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    try:
        client = LLMClient()
    except ValueError as e:
        raise ValueError(f"LLM 未配置: {e}") from e

    prompt = f"目标 URL: {url or '未指定'}\n\n需求描述：\n{description}\n\n请输出 JSON。"
    if page_probe:
        probe_text = page_probe.get("probe_text") or format_page_probe(page_probe)
        prompt += f"\n\n【页面探测结果 — 请优先使用下列真实元素编写选择器】\n{probe_text}"
    if image_data_urls:
        prompt += f"\n（附带 {len(image_data_urls)} 张 UI 截图，请结合界面编写选择器与断言。）"
    resp = await client.call(
        prompt=prompt,
        system_message=PLAYWRIGHT_GENERATE_SYSTEM,
        temperature=0.15,
        max_tokens=6000,
        response_format={"type": "json_object"},
        image_data_urls=image_data_urls or None,
    )
    if resp.error:
        raise RuntimeError(resp.error)
    parsed = parse_llm_judge_json(resp.content)
    name = spec_name or parsed.get("spec_name") or "generated.spec.ts"
    return {
        "spec_name": _safe_spec_name(str(name)),
        "spec_content": str(parsed.get("spec_content") or ""),
        "message": str(parsed.get("message") or "脚本已生成"),
    }


def _safe_run_id(run_id: str) -> str:
    safe = (run_id or "").strip()
    if not re.match(r"^\d{8}_\d{6}_[a-f0-9]{6}$", safe):
        raise ValueError(f"无效 run_id: {run_id}")
    return safe


def _ensure_npm_deps(root: Path) -> None:
    if (root / "node_modules" / "@playwright" / "test").exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("未找到 npm。请在 ui_tests 目录执行: npm install")
    logger.info("Installing ui_tests npm dependencies…")
    result = subprocess.run(
        [npm, "install"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "npm install failed").strip()
        raise RuntimeError(f"npm install 失败: {err[:800]}")


def _playwright_test_args(
    root: Path, spec_name: Optional[str] = None, display_mode: str = "background"
) -> List[str]:
    """Use project-local Playwright CLI (reuses %LOCALAPPDATA%\\ms-playwright browsers)."""
    bin_name = "playwright.cmd" if sys.platform == "win32" else "playwright"
    bin_path = root / "node_modules" / ".bin" / bin_name
    if not bin_path.exists():
        raise RuntimeError("未找到本地 Playwright，请在 ui_tests 目录执行: npm install")
    args = [str(bin_path), "test"]
    if spec_name:
        safe = _safe_spec_name(spec_name)
        args.append(f"specs/{safe}")
    mode = (display_mode or "background").strip().lower()
    if mode == "visible":
        args.extend(["--headed", "--workers=1"])
    return args


def _run_playwright_command(
    root: Path, spec_name: Optional[str] = None, display_mode: str = "background"
) -> tuple[int, str]:
    """Run Playwright in a worker thread (Windows uvicorn reload uses SelectorEventLoop)."""
    args = _playwright_test_args(root, spec_name, display_mode)

    try:
        env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1"}
        result = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        log_text = (exc.stdout or "") + (exc.stderr or "")
        if log_text and not log_text.endswith("\n"):
            log_text += "\n"
        return 124, log_text + "[timeout after 600s]"

    log_text = result.stdout or ""
    if result.stderr:
        log_text = f"{log_text}{result.stderr}" if log_text else result.stderr
    return result.returncode, log_text


async def run_playwright_tests(
    base: Path,
    spec_name: Optional[str] = None,
    display_mode: str = "background",
) -> Dict[str, Any]:
    root = ensure_playwright_config(base)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    mode = (display_mode or "background").strip().lower()
    if mode not in ("background", "visible"):
        mode = "background"

    await asyncio.to_thread(_ensure_npm_deps, root)
    exit_code, log_text = await asyncio.to_thread(_run_playwright_command, root, spec_name, mode)
    log_path.write_text(log_text, encoding="utf-8")

    report_dir = root / "runs" / "latest-report"
    meta = {
        "run_id": run_id,
        "exit_code": exit_code,
        "display_mode": mode,
        "log": log_text[-12000:],
        "log_path": str(log_path),
        "report_available": report_dir.exists() and any(report_dir.iterdir()),
        "report_path": "/api/ui-auto/report/latest" if report_dir.exists() else None,
        "finished_at": datetime.now().isoformat(),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_runs(base: Path) -> List[Dict[str, Any]]:
    root = ui_tests_root(base) / "runs"
    out = []
    for p in sorted(root.glob("*/meta.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
            meta["run_id"] = p.parent.name
            out.append(meta)
        except Exception:
            pass
    return out[:50]


def delete_run(base: Path, run_id: str) -> bool:
    safe = _safe_run_id(run_id)
    run_dir = ui_tests_root(base) / "runs" / safe
    if not run_dir.is_dir():
        return False
    shutil.rmtree(run_dir)
    return True


def infer_spec_name_from_log(log_text: str) -> Optional[str]:
    m = re.search(r"specs[\\/][\w.\-]+\.spec\.ts", log_text or "", re.IGNORECASE)
    if not m:
        return None
    return Path(m.group(0).replace("\\", "/")).name


def find_failure_screenshot(base: Path, log_text: str) -> Optional[Path]:
    root = ui_tests_root(base)
    m = re.search(r"(test-results[\\/][^\s\n]+test-failed-\d+\.png)", log_text or "", re.IGNORECASE)
    if m:
        rel = m.group(1).replace("\\", "/")
        candidate = root / rel
        if candidate.exists():
            return candidate
    results = root / "test-results"
    if not results.is_dir():
        return None
    shots = sorted(results.glob("**/test-failed-*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return shots[0] if shots else None


def get_run(base: Path, run_id: str) -> Dict[str, Any]:
    safe = _safe_run_id(run_id)
    run_dir = ui_tests_root(base) / "runs" / safe
    if not run_dir.is_dir():
        raise FileNotFoundError(f"运行记录不存在: {safe}")
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["run_id"] = safe
    log_path = run_dir / "run.log"
    log_full = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else str(meta.get("log") or "")
    meta["log_full"] = log_full
    meta["spec_name"] = infer_spec_name_from_log(log_full)
    shot = find_failure_screenshot(base, log_full)
    meta["has_screenshot"] = shot is not None
    if shot:
        meta["screenshot_path"] = str(shot.relative_to(ui_tests_root(base)))
    err_lines = []
    for line in log_full.splitlines():
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        if not plain:
            continue
        if re.search(r"Error:|timeout| exceeded|failed", plain, re.I):
            err_lines.append(plain)
            if len(err_lines) >= 5:
                break
    meta["error_summary"] = err_lines[0] if err_lines else "测试未通过"
    return meta


def get_run_screenshot_path(base: Path, run_id: str) -> Optional[Path]:
    run = get_run(base, run_id)
    rel = run.get("screenshot_path")
    if not rel:
        return None
    path = (ui_tests_root(base) / str(rel)).resolve()
    root = ui_tests_root(base).resolve()
    if not str(path).startswith(str(root)):
        return None
    return path if path.is_file() else None


def get_latest_report_dir(base: Path) -> Optional[Path]:
    d = ui_tests_root(base) / "runs" / "latest-report"
    if d.exists() and (d / "index.html").exists():
        return d
    return None


def generate_github_workflow(base: Path) -> Dict[str, str]:
    """Generate GitHub Actions workflow template for Playwright."""
    root = ui_tests_root(base)
    workflows = base / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    content = """name: UI Automation (Playwright)

on:
  workflow_dispatch:
  push:
    paths:
      - 'ui_tests/**'

jobs:
  playwright:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install dependencies
        working-directory: ui_tests
        run: npm ci || npm install
      - name: Install Playwright browsers
        working-directory: ui_tests
        run: npx playwright install --with-deps
      - name: Run tests
        working-directory: ui_tests
        run: npx playwright test
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: ui_tests/runs/latest-report/
"""
    path = workflows / "ui-automation.yml"
    path.write_text(content, encoding="utf-8")
    return {"path": str(path.relative_to(base)), "content": content}
