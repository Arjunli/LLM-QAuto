"""Web chat 截图附件解析。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..media import parse_chat_image_attachments


def parse_request_attachments(items: Optional[List[Dict[str, Any]]]) -> List[str]:
    return parse_chat_image_attachments(items)
