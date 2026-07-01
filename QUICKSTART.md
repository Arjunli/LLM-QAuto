# 快速开始指南

## 环境准备

### 1. 安装 Python 依赖

```bash
cd LLM-QAuto
pip install -r requirements.txt
```

### 2. 设置 API 密钥

```bash
# Windows PowerShell
$env:OPENAI_API_KEY="your-api-key-here"

# Windows CMD
set OPENAI_API_KEY=your-api-key-here

# Linux/Mac
export OPENAI_API_KEY=your-api-key-here
```

或在项目根目录使用 `.env`（`web_server.py` 会自动加载）。

## Web 界面（推荐）

日常创建套件、运行测试、看报告都在浏览器完成：

```bash
python web_server.py
```

浏览器访问 **http://localhost:8080**。

## 命令行（可选，无界面 / CI）

与已移除的 `run_test.py` 等价：`run_test.py` 仅转发到 `qauto`。安装后可直接使用：

```bash
qauto validate --config examples/copywriting_test.yaml
qauto run --config examples/copywriting_test.yaml --output ./output
```

也可用：

```bash
python -m llm_qauto.cli run --config examples/copywriting_test.yaml --output ./output
```

### 多格式报告与变量示例

```bash
qauto run --config examples/copywriting_test.yaml \
    --output ./output \
    --format html,json,md,csv \
    --save-artifacts

qauto run --config examples/copywriting_test.yaml \
    --var api_key=xxx \
    --var model=gpt-4
```

## 查看报告

- **Web**：运行结束后在界面中查看或下载。
- **CLI**：报告在 `./output/{run_id}/`（`report.html`、`report.json` 等）。

```
output/
└── copywriting_test_20240515_143022/
    ├── report.html
    ├── report.json
    ├── report.md
    ├── report.csv
    └── artifacts/          # 若使用 --save-artifacts
        ├── config.json
        └── raw_outputs.jsonl
```

## 创建自己的测试配置

复制示例配置并修改：

```bash
cp examples/copywriting_test.yaml my_test.yaml
```

主要修改点：

### 1. 被测对象（target）

```yaml
target:
  connector:
    config:
      endpoint: "你的API地址"
      headers:
        Authorization: "Bearer ${YOUR_API_KEY}"
```

### 2. 测试数据（data_generator）

```yaml
data_generator:
  variables:
    - name: "场景"
      type: "enum"
      values: ["场景1", "场景2", "场景3"]
  sampling:
    total: 100
```

### 3. 文生图（与文案共用引擎）

在 `output_parser` 增加 `media` 下载图片，评委使用 `image_rule`（零成本）与 `vision_llm`（多模态模型）：

```bash
qauto run --config examples/image_generation_test.yaml --output ./output --save-artifacts
```

详见 `examples/image_generation_test.yaml` 与 README「文生图 / 混合模态解析」。

### 4. 评判标准（evaluation）

```yaml
evaluation:
  dimensions:
    - id: "你的维度"
      evaluators:
        - type: "llm"
          prompt_template: |
            请评判：{{output}}
            返回JSON：{"score": 0-10, "passed": true/false}
```

### 4. 通过标准（pass_criteria）

```yaml
pass_criteria:
  dimensions:
    - id: "你的维度"
      min_avg_score: 7.0
      category_distribution:
        - category: "类别A"
          min_percent: 30
          max_percent: 50
```

## CI/CD 集成

```bash
qauto run --config my_test.yaml --output ./test-results --format json

# 检查结果（Bash）
if [ $(cat test-results/*/report.json | jq -r '.ci_status') == "fail" ]; then
    echo "测试未通过"
    exit 1
fi

# 检查结果（PowerShell）
$report = Get-Content test-results/*/report.json | ConvertFrom-Json
if ($report.ci_status -eq "fail") {
    Write-Error "测试未通过"
    exit 1
}
```

## 常见问题

### Q: API 调用失败？

检查：`OPENAI_API_KEY`、网络、账户余额。

### Q: 如何降低 API 成本？

1. 减少 `sampling.total`
2. 评判模型用 `gpt-4o-mini` 等
3. 启用评判缓存（默认已启用）
4. 优先规则评判器

### Q: 如何调试评判结果？

CLI 使用 `--save-artifacts`，查看 `artifacts/raw_outputs.jsonl`。

## 下一步

- 阅读 `README.md` 了解完整功能
- 查看 `examples/` 目录学习更多示例
- 自定义评判器扩展功能
