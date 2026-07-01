"""
Markdown报告生成器
"""

from typing import Any, Dict
from ..models import TestReport, TestStatus
from . import BaseReporter
from .labels import dimension_display_label, dimension_names_from_report, format_dimension_labels


class MarkdownReporter(BaseReporter):
    """生成Markdown格式报告"""
    
    @property
    def name(self) -> str:
        return "markdown"
    
    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        """生成Markdown报告"""
        
        md = f"""# AI测试报告: {report.project_name}

## 概览

| 项目 | 值 |
|------|-----|
| 运行ID | `{report.run_id}` |
| 状态 | {'✅ PASSED' if report.status == TestStatus.PASSED else '❌ FAILED'} |
| 总样本数 | {report.total_cases} |
| 通过数 | {report.passed_cases} |
| 失败数 | {report.failed_cases} |
| 通过率 | {report.pass_rate:.1f}% |
| 开始时间 | {report.start_time.strftime('%Y-%m-%d %H:%M:%S')} |
| 结束时间 | {report.end_time.strftime('%Y-%m-%d %H:%M:%S') if report.end_time else '-'} |

## 通过标准检查

| 检查项 | 状态 | 实际值 | 期望值 | 详情 |
|--------|------|--------|--------|------|
"""
        
        for criteria in report.criteria_results:
            status = "✅" if criteria.passed else "❌"
            actual = f"{criteria.actual_value:.2f}" if isinstance(criteria.actual_value, float) else str(criteria.actual_value)
            expected = f"{criteria.expected_value:.2f}" if isinstance(criteria.expected_value, float) else str(criteria.expected_value)
            md += f"| {criteria.description} | {status} | {actual} | {expected} | {criteria.details} |\n"
        
        md += "\n## 维度统计\n\n"
        dim_names = dimension_names_from_report(report)

        for stat in report.dimension_stats:
            dim_title = stat.dimension_name or dimension_display_label(
                report, stat.dimension_id, names=dim_names
            )
            md += f"""### {dim_title}

- **通过率**: {stat.pass_rate:.1f}%
- **平均分**: {stat.avg_score:.2f} (范围: {stat.min_score:.2f} - {stat.max_score:.2f})
- **样本数**: {stat.total_cases} (通过: {stat.passed_cases}, 失败: {stat.failed_cases})
- **标准差**: {stat.std_score:.2f}

#### 类别分布

| 类别 | 数量 | 占比 | 95%置信区间 |
|------|------|------|-------------|
"""
            for cat in stat.category_distribution:
                ci_lower, ci_upper = cat.confidence_interval
                md += f"| {cat.category} | {cat.count} | {cat.percentage:.1f}% | [{ci_lower*100:.1f}%, {ci_upper*100:.1f}%] |\n"
            
            md += "\n"
        
        # 失败示例
        if report.failed_examples:
            md += "## 失败示例\n\n"
            for case in report.failed_examples[:5]:
                md += f"""### Case {case.id}

**输入:**
```
{case.input.prompt[:300]}{'...' if len(case.input.prompt) > 300 else ''}
```

**输出:**
```
{case.output.content[:300]}{'...' if len(case.output.content) > 300 else ''}
```

**失败维度:** {format_dimension_labels(report, case.failed_dimensions, names=dim_names)}

---

"""
        
        # 建议
        if report.recommendations:
            md += "## 改进建议\n\n"
            for i, rec in enumerate(report.recommendations, 1):
                md += f"{i}. {rec}\n"
            md += "\n"
        
        md += f"""---

*由 LLM-QAuto 通用AI测试平台生成*
*报告时间: {report.end_time.strftime('%Y-%m-%d %H:%M:%S') if report.end_time else ''}*
"""
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(md)
