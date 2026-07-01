---
name: qauto-from-curl
description: >-
  Builds LLM-QAuto test project YAML from browser cURL plus follow-up questions
  when inputs are incomplete. Use when the user provides cURL, asks to create or
  scaffold a test project/suite, 建测试项目, 帮写测评, Listing 质检, 生图测评,
  copy-info API evaluation, or wants curl parsed into web_uploads config.
---

# LLM-QAuto：cURL → 测试项目

从用户提供的 cURL（及可选补充信息）生成 `web_uploads/*.yaml`，并在信息不足时**先追问、后落盘**。

## 触发后流程

```
1. 解析用户输入 → 2. 对照必填清单 → 3. 缺则追问 → 4. 选场景模板 → 5. 写 YAML → 6. validate → 7. 告知如何跑
```

**禁止**：在必填项未齐时写 YAML；猜测 Token/字段名/异步 poll；把 Bearer 明文写进 YAML。

## 必填清单（缺一必问）

| 项 | 说明 |
|----|------|
| 被测 cURL | 浏览器 DevTools 复制的 HTTPS 请求（POST/GET 均可） |
| 场景类型 | `listing_qc` \| `prompt_rewrite_qc` \| `image_gen` \| `generic` |

## 条件追问（按场景）

### 所有场景

- **响应样例**：用户未给且无法从 cURL 推断 `output_parser.path` / `keys` 时 → 请贴一条 JSON，或调用 `POST /api/config/probe`（需 Web 已启动）
- **鉴权**：默认**保留 cURL 内 Authorization**，`use_env_token=false`；不要问是否改 `.env`
- **批量 id**：问「单条试跑 / 手填范围 / page 列表 cURL」三选一

### listing_qc

- regenerate 类：是否异步？若是 → 要 **poll GET cURL** + `ready_path`（如 `data.title`）
- 锚点字段：`id, sku, site, productName, productParameters, status` 是否与 body 一致
- 模板：`examples/de_copyinfo_regenerate_listing_qc_rubric_batch.yaml`

### prompt_rewrite_qc（帮写 L1）

- 原始口语字段名（如 `rawPrompt`）
- 图类型字段（如 `imageType`），若无则问是否固定一种类型
- 帮写结果 JSON path（如 `data.optimizedPrompt` 或整段 `data`）
- 评委需对比 **原始输入 vs 帮写输出** → `batch_llm.prompt_template` 必须含 `{{ raw_prompt }}` 等变量
- 维度与 rule 见 [templates.md](templates.md#prompt_rewrite_qc)

### image_gen

- 返回是图片 URL 还是 base64
- `media.urls_path` 相对 `output_parser.path` 的路径
- 是否同时评文案字段（mixed）还是纯图（image）
- 视觉评委模型（默认读 `.env` 的 `LLM_PROVIDER` / `BAIDU_VOD_MODEL` 等）

### generic

- 评委：单次全评 / 分维 / 仅 rule
- 通过标准：`min_total_score`、关键维度门槛

## 追问方式

1. **2～4 个固定选项** → 用 `AskQuestion`（场景类型、批量方式、是否异步等）
2. **开放信息**（JSON 样例、字段名）→ 对话文字，一次只问 1～2 项，避免问卷轰炸
3. **可推断则不问**（如 GET `?id=1914` → 变量 `id`）

## cURL 解析规则（与 Web 表单一致）

- URL → `target.connector.config.endpoint`（GET 带 query 时 endpoint 不含 query，query 进 template）
- `-H` → `headers`（过滤 `Host`/`Content-Length`；Bearer 改 env 占位符）
- `--data-raw` / `-d` JSON → `input_formatter.template`；数字/短字符串 → `{{ input.variables.xxx }}`
- 多条 cURL：优先 **详情/get?id=** 作被测接口；**page/list** 用于拉测试 id 列表
- 不支持 `@file` 请求体 → 让用户贴 JSON

## YAML 落盘

- 路径：`web_uploads/<scene>_<api_slug>_<date>.yaml`
- 参考：`src/llm_qauto/web/static/config-editor.js` 的 `MINIMAL_TEMPLATE_YAML`、`ensureConfigSkeleton`
- `meta.name`：短横线命名，与业务一致
- 保存后执行：`python -m llm_qauto.cli validate --config <path>`（或 `qauto validate`）
- 可选启动跑批：`POST http://127.0.0.1:8080/api/runs` body `{"config_path": "..."}`

## 生成后交付给用户

1. 配置文件路径
2. 场景与评委维度摘要
3. 测试数据如何填（变量名、建议 id 范围）
4. Web 打开方式：`http://127.0.0.1:8080`（注意端口 **8080**，不是 8000）
5. 仍缺什么（如未给 page curl 则批量需手填）

## 禁止猜测项

- 真实 Token / API Key
- 未在 cURL 或响应中出现的字段 path
- 帮写/生图专用维度（用户选了 generic 却套 Listing 七维）
- `invoke_poll`（除非用户确认异步且提供 GET cURL）

## 延伸阅读

- 各场景 YAML 骨架与帮写评委维度：[templates.md](templates.md)
- Listing 完整示例：`examples/de_copyinfo_regenerate_listing_qc_rubric_batch.yaml`
- 帮写示例：`examples/prompt_rewrite_qc_batch.yaml`
- **Web UI**：侧边栏「从 cURL 快速创建」四步向导；**「配置助手」** 聊天页（`/api/assistant/chat`）多轮追问并生成 YAML

## Web 联动（模块 `api_qc`）

| 项 | 值 |
|----|-----|
| 工作台模块 id | `api_qc` |
| Web 入口 | `http://127.0.0.1:8080` → **API 质检** |
| Manifest | `GET /api/platform/modules` → `skill_id: qauto-from-curl` |
| 配置助手 | `POST /api/assistant/chat` — 多轮追问 + 生成 YAML |
| cURL 向导 | 侧边栏「从 cURL 快速创建」 |
| 探测响应 | `POST /api/config/probe`（推断 output_parser） |
| 创建项目 | `POST /api/projects` body `{ name, config_yaml }` |
| 运行测试 | `POST /api/runs` body `{ config_path }` |
| Cursor | `@qauto-from-curl` 或粘贴 cURL |

## 与其他 Skill 的分工

| 需求 | 用哪个 |
|------|--------|
| LLM 评判 API **输出质量**（帮写/Listing/生图） | `@qauto-from-curl` |
| OpenAPI **字段/状态码契约** | `@openapi-contract` |
| 联调 **Mock 服务** | `@mock-data` |
| 接口 **压测** | `@perf-k6` |
