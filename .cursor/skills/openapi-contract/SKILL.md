---
name: openapi-contract
description: >-
  Generate API contract test matrices and pytest/httpx skeletons from OpenAPI or
  Swagger. Use for 接口契约, contract testing, Swagger, OpenAPI, REST 契约,
  schema validation. Syncs with Web module api_contract.
---

# 接口契约（OpenAPI）

从 OpenAPI 3 / Swagger 2 或接口列表生成**契约矩阵 + pytest 骨架**。

## 触发

- `@openapi-contract`
- Swagger URL、openapi.json/yaml、paths 片段
- 工作台 → **接口契约** → 快速生成

## 输入

- OpenAPI 内容或接口清单
- base URL、鉴权（Bearer / API Key → `os.environ`）
- 范围：全量或指定 tag/模块

## 交付（Cursor 与 Web 同结构）

1. **assumptions** — 范围与缺口（markdown）
2. **contract_matrix_markdown** — | 方法 | 路径 | 场景 | 期望状态码 | 关键断言 |
3. **pytest_skeleton** — pytest + httpx，Token 用环境变量
4. **message** — 简短说明

须含：正向、401/403、缺必填/类型错误、分页边界（如适用）。

## Cursor 输出 JSON

```json
{
  "assumptions": "…",
  "contract_matrix_markdown": "| 方法 | 路径 | …",
  "pytest_skeleton": "import pytest\n…",
  "message": "…"
}
```

落盘建议：`tests/contract/test_<service>.py`（从 `pytest_skeleton` 写入）。

## Web 联动

| 项 | 值 |
|----|-----|
| 模块 id | `api_contract` |
| 生成 | `POST /api/workbench/contract/generate` `{ "input_text", "title?" }` |
| 保存 | `POST /api/workbench/contract/sessions` |
| 列表 / 读取 / 删除 | `GET/DELETE /api/workbench/contract/sessions[/{id}]` |
| skill_id | `openapi-contract` |

## 禁止

- 硬编码生产 Token
- 未读 schema 就写「返回正常」类断言

## 延伸阅读

- API 批量评判仍用 `@qauto-from-curl`（LLM 评输出内容，非 schema 契约）
