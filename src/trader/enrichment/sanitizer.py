from __future__ import annotations

import html

TAG_CONFUSION_MARKERS = ("\uff1c/article\uff1e", "\u2039/article\u203a")


def sanitize_for_prompt(text: str, *, max_chars: int = 4000) -> str:
    raw = text or ""
    lowered = raw.lower()
    if any(marker in lowered for marker in TAG_CONFUSION_MARKERS):
        raise ValueError("tag-confusion marker found in untrusted article text")

    truncated = raw[:max_chars]
    escaped = html.escape(truncated, quote=False)
    if len(raw) > max_chars:
        return f"{escaped}\n[truncated]"
    return escaped
