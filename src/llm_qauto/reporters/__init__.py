"""
报告生成器 - 各种格式输出
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from ..models import TestReport


class BaseReporter(ABC):
    """报告生成器基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        """生成报告"""
        pass


from .html_reporter import HTMLReporter
from .json_reporter import JSONReporter
from .markdown_reporter import MarkdownReporter
from .csv_reporter import CSVReporter
from .labels import (
    build_dimension_display_names,
    dimension_display_label,
    dimension_names_from_report,
    format_dimension_labels,
)

__all__ = [
    "BaseReporter",
    "HTMLReporter",
    "JSONReporter",
    "MarkdownReporter",
    "CSVReporter",
    "build_dimension_display_names",
    "dimension_display_label",
    "dimension_names_from_report",
    "format_dimension_labels",
]
