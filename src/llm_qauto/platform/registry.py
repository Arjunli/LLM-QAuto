"""Load platform module manifest."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

_MANIFEST = Path(__file__).parent / "modules.yaml"


@lru_cache(maxsize=1)
def _load_raw() -> Dict[str, Any]:
    with open(_MANIFEST, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_platform_meta() -> Dict[str, Any]:
    return dict(_load_raw().get("platform") or {})


def get_modules(enabled_only: bool = True) -> List[Dict[str, Any]]:
    mods = list(_load_raw().get("modules") or [])
    if enabled_only:
        mods = [m for m in mods if m.get("enabled", True)]
    return mods


def get_module(module_id: str) -> Optional[Dict[str, Any]]:
    for m in get_modules(enabled_only=False):
        if m.get("id") == module_id:
            return m
    return None
