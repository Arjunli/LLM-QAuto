---
name: mock-data
description: >-
  Generate API mock specs, FastAPI mock servers, and sample JSON from OpenAPI or
  interface descriptions. Use for Mock, 造数, 接口 mock, stub, FastAPI mock.
  Syncs with Web module mock_data.
---

# Mock 与造数

从接口说明 / OpenAPI 片段生成 **Mock 清单 + 样例 JSON + 可运行 Mock 服务**。

## 触发

- `@mock-data`
- 联调 stub、前端并行、测试造数
- 工作台 → **Mock 造数**

## 输入

- 接口列表（方法、路径、字段）或 OpenAPI paths
- 需覆盖的场景：成功 / 空列表 / 422 / 403 / 500 等

## 交付（Cursor 与 Web 同结构）

1. **assumptions** — Mock 策略（markdown）
2. **mock_spec_markdown** — | 方法 | 路径 | 场景 | 响应要点 | 状态码 |
3. **sample_responses_json** — 典型 JSON 样例（字符串）
4. **mock_server_code** — FastAPI 单文件，可 `uvicorn` 启动
5. **message**

## Cursor 输出 JSON

```json
{
  "assumptions": "…",
  "mock_spec_markdown": "| 方法 | 路径 | …",
  "sample_responses_json": "{ … }",
  "mock_server_code": "from fastapi import FastAPI\n…",
  "message": "…"
}
```

## 落盘与运行

```bash
# 将 mock_server_code 写入 mock_server.py 后：
pip install fastapi uvicorn
uvicorn mock_server:app --reload --port 9090
```

## Web 联动

| 项 | 值 |
|----|-----|
| 模块 id | `mock_data` |
| 生成 | `POST /api/workbench/mock/generate` |
| 保存 / 列表 / 删除 | `POST/GET/DELETE /api/workbench/mock/sessions[/{id}]` |
| skill_id | `mock-data` |

## 禁止

- 硬编码真实 Token/密码
- 只有 200 成功、无错误态/空态 Mock

## 延伸阅读

- 契约字段校验 → `@openapi-contract`
- 压测 Mock 服务 → `@perf-k6`
