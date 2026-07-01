"""
JSON报告生成器 - 机器可读格式
"""

import json
from typing import Any, Dict
from ..models import TestReport
from . import BaseReporter


class JSONReporter(BaseReporter):
    """生成JSON格式报告"""
    
    @property
    def name(self) -> str:
        return "json"
    
    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        """生成JSON报告"""
        
        # 转换为可序列化的字典（含 cases[] 每条用例摘要、suite_meta、aggregation_method）
        data = report.model_dump()
        
        # 添加一些便于机器解析的字段
        data["ci_status"] = "pass" if report.status.value == "passed" else "fail"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
