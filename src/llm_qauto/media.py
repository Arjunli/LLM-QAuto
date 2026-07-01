"""
多模态产物处理：从 API 响应提取图片 URL/base64，下载到 artifacts，供视觉评委使用。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from .models import MediaAsset

logger = logging.getLogger(__name__)

_DATA_URL_RE = re.compile(
    r"^data:(image/[\w.+-]+);base64,(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def traverse_dotted(start: Any, path: Optional[str]) -> Any:
    if not path or not str(path).strip():
        return start
    cur = start
    for raw in str(path).split("."):
        key = raw.strip()
        if not key:
            continue
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)]
        else:
            return None
    return cur


def _flatten_image_candidates(node: Any) -> List[str]:
    """将 path 节点规范为 URL 或 data-url 字符串列表。"""
    out: List[str] = []
    if node is None:
        return out
    if isinstance(node, str):
        s = node.strip()
        if s.startswith(("http://", "https://", "data:image")):
            out.append(s)
        return out
    if isinstance(node, list):
        for item in node:
            out.extend(_flatten_image_candidates(item))
        return out
    if isinstance(node, dict):
        for key in (
            "url",
            "image_url",
            "imageUrl",
            "b64_json",
            "b64",
            "base64",
            "image",
            "src",
        ):
            if key in node:
                out.extend(_flatten_image_candidates(node[key]))
        return out
    return out


def _guess_ext(mime: Optional[str], url: Optional[str] = None) -> str:
    if mime:
        ext = mimetypes.guess_extension(mime.split(";")[0].strip())
        if ext:
            return ext
    if url:
        path_part = url.split("?")[0]
        if "." in path_part:
            suf = Path(path_part).suffix.lower()
            if suf in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                return suf
    return ".png"


async def _download_url(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    timeout: float = 60.0,
) -> Tuple[bool, Optional[str]]:
    try:
        resp = await client.get(url, timeout=timeout, follow_redirects=True)
        if resp.status_code >= 300:
            return False, f"HTTP {resp.status_code}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        mime = resp.headers.get("content-type", "").split(";")[0].strip() or None
        return True, mime
    except Exception as e:
        return False, str(e)


def _write_b64(b64_data: str, dest: Path) -> Tuple[bool, Optional[str]]:
    try:
        raw = base64.b64decode(b64_data, validate=False)
        if not raw:
            return False, "empty decode"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        return True, "image/png"
    except Exception as e:
        return False, str(e)


async def extract_and_persist_media(
    raw_response: Optional[Dict[str, Any]],
    parser_config: Dict[str, Any],
    case_id: str,
    artifacts_dir: Optional[str],
) -> List[MediaAsset]:
    """
    按 output_parser.media 配置从 raw_response 提取图片并落盘。
    parser_config 示例:
      media:
        urls_path: data.images
        b64_path: data.b64_json
        download: true
        max_images: 4
    """
    media_cfg = parser_config.get("media") or {}
    if not media_cfg:
        return []

    root = raw_response or {}
    inner = root.get("data", root) if isinstance(root, dict) else root

    candidates: List[str] = []
    for path_key in ("urls_path", "url_path", "b64_path", "images_path"):
        p = media_cfg.get(path_key)
        if not p:
            continue
        node = traverse_dotted(inner, str(p).strip())
        candidates.extend(_flatten_image_candidates(node))

    max_images = int(media_cfg.get("max_images", 8) or 8)
    candidates = candidates[:max_images]

    if not candidates:
        return []

    download = media_cfg.get("download", True)
    base_dir = Path(artifacts_dir) if artifacts_dir else None
    img_dir = base_dir / "images" if base_dir else None

    assets: List[MediaAsset] = []
    timeout = float(media_cfg.get("timeout", 90))

    async with httpx.AsyncClient() as client:
        for idx, cand in enumerate(candidates):
            asset_id = f"{case_id}_{idx}"
            local_path: Optional[str] = None
            remote_url: Optional[str] = None
            mime: Optional[str] = None
            width: Optional[int] = None
            height: Optional[int] = None
            err: Optional[str] = None

            m = _DATA_URL_RE.match(cand)
            if m:
                mime = m.group(1)
                b64_body = m.group(2)
                if download and img_dir:
                    ext = _guess_ext(mime)
                    dest = img_dir / f"{asset_id}{ext}"
                    ok, mime2 = _write_b64(b64_body, dest)
                    if ok:
                        local_path = str(dest)
                        mime = mime2 or mime
                    else:
                        err = mime2
                else:
                    remote_url = cand[:120] + "…" if len(cand) > 120 else cand
            elif cand.startswith(("http://", "https://")):
                remote_url = cand
                if download and img_dir:
                    ext = _guess_ext(None, cand)
                    dest = img_dir / f"{asset_id}{ext}"
                    ok, mime_dl = await _download_url(client, cand, dest, timeout=timeout)
                    if ok:
                        local_path = str(dest)
                        mime = mime_dl
                    else:
                        err = mime_dl
            else:
                # 裸 base64
                if download and img_dir:
                    dest = img_dir / f"{asset_id}.png"
                    ok, mime2 = _write_b64(cand, dest)
                    if ok:
                        local_path = str(dest)
                        mime = mime2
                    else:
                        err = mime2

            size_bytes = None
            if local_path and Path(local_path).is_file():
                size_bytes = Path(local_path).stat().st_size

            assets.append(
                MediaAsset(
                    id=asset_id,
                    source="response",
                    remote_url=remote_url,
                    local_path=local_path,
                    mime_type=mime,
                    width=width,
                    height=height,
                    size_bytes=size_bytes,
                    error=err,
                )
            )

    return assets


def resolve_content_mode(
    parser_config: Dict[str, Any],
    content: str,
    media: List[MediaAsset],
) -> str:
    """返回 text | image | mixed"""
    explicit = (parser_config.get("content_mode") or "auto").strip().lower()
    has_text = bool((content or "").strip())
    has_media = any(m.local_path or m.remote_url for m in media)
    if explicit in ("text", "image", "mixed"):
        if explicit == "text":
            return "text"
        if explicit == "image":
            return "image" if has_media else "text"
        return "mixed" if (has_text and has_media) else ("image" if has_media else "text")
    if has_text and has_media:
        return "mixed"
    if has_media:
        return "image"
    return "text"


def media_paths_for_judge(media: List[MediaAsset]) -> List[str]:
    """优先本地路径，供 vision 评委读取。"""
    paths: List[str] = []
    for m in media:
        if m.local_path and Path(m.local_path).is_file():
            paths.append(m.local_path)
    return paths


def encode_image_for_vision_api(path: str) -> Optional[Dict[str, Any]]:
    """将本地图片编码为 OpenAI 兼容的 image_url content part。"""
    p = Path(path)
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if not raw:
        return None
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{b64}"},
    }


def encode_image_for_gemini_api(path: str) -> Optional[Dict[str, Any]]:
    """将本地图片编码为 Gemini generateContent 的 inlineData part。"""
    p = Path(path)
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if not raw:
        return None
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return {
        "inlineData": {
            "mimeType": mime,
            "data": b64,
        }
    }


def normalize_image_data_url(raw: str) -> Optional[str]:
    """规范 chat 附件为 data:image/...;base64,..."""
    s = (raw or "").strip()
    if not s:
        return None
    if _DATA_URL_RE.match(s):
        return s
    compact = re.sub(r"\s+", "", s)
    if len(compact) > 64 and re.fullmatch(r"[A-Za-z0-9+/=]+", compact):
        return f"data:image/png;base64,{compact}"
    return None


def encode_data_url_for_vision_api(data_url: str) -> Optional[Dict[str, Any]]:
    norm = normalize_image_data_url(data_url)
    if not norm:
        return None
    return {"type": "image_url", "image_url": {"url": norm}}


def encode_data_url_for_gemini_api(data_url: str) -> Optional[Dict[str, Any]]:
    norm = normalize_image_data_url(data_url)
    if not norm:
        return None
    m = _DATA_URL_RE.match(norm)
    if not m:
        return None
    return {"inlineData": {"mimeType": m.group(1), "data": m.group(2)}}


def parse_chat_image_attachments(
    items: Optional[List[Dict[str, Any]]],
    max_count: int = 4,
    max_decoded_bytes: int = 4_000_000,
) -> List[str]:
    """从 Web chat attachments 解析 data URL 列表。"""
    out: List[str] = []
    for item in items or []:
        if str(item.get("type") or "image").lower() != "image":
            continue
        norm = normalize_image_data_url(str(item.get("data") or ""))
        if not norm:
            continue
        m = _DATA_URL_RE.match(norm)
        if m:
            try:
                raw = base64.b64decode(m.group(2), validate=False)
            except Exception:
                continue
            if len(raw) > max_decoded_bytes:
                logger.warning("skip oversized chat image attachment")
                continue
        out.append(norm)
        if len(out) >= max_count:
            break
    return out


def relative_media_path(local_path: str, artifacts_dir: str) -> str:
    """报告 HTML 相对 artifacts 目录的路径。"""
    try:
        return str(Path(local_path).relative_to(Path(artifacts_dir)))
    except ValueError:
        return local_path
