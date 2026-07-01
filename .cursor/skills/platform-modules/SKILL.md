---
name: platform-modules
description: >-
  Extend LLM-QAuto with new testing modules and Cursor skills. Use when adding
  capabilities, modules.yaml entries, or new SKILL.md for the 测试工作台.
---

# 扩展平台模块

## 架构

```
modules.yaml                    ← 模块清单
.cursor/skills/<id>/SKILL.md    ← Cursor @触发
src/llm_qauto/platform/         ← 业务服务
src/llm_qauto/web/static/*-ui.js ← 前端
```

## 当前模块

| id | skill | Web |
|----|-------|-----|
| api_qc | qauto-from-curl | 完整 |
| case_design | test-case-design | 完整 |
| ui_automation | ui-playwright | 完整 |
| api_contract | openapi-contract | 工作台 `workbench-ui.js` |
| perf_test | perf-k6 | 工作台 |
| mock_data | mock-data | 工作台 |

## 新增「工作台型」模块（推荐）

1. 在 `workbench_service.PROMPTS` 增加 prompt
2. 在 `KIND_ALIASES` 增加 URL 段映射
3. 在 `workbench-ui.js` 的 `WORKBENCH` 增加 UI 配置
4. 在 `modules.yaml` 增加条目（参考 `mock_data`）
5. 在 `platform-shell.js` 的 `WORKBENCH_MODULE_IDS` 加入 module id
6. 创建 `.cursor/skills/<skill-id>/SKILL.md`

API 已统一：`POST /api/workbench/{contract|perf|mock}/generate` 与同路径 sessions CRUD。

## 禁用模块

```yaml
enabled: false
```
