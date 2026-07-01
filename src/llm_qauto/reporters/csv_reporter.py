"""
CSV报告生成器 - 便于数据分析
"""

import csv
from typing import Any, Dict
from ..models import TestReport
from . import BaseReporter
from .labels import dimension_display_label, dimension_names_from_report


class CSVReporter(BaseReporter):
    """生成CSV格式报告"""
    
    @property
    def name(self) -> str:
        return "csv"
    
    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        """生成CSV报告"""
        
        # 准备数据
        rows = []
        
        # 表头
        dim_names = dimension_names_from_report(report)
        headers = [
            "run_id",
            "project_name", 
            "dimension_id",
            "dimension_name",
            "total_cases",
            "passed_cases",
            "failed_cases",
            "pass_rate",
            "avg_score",
            "min_score",
            "max_score",
            "std_score",
            "category",
            "category_count",
            "category_percentage",
            "ci_lower",
            "ci_upper"
        ]
        
        # 数据行
        for stat in report.dimension_stats:
            if stat.category_distribution:
                for cat in stat.category_distribution:
                    ci_lower, ci_upper = cat.confidence_interval
                    rows.append({
                        "run_id": report.run_id,
                        "project_name": report.project_name,
                        "dimension_id": stat.dimension_id,
                        "dimension_name": stat.dimension_name or dimension_display_label(
                            report, stat.dimension_id, names=dim_names
                        ),
                        "total_cases": stat.total_cases,
                        "passed_cases": stat.passed_cases,
                        "failed_cases": stat.failed_cases,
                        "pass_rate": stat.pass_rate,
                        "avg_score": stat.avg_score,
                        "min_score": stat.min_score,
                        "max_score": stat.max_score,
                        "std_score": stat.std_score,
                        "category": cat.category,
                        "category_count": cat.count,
                        "category_percentage": cat.percentage,
                        "ci_lower": ci_lower * 100,
                        "ci_upper": ci_upper * 100
                    })
            else:
                rows.append({
                    "run_id": report.run_id,
                    "project_name": report.project_name,
                    "dimension_id": stat.dimension_id,
                    "dimension_name": stat.dimension_name or dimension_display_label(
                        report, stat.dimension_id, names=dim_names
                    ),
                    "total_cases": stat.total_cases,
                    "passed_cases": stat.passed_cases,
                    "failed_cases": stat.failed_cases,
                    "pass_rate": stat.pass_rate,
                    "avg_score": stat.avg_score,
                    "min_score": stat.min_score,
                    "max_score": stat.max_score,
                    "std_score": stat.std_score,
                    "category": "",
                    "category_count": 0,
                    "category_percentage": 0,
                    "ci_lower": 0,
                    "ci_upper": 0
                })
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
