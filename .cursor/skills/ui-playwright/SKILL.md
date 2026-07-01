---
name: ui-playwright
description: >-
  Generate Playwright TypeScript specs, run locally, and optional GitHub Actions CI.
  Use for UI 自动化, E2E, Playwright, 页面回归, browser testing. Syncs with Web
  module ui_automation.
---

# UI 自动化（Playwright）

生成、保存、本机运行 Playwright 测试；可选生成 GitHub Actions 工作流。

## 触发

- `@ui-playwright`
- 用户描述页面流程 / 要 E2E 回归
- 工作台 **UI 自动化** 模块

## 输出

1. `ui_tests/specs/<name>.spec.ts` — 使用 `@playwright/test`
2. 运行说明：`cd ui_tests && npm install && npx playwright install && npx playwright test`
3. 可选：`.github/workflows/ui-automation.yml`

## 脚本规范

```typescript
import { test, expect } from '@playwright/test';

test('描述', async ({ page }) => {
  await page.goto('https://...');
  // ...
});
```

- 敏感信息用 `process.env`，不要硬编码 Token
- 步骤带中文注释

## Web 联动（模块 `ui_automation`）

| 项 | 值 |
|----|-----|
| 模块 id | `ui_automation` |
| Web 入口 | 工作台 → **UI 自动化** |
| 页面探测 | `POST /api/ui-auto/probe` body `{ "url" }` — Playwright 打开页面，返回可交互元素 + 截图 |
| AI 生成 | `POST /api/ui-auto/generate` body `{ "description", "url?" }` — **有 url 时自动先探测再生成** |
| 助手对话 | `POST /api/ui-auto/chat` — 用户说「生成脚本」且 collected 含 url 时同样自动探测 |
| 保存脚本 | `POST /api/ui-auto/specs` body `{ "name", "content" }` |
| 本机运行 | `POST /api/ui-auto/run` body `{ "spec_name?", "display_mode": "background|visible" }` |
| 运行记录 | `GET /api/ui-auto/runs` · `GET /api/ui-auto/runs/{id}` · `DELETE .../runs/{id}` |
| 失败修复 | 运行记录 →「交给助手修复」→ `POST /api/ui-auto/chat`（带 `fix_context` + 截图） |
| 报告 | `GET /api/ui-auto/report/latest`（需先跑过 test） |
| CI 模板 | `POST /api/ui-auto/ci/generate-workflow` |
| 目录 | `ui_tests/specs/`, `ui_tests/runs/`, `ui_tests/scripts/probe_page.mjs` |
| Manifest | `GET /api/platform/modules` → `skill_id: ui-playwright` |

## 页面探测（提高脚本精度）

用户提供 **URL** 时，生成前应优先探测真实 DOM：

1. **Cursor / Skill**：若用户给了链接，可调用 `POST /api/ui-auto/probe` 或本机 `node ui_tests/scripts/probe_page.mjs "<url>"` 查看元素列表。
2. **Web 助手**：生成脚本前自动探测；用户可说「重新探测」强制刷新。
3. **生成 prompt**：探测结果（标题、headings、input/button 的 id/name/placeholder/data-testid）会注入 LLM，并附带首屏截图。

选择器优先级：`data-testid` > `role`+name > `#id` > `[name]` > placeholder/text > CSS。

## 运行模式

- `display_mode: background` — 无头后台（默认）
- `display_mode: visible` — 弹出浏览器，便于调试（`--headed --workers=1`）

## 与用例设计联动

页面流程已有 TC 表时，可引用 `TC-xxx` 步骤编写 spec；断言与用例表期望结果保持一致。

## 前置依赖

本机跑需要 Node.js：

```bash
cd ui_tests
npm install
npx playwright install
```

## 禁止

- 在 spec 外目录写脚本
- 执行任意 shell（Web 仅允许 `ui_tests/` 下 playwright 命令）
