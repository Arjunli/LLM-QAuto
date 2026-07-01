# 场景模板参考

## 公共骨架

```yaml
meta:
  name: <suite-name>
  version: "1.0.0"
  description: ""

target:
  type: api
  connector:
    name: httpx
    config:
      endpoint: <from curl>
      method: POST
      timeout: 120
      retry: 2
      concurrency: 2
      headers:
        Authorization: "Bearer ${ZHIYUAN_BEARER_TOKEN}"
        tenant-id: "${TENANT_ID}"
  input_formatter:
    name: json_payload
    template:
      id: "{{ input.variables.id | int }}"
  output_parser:
    name: json_extractor
    path: data

data_generator:
  strategy: template_cartesian
  prompt_template: "{{ vars.id }}"
  variables:
    - name: id
      type: enum
      values: ["1914"]
  sampling:
    total: 1

evaluation:
  aggregation_method: weighted_average
  dimensions: []

pass_criteria:
  global_criteria:
    min_total_score: 6.0
  dimensions: []
  statistical:
    confidence_level: 0.95
    min_sample_size: 1
```

## listing_qc

复制 `examples/de_copyinfo_regenerate_listing_qc_rubric_batch.yaml` 的 `evaluation.batch_llm` + `dimensions` + `pass_criteria`，只改 `target` 与 `data_generator.variables`。

异步 regenerate 追加：

```yaml
invoke_poll:
  enabled: true
  endpoint: "<GET base>/copy-info/get"
  method: GET
  query:
    id: "{{ input.variables.id }}"
  ready_path: data.title
  timeout: 30
```

## prompt_rewrite_qc

### data_generator 建议变量

```yaml
variables:
  - name: id
    type: enum
    values: ["8001"]
  - name: raw_prompt
    type: enum
    values: ["要欧美模特，不要文字，产品小一点"]
  - name: image_type
    type: enum
    values: ["场景图"]
  - name: site
    type: enum
    values: ["DE"]
  - name: productName
    type: enum
    values: ["锚点产品名"]
```

### batch_llm 六维（帮写 L1 文本质检）

| id | 权重 | 要点 |
|----|------|------|
| intent_fidelity | 0.25 | 原始诉求完整、无曲解 |
| pos_neg_decouple | 0.20 | 正反向分离正确 |
| format_compliance | 0.10 | 含「正向提示词」「反向提示词」或约定格式 |
| professional_rewrite | 0.15 | 口语→专业摄影/构图表达 |
| compliance_coverage | 0.15 | 无文字/Logo/水印等电商合规 |
| no_hallucination | 0.15 | 不臆造颜色/材质/数量 |

`excerpt_mode`: 默认整段 `output`（**不要** `listing`）。

`prompt_template` 须包含：

```
【原始口语】{{ raw_prompt }}
【图类型】{{ image_type }}
【站点】{{ site }}
【产品锚点】{{ productName }}

【帮写 API 返回】
{{ output }}
```

### rule 维度（可选零成本前置）

```yaml
- id: format_rule
  evaluators:
    - type: rule
      rules:
        - name: 含正反向标签
          condition: "contains(output, '正向提示词：') and contains(output, '反向提示词：')"
          severity: error
        - name: 无 markdown 包裹
          condition: "not_contains(output, '```')"
          severity: error
```

### pass_criteria 建议

```yaml
global_criteria:
  min_total_score: 7.0
dimensions:
  - id: intent_fidelity
    min_avg_score: 8.0
  - id: no_hallucination
    min_avg_score: 8.0
  - id: pos_neg_decouple
    min_avg_score: 7.5
```

## image_gen

```yaml
output_parser:
  path: data
  keys: ["revised_prompt"]
  content_mode: image
  media:
    urls_path: "0.url"
    download: true
    max_images: 4
```

评委：`image_rule`（交付率）+ `vision_llm`（图文一致/质量/合规）。`vision_llm` 的 `prompt_template` 含 `{{ prompt }}` 与图片。

## generic

使用 Web 默认三维：content_quality / safety_compliance / format_check，或 `batch_llm` 单次全评 + `excerpt_mode: full`（整段 output）。

## 从 page cURL 批量生成 id

1. 用 page GET cURL 请求一次，解析 `data.list[].id`（路径以实际响应为准）
2. 写入 `data_generator.variables[0].values`
3. 若用户只给范围 `8001-8050`，生成 enum values 列表
