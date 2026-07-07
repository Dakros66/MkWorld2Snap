"""Static security headers for the MkWorld2Snap local API."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path


_FRONTEND_DIST = Path(
    os.environ.get("MKWORLD2SNAP_FRONTEND_DIST", "/app/frontend/dist")
)
_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)
_INLINE_SCRIPT_RE = re.compile(
    r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE
)


def _script_sha256(script: str) -> str:
    digest = hashlib.sha256(script.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _json_ld_hash() -> str | None:
    index = _FRONTEND_DIST / "index.html"
    try:
        html = index.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _JSON_LD_RE.search(html)
    return _script_sha256(match.group(1)) if match else None


def _inline_script_hashes(filename: str) -> list[str]:
    page = _FRONTEND_DIST / filename
    try:
        html = page.read_text(encoding="utf-8")
    except OSError:
        return []
    hashes: list[str] = []
    for match in _INLINE_SCRIPT_RE.finditer(html):
        body = match.group(1)
        if body.strip():
            hashes.append(_script_sha256(body))
    return hashes


def _build_csp() -> str:
    script_src = ["'self'"]
    if json_ld := _json_ld_hash():
        script_src.append(json_ld)
    script_src.extend(_inline_script_hashes("privacy.html"))
    return "; ".join(
        [
            "default-src 'self'",
            "script-src " + " ".join(script_src),
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "font-src 'self'",
            "frame-src 'none'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
        ]
    )


SECURITY_HEADERS: dict[str, str] = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": _build_csp(),
}


def render_privacy_html(html: str) -> str:
    return html
