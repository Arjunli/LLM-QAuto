# LLM-QAuto Skills 索引

与 `src/llm_qauto/platform/modules.yaml` 一一对应。Web 入口：`http://127.0.0.1:8080`（默认 **8080**）。

| Skill | 模块 id | Web | 一句话 |
|-------|---------|-----|--------|
| `@qauto-from-curl` | `api_qc` | 完整 | cURL → 测评 YAML + 批量 LLM 评判 |
| `@test-case-design` | `case_design` | 完整 | PRD → 评审图 + 覆盖树 + 用例表 |
| `@ui-playwright` | `ui_automation` | 完整 | URL 探测 → Playwright 脚本 + 本机运行 |
| `@openapi-contract` | `api_contract` | 工作台 | OpenAPI → 契约矩阵 + pytest 骨架 |
| `@perf-k6` | `perf_test` | 工作台 | 场景 → k6 脚本 + 阈值 |
| `@mock-data` | `mock_data` | 工作台 | 接口说明 → Mock 清单 + FastAPI 代码 |

扩展新模块见 [platform-modules/SKILL.md](platform-modules/SKILL.md)。
