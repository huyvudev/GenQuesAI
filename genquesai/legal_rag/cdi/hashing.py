"""CDI · content hashing — SHA-256 trên toàn văn đã chuẩn hoá (CDI-1a; gỡ G2/G8).

Dùng để: (1) phát hiện RE-UPLOAD trùng nội dung dù số hiệu lệch (dedup);
(2) phát hiện nguồn ĐỔI nội dung VB cũ (resync — graph lỗi thời thầm lặng).
Chuẩn hoá whitespace trước khi hash để nhiễu OCR/format không làm đổi hash.
"""
from __future__ import annotations
import hashlib
import re

from selectolax.parser import HTMLParser

_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Gập mọi khoảng trắng (gồm xuống dòng/tab) về 1 space + strip — hash ổn định."""
    return _WS.sub(" ", (text or "").strip())


def content_hash(text: str) -> str:
    """SHA-256 hex của text đã chuẩn hoá. Text rỗng -> '' (không hash chuỗi rỗng)."""
    norm = normalize_text(text)
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def hash_html(html: str) -> str:
    """Hash phần body text của toanvan.html (bỏ thẻ) — dùng cho re-sync nguồn."""
    if not html:
        return ""
    body = HTMLParser(html).body
    return content_hash(body.text(separator="\n", strip=True) if body else "")
