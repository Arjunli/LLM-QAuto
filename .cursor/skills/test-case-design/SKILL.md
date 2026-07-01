---
name: test-case-design
description: >-
  Derives functional test cases, Mermaid test tree, and review matrices from PRD
  and acceptance criteria. Use for 用例设计, 测试树, test cases, PRD-to-tests,
  验收标准覆盖. Syncs with Web module case_design.
---

# 用例设计（Web + Skill 同步）

与 Cursor Skill `test-case-review` 同规则，输出格式一致；可保存到 Web 服务端。

## 触发

- `@test-case-design`
- 用户要 PRD → 测试树 + 用例表
- 工作台 **用例设计** 模块

## 交付顺序

1. **假设与缺口**（须含 **覆盖维度** 小节）
2. **评审概览图**（`mermaid_review` — flowchart：主流程 + 按类型/模块分组的 TC，供评审快速过一遍）
3. **测试覆盖树**（`mermaid_tree` — 全部 TC 编号导航）
4. **用例表**（| 编号 | 模块 | 前置条件 | 步骤 | 测试数据 | 期望结果 | 优先级 | 类型 | 关联需求 ID | 风险/备注 |）

Web 端会自动 **渲染 Mermaid 为 SVG**；源码可折叠查看。

## 图表样式（覆盖树 / 评审图）

- **禁止 mindmap**（中心大圆、灰阶、难读）；统一 `flowchart TB` + `subgraph` 按模块分组。
- 节点：`:::root` 根、`:::mod` 模块、`:::tc` 用例、`:::nf` 非功能、`:::p0` 高优先级。
- 文末附 5 行 `classDef`（蓝/浅蓝/白/黄/红），与 Web `case-mermaid.js` 主题一致。

## 覆盖维度（Web 生成与 Cursor 输出均须评估）

| 维度 | 说明 | Web 场景默认 |
|------|------|--------------|
| 功能 | 主流程、分支、取消回退 | 必有 |
| 边界/异常 | 空值、极值、非法输入 | 必有 |
| 弱网 | 高延迟、加载态、超时、重试 | **必有** |
| 稳定性 | 断网/恢复、接口失败、数据不丢 | **必有** |
| 权限/安全 | 角色差异、越权 | 涉及时必有 |
| 并发 | 连点、重复提交、双 Tab | 提交类操作评估 |
| 兼容/易用性 | 浏览器、空态、文案 | Web 至少 1 条或说明 N/A |
| 性能 | SLA、大数据量、导出 | 有要求时评估 |

**类型**列可用：功能、边界、异常、权限、安全、兼容、性能、**弱网**、**稳定性**、并发、易用性、数据一致性。

简单功能也至少 **8 条**用例（含 ≥2 条非功能）。规则细节同 `test-case-review`。

## Web 联动（模块 `case_design`）

| 项 | 值 |
|----|-----|
| 模块 id | `case_design` |
| Web 入口 | 工作台 → **用例设计** |
| 用例助手 | `POST /api/cases/chat` — 多轮收集 PRD，说「生成用例」触发 |
| 快速生成 | `POST /api/cases/generate` body `{ "input_text", "title?" }` |
| 保存会话 | `POST /api/cases/sessions` |
| 列表 / 读取 | `GET /api/cases/sessions` · `GET /api/cases/sessions/{id}` |
| 删除 | `DELETE /api/cases/sessions/{id}` |
| 导出 CSV | `GET /api/cases/sessions/{id}/export.csv` |
| Manifest | `GET /api/platform/modules` → `skill_id: test-case-design` |

生成失败时会**自动重试**；必要时**分步生成**（先表后图）。`mindmap` 会自动转为 `flowchart` 以便 Web 渲染。

## Cursor 输出 JSON（与 Web generate 一致）

```json
{
  "assumptions": "…",
  "mermaid_review": "flowchart TB …",
  "mermaid_tree": "flowchart TB …",
  "case_table_markdown": "| 编号 | 模块 | …",
  "message": "…"
}
```

## 推送到 Web（可选）

```bash
curl -X POST http://127.0.0.1:8080/api/cases/sessions \
  -H "Content-Type: application/json" \
  -d '{"title":"...","input_text":"...","assumptions":"...","mermaid_review":"...","mermaid_tree":"...","case_table_markdown":"..."}'
```

## 禁止

- 树与表 TC 编号不一致
- 不可执行的模糊期望（「系统正常」）
- 无依据的负向用例堆砌
