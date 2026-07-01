"""
通用AI智能体测试平台 (Universal AI Testing Platform)

支持任何AI生成能力的通用测试框架，包括：
- 文案生成
- 代码生成
- 对话系统
- SQL生成
- 多模态内容
"""

from __future__ import annotations

import logging
import os
import sys

__version__ = "1.0.0"
__author__ = "QA Team"


def _configure_llm_qauto_logging() -> None:
    """
    为包内 logger（llm_qauto.*）挂一条控制台 Handler，便于观察评委截断 / LLM 调用。
    可用环境变量覆盖级别：QAUTO_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
    """
    pkg = logging.getLogger("llm_qauto")
    if pkg.handlers:
        return

    level_name = os.environ.get("QAUTO_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    pkg.addHandler(handler)
    pkg.setLevel(level)
    pkg.propagate = False


_configure_llm_qauto_logging()
