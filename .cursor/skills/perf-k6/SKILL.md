---
name: perf-k6
description: >-
  Generate k6 load test scripts with thresholds (p95, error rate) from scenarios.
  Use for 性能测试, k6, 压测, load test, 弱网, SLA, 阶梯加压. Syncs with Web
  module perf_test.
---

# 性能测试（k6）

从场景描述生成 **k6 脚本 + 阈值 + 运行命令**。

## 触发

- `@perf-k6`
- 压测、性能基线、阶梯加压、SLA 验收
- 工作台 → **性能测试**

## 输入

- API 列表或用户旅程（登录 → 列表 → 提交）
- VU / 时长 / 目标 QPS
- SLA：p95、错误率上限
- **环境**：预发/测试（默认）；生产须用户明确确认

## 交付（Cursor 与 Web 同结构）

1. **scenario_summary** — 加压模型（constant-vus / ramping-vus / 阶梯）
2. **k6_script** — 完整 JS（含 `export default function`、thresholds）
3. **run_command** — 如 `k6 run perf/k6/xxx.js`
4. **thresholds_note** — p95 / 错误率说明
5. **message**

## Cursor 输出 JSON

```json
{
  "scenario_summary": "…",
  "k6_script": "import http from 'k6/http';\n…",
  "run_command": "k6 run perf/k6/orders.js",
  "thresholds_note": "…",
  "message": "…"
}
```

落盘：`perf/k6/<name>.js`；前置安装 [k6](https://k6.io/docs/get-started/installation/)。

## 脚本要点

- `setup()` 登录，Token 读 `__ENV.TOKEN`
- 关键路径用 `group()` 分段
- `thresholds` 必含，例如：

```javascript
thresholds: {
  http_req_duration: ['p(95)<800'],
  http_req_failed: ['rate<0.01'],
}
```

## Web 联动

| 项 | 值 |
|----|-----|
| 模块 id | `perf_test` |
| 生成 | `POST /api/workbench/perf/generate` |
| 保存 / 列表 / 删除 | `POST/GET/DELETE /api/workbench/perf/sessions[/{id}]` |
| skill_id | `perf-k6` |

## 禁止

- 未确认环境对生产全速压测
- 无 thresholds 的「只跑不判」
