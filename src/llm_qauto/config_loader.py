"""
配置加载器 - 支持YAML/JSON
"""

import os
import json
import yaml
from typing import Dict, Any
from pathlib import Path
from jinja2 import Template

from .models import TestSuiteConfig


def load_config(config_path: str, vars_dict: Dict[str, Any] = None) -> TestSuiteConfig:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径(.yaml或.json)
        vars_dict: 用于模板渲染的变量
    
    Returns:
        TestSuiteConfig对象
    """
    path = Path(config_path)
    
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    # 读取原始内容
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 如果有变量，进行Jinja2模板渲染
    if vars_dict:
        template = Template(content)
        content = template.render(**vars_dict)
    
    # 解析配置
    if path.suffix in ['.yaml', '.yml']:
        data = yaml.safe_load(content)
    elif path.suffix == '.json':
        data = json.loads(content)
    else:
        raise ValueError(f"不支持的配置文件格式: {path.suffix}")
    
    # 处理环境变量引用 ${VAR_NAME}
    data = _resolve_env_vars(data)
    
    return TestSuiteConfig(**data)


def load_config_from_yaml_text(content: str) -> TestSuiteConfig:
    """从 YAML 字符串加载套件配置（含 ${ENV} 展开）。"""
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        raise ValueError("配置必须是 YAML 映射对象")
    data = _resolve_env_vars(data)
    return TestSuiteConfig(**data)


def _resolve_env_vars(obj: Any) -> Any:
    """递归解析配置中的环境变量引用"""
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        # 替换 ${VAR} 格式的环境变量
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replacer(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        
        return re.sub(pattern, replacer, obj)
    else:
        return obj


def save_example_configs(output_dir: str):
    """生成示例配置文件"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 基础配置
    basic = {
        "meta": {
            "name": "基础测试示例",
            "version": "1.0.0",
            "description": "最简单的测试配置"
        },
        "target": {
            "type": "api",
            "connector": {
                "name": "http_json",
                "config": {
                    "endpoint": "https://api.example.com/v1/generate",
                    "method": "POST",
                    "headers": {
                        "Authorization": "Bearer ${API_KEY}"
                    },
                    "timeout": 30,
                    "retry": 3,
                    "concurrency": 5
                }
            },
            "input_formatter": {
                "name": "json_payload",
                "template": {
                    "messages": [
                        {"role": "user", "content": "{{input.prompt}}"}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 500
                }
            },
            "output_parser": {
                "name": "json_extractor",
                "path": "choices.0.message.content"
            }
        },
        "data_generator": {
            "strategy": "template_cartesian",
            "variables": [
                {
                    "name": "instruction",
                    "type": "enum",
                    "values": ["生成一段文案", "写一段介绍"]
                }
            ],
            "sampling": {
                "total": 10,
                "seed": 42
            }
        },
        "evaluation": {
            "dimensions": [
                {
                    "id": "basic_quality",
                    "name": "基础质量",
                    "weight": 1.0,
                    "evaluators": [
                        {
                            "type": "rule",
                            "name": "format_check",
                            "dimension_id": "basic_quality",
                            "rules": [
                                {
                                    "name": "非空检查",
                                    "condition": "len(output) > 0"
                                },
                                {
                                    "name": "长度范围",
                                    "condition": "len(output) >= 10 and len(output) <= 1000"
                                }
                            ]
                        }
                    ]
                }
            ],
            "aggregation_method": "weighted_average"
        },
        "pass_criteria": {
            "global_criteria": {
                "min_dimension_coverage": 0.8
            },
            "dimensions": [
                {
                    "id": "basic_quality",
                    "min_avg_score": 6.0,
                    "max_fail_rate": 0.2
                }
            ],
            "statistical": {
                "confidence_level": 0.95,
                "min_sample_size": 30
            }
        }
    }
    
    with open(os.path.join(output_dir, "basic_example.yaml"), 'w', encoding='utf-8') as f:
        yaml.dump(basic, f, allow_unicode=True, sort_keys=False)
    
    print(f"示例配置已保存到: {output_dir}")
