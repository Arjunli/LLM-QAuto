# LLM-QAuto - 通用AI智能体测试平台

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 由AI测AI，以通用框架支持任何生成式AI能力的质量评估

## 核心特性

- **通用框架** - 不绑定任何特定领域，支持文案、代码、对话、SQL、**文生图**等多种场景
- **双模态测评** - 同一套 YAML/引擎：`content_mode` 自动区分纯文本、纯图像、图文混合
- **配置驱动** - 测试场景完全通过YAML配置定义，无需修改代码
- **三层评判** - 规则引擎（零成本）+ LLM评判（语义级）+ 人工抽检
- **占比统计** - 自动计算各类别分布及95%置信区间
- **成本优化** - 自适应抽样、评判缓存、提前终止策略
- **多种报告** - HTML/JSON/Markdown/CSV多种格式输出

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/example/llm-qauto.git
cd llm-qauto

# 安装依赖
pip install -r requirements.txt

# 或使用 pip install -e .
pip install -e .
```

### 生成示例配置

```bash
qauto init --output ./examples
```

### 运行测试

```bash
# 设置API密钥
export OPENAI_API_KEY="your-api-key"

# 运行文案生成测试
qauto run --config examples/copywriting_test.yaml --output ./output

# 运行代码生成测试
qauto run --config examples/code_generation_test.yaml --output ./output

# 保存原始数据并生成所有格式报告
qauto run --config examples/chatbot_test.yaml --output ./output \
          --format html,json,md,csv --save-artifacts
```

### 验证配置

```bash
qauto validate --config examples/copywriting_test.yaml
```

## 工作原理

```
┌─────────────────────────────────────────────────────────────┐
│                     通用测试流程                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 配置加载 (YAML)                                          │
│     ├── 被测对象定义 (API/本地模型)                           │
│     ├── 数据生成策略 (模板/模糊/对抗)                         │
│     ├── 评判维度 (规则/LLM/向量/参考)                         │
│     └── 通过标准 (占比/分数/置信区间)                         │
│                                                             │
│  2. 批量调用 (并发控制)                                       │
│     ├── 生成 N 个测试输入                                     │
│     ├── 格式化输入 → 调用被测AI                               │
│     └── 解析输出 → 保存原始数据                               │
│                                                             │
│  3. 三层评判                                                 │
│     ├── 规则引擎 (硬性检查，零成本)                           │
│     ├── LLM评判 (语义分类，按配置)                          │
│     └── 聚合结果 (加权平均)                                   │
│                                                             │
│  4. 统计与门禁                                               │
│     ├── 各类别占比 + 95%置信区间                              │
│     ├── 与产品定义目标对比                                    │
│     └── 判定通过/失败                                        │
│                                                             │
│  5. 报告输出                                                 │
│     ├── HTML (美观的网页报告)                                 │
│     ├── JSON (机器可读，CI集成)                               │
│     ├── Markdown (便于文档嵌入)                               │
│     └── CSV (数据分析)                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 配置详解

### 被测对象配置

```yaml
target:
  type: "api"  # api | local_model
  connector:
    name: "httpx"  # http_json | httpx | local_model
    config:
      endpoint: "https://api.example.com/v1/chat"
      headers:
        Authorization: "Bearer ${API_KEY}"
      concurrency: 5
  
  input_formatter:
    name: "json_payload"
    template:  # Jinja2模板
      messages:
        - role: "user"
          content: "{{input.prompt}}"
  
  output_parser:
    name: "json_extractor"
    path: "choices.0.message.content"  # JSON路径
```

### 文生图 / 混合模态解析

在 `output_parser` 中增加 `media` 块即可从 JSON 响应提取图片 URL 或 base64，并下载到 `artifacts/images/`：

```yaml
output_parser:
  name: json_extractor
  path: "data"                    # 可选：文本/JSON 摘要给 llm 评委
  keys: ["revised_prompt"]
  content_mode: image             # auto | text | image | mixed
  media:
    urls_path: "0.url"            # 相对 path 所指节点的图片 URL 列表
    download: true
    max_images: 4
```

- **文案测评**：不配 `media`，行为与原先完全一致（`content_mode: text`）。
- **生图测评**：配置 `media` + `vision_llm` / `image_rule` 评委（见 `examples/image_generation_test.yaml`）。
- **图文混合**：同时保留 `keys` 与 `media`，`content_mode: mixed`，文本维度用 `llm`，画面维度用 `vision_llm`。

### 评判维度配置

```yaml
evaluation:
  dimensions:
    - id: "style_classification"
      name: "风格分类"
      weight: 0.5
      
      evaluators:
        # 1. 规则引擎 (零成本)
        - type: "rule"
          rules:
            - name: "长度检查"
              condition: "len(output) >= 10"
        
        # 2. LLM评判
        - type: "llm"
          model: "gpt-4o-mini"
          prompt_template: |
            判断以下文案风格：促销型/情感型/说明型
            
            文案：{{output}}
            
            返回JSON：
            {
              "categories": ["风格标签"],
              "score": 0-10,
              "confidence": 0-1
            }
        
        # 3. 向量相似度
        - type: "embedding"
          model: "text-embedding-3-small"
          reference_pool: "./references.jsonl"
```

### 通过标准配置

```yaml
pass_criteria:
  dimensions:
    - id: "style_classification"
      min_avg_score: 6.5
      max_fail_rate: 0.1
      
      # 类别占比目标（核心）
      category_distribution:
        - category: "促销型"
          min_percent: 30
          max_percent: 50
        
        - category: "情感型"
          min_percent: 20
          max_percent: 40
        
        - category: "违规"
          max_percent: 5
          fail_if_exceed: true  # 超过直接失败
```

## 示例场景

### 1. 文案生成测试

测试营销文案的风格分布和合规性：

```bash
qauto run --config examples/copywriting_test.yaml
```

关键指标：
- 促销型文案占比 30%-50%
- 情感型文案占比 20%-40%
- 违规内容占比 ≤5%

### 2. SQL生成测试

测试代码生成的语法正确性和安全性：

```bash
qauto run --config examples/code_generation_test.yaml
```

关键指标：
- 语法通过率 ≥95%
- 语义正确率 ≥90%
- 安全问题零容忍

### 3. 对话Agent测试

测试客服机器人的任务完成度和共情能力：

```bash
qauto run --config examples/chatbot_test.yaml
```

关键指标：
- 任务完成度 ≥70%
- 共情能力平均分 ≥6.5
- 安全合规率 100%

### 4. 文生图质量测试

与文案测评共用 CLI / Web UI，需配置多模态评委模型（如 `gpt-4o` 或方舟视觉接入点）：

```bash
qauto run --config examples/image_generation_test.yaml --output ./output --save-artifacts
```

关键指标：
- 图像成功交付率 100%
- 图文一致性平均分 ≥6.0
- 画面质量与安全 ≥6.0

## 评判器类型

| 评判器 | 类型 | 适用场景 | 成本 |
|--------|------|----------|------|
| `rule` | 规则引擎 | 格式、长度、关键词、正则 | 零 |
| `llm` | LLM评判 | 语义、风格、符合度 | 低-中 |
| `embedding` | 向量相似度 | 语义相似度比较 | 低 |
| `reference` | 参考对比 | 与标准答案对比 | 零-低 |
| `image_rule` | 图像规则 | 是否出图、落盘、体积等 | 零 |
| `vision_llm` | 视觉 LLM | 图文一致、画面质量、安全 | 中-高 |
| `code_exec` | 代码执行 | 代码可执行性验证 | 中 |

## CI/CD集成

在CI流程中使用：

```yaml
# .github/workflows/ai-test.yml
name: AI Quality Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run AI Tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          qauto run \
            --config tests/ai/copywriting_test.yaml \
            --output test-results \
            --format json
      
      - name: Check Results
        run: |
          if [ $(cat test-results/*/report.json | jq -r '.ci_status') == "fail" ]; then
            echo "AI测试未通过"
            exit 1
          fi
```

## 扩展开发

### 自定义评判器

```python
from llm_qauto.plugins import BaseEvaluator, register_plugin
from llm_qauto.models import DimensionResult

@register_plugin("evaluator", "my_custom")
class MyEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "my_custom"
    
    async def judge(self, output, config, context):
        # 实现你的评判逻辑
        return DimensionResult(
            dimension_id=config["dimension_id"],
            evaluator_type="my_custom",
            passed=True,
            score=8.5,
            categories=["custom_category"],
            confidence=0.9
        )
```

### 自定义连接器

```python
from llm_qauto.plugins import BaseConnector, register_plugin

@register_plugin("connector", "my_api")
class MyConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "my_api"
    
    async def call(self, formatted_input):
        # 实现你的API调用
        pass
```

## 项目结构

```
llm-qauto/
├── src/llm_qauto/
│   ├── __init__.py
│   ├── models.py           # 核心数据模型
│   ├── engine.py           # 测试执行引擎
│   ├── config_loader.py    # 配置加载
│   ├── statistics.py       # 统计工具
│   ├── cli.py              # 命令行入口
│   ├── plugins/            # 插件目录
│   │   ├── __init__.py
│   │   ├── connectors.py   # 连接器插件
│   │   ├── generators.py   # 数据生成器
│   │   └── evaluators.py   # 评判器
│   └── reporters/          # 报告生成器
│       ├── __init__.py
│       ├── html_reporter.py
│       ├── json_reporter.py
│       ├── markdown_reporter.py
│       └── csv_reporter.py
├── examples/               # 示例配置
│   ├── copywriting_test.yaml
│   ├── code_generation_test.yaml
│   └── chatbot_test.yaml
├── requirements.txt
├── pyproject.toml
└── README.md
```

## 成本估算

以100次文案生成测试为例：

| 环节 | 调用次数 | 预估成本 |
|------|----------|----------|
| 被测AI调用 | 100次 | 取决于你的API |
| LLM评判 | 100次 (gpt-4o-mini) | ~$0.05-0.10 |
| 规则评判 | 100次 | $0 |
| **总计** | | **<$0.10** |

成本优化策略：
- 使用自适应抽样减少不必要的评判
- 评判结果缓存避免重复评判相同输出
- 分层评判：规则先筛，LLM后判

## 贡献指南

欢迎提交Issue和PR！

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 联系方式

- 项目主页: https://github.com/example/llm-qauto
- 问题反馈: https://github.com/example/llm-qauto/issues
