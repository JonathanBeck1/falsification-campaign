"""Defensive sanitization for untrusted news text.

Runs at the ingestion boundary BEFORE any normalized text lands in
news_events. Anything that reaches the LLM enricher or the
ThesisEngine has already passed through here.

Defends against the prompt-injection vectors flagged in the PR #24
safety review and the brain/20 ADR:

1. Invisible / zero-width characters (U+200B/U+FEFF/U+2060) used to
   smuggle hidden tokens past visual review.
2. RTL override (U+202E) that can reverse displayed text.
3. Tag-closing attempts (`</article>`, `</event>`, `</allowed_tickers>`)
   that close the XML envelope the enricher uses to delimit data.
4. Known prompt-injection phrasings ("ignore previous instructions",
   "you are now", "disregard the above", etc.).
5. HTML/script tags that some adapters may pass through.

Each unsafe pattern is **stripped or escaped** and the event metadata
is annotated with a list of `sanitization_flags` so reviewers (and
the dashboard) can see which articles tripped which guards.

The sanitizer is intentionally aggressive: false positives (a benign
article that mentions "ignore previous" in commentary) end up
flagged-but-still-usable. False negatives are the failure mode we
care about.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

# Zero-width and BOM-style codepoints that can hide adversarial tokens.
_INVISIBLE_CHARS = re.compile(
    "["
    "​"  # zero-width space
    "‌"  # zero-width non-joiner
    "‍"  # zero-width joiner
    "⁠"  # word joiner
    "﻿"  # zero-width no-break space / BOM
    "᠎"  # mongolian vowel separator
    "]"
)

# Right-to-left and other bidirectional override controls.
_BIDI_OVERRIDES = re.compile(
    "["
    "‪"  # LEFT-TO-RIGHT EMBEDDING
    "‫"  # RIGHT-TO-LEFT EMBEDDING
    "‬"  # POP DIRECTIONAL FORMATTING
    "‭"  # LEFT-TO-RIGHT OVERRIDE
    "‮"  # RIGHT-TO-LEFT OVERRIDE
    "⁦"  # LEFT-TO-RIGHT ISOLATE
    "⁧"  # RIGHT-TO-LEFT ISOLATE
    "⁨"  # FIRST STRONG ISOLATE
    "⁩"  # POP DIRECTIONAL ISOLATE
    "]"
)

# XML envelope tags the enricher prompt uses to delimit data blocks.
# Anything trying to close one of these gets escaped.
_ENVELOPE_TAGS: tuple[str, ...] = (
    "article",
    "event",
    "event_id",
    "headline",
    "summary",
    "allowed_tickers",
    "live_data",
    "news_feed",
    "general_knowledge",
    "system",
    "instructions",
    "context",
)

_TAG_CLOSE = re.compile(
    r"</\s*(?P<tag>" + "|".join(_ENVELOPE_TAGS) + r")\s*>",
    re.IGNORECASE,
)
_TAG_OPEN = re.compile(
    r"<\s*(?P<tag>" + "|".join(_ENVELOPE_TAGS) + r")(?:\s+[^>]*)?\s*/?\s*>",
    re.IGNORECASE,
)

# Known prompt-injection phrasings. Conservative list — additions should
# be reviewed since adding too many causes false positives.
_INJECTION_PHRASES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore (?:all |the |any )?(?:previous|prior|above|earlier) instruction",
        r"disregard (?:all |the |any )?(?:previous|prior|above|earlier) instruction",
        r"forget (?:all |the |any )?(?:previous|prior|above|earlier) instruction",
        r"you are (?:now |actually )?(?:a |an )?(?:\w+\s+){0,2}(?:trader|trading agent|jailbroken|developer|admin|llm|assistant)",
        r"reveal (?:the |your )?system prompt",
        r"print (?:the |your )?system prompt",
        r"override (?:your |the )?safety",
        r"new instructions?:\s",
        r"### system\s*:",
        r"###\s*instructions\s*:",
        r"\bsudo\s+",
        r"buy \d+(?:k|m|,\d+)? shares? of",
        r"execute (?:the )?(?:following )?(?:trade|order):",
    )
)

# Scripts/iframes that some adapters might pass through verbatim.
_SCRIPT_TAGS = re.compile(
    r"<(?:script|iframe|object|embed)[^>]*>.*?</(?:script|iframe|object|embed)>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class SanitizedText:
    """Result of sanitization. `text` is safe to embed in a prompt or store;
    `flags` lists every guard that fired so reviewers can audit."""

    text: str
    flags: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return not self.flags


def sanitize_for_ingestion(raw: str | None) -> SanitizedText:
    """Single entry point. Always returns a SanitizedText, never raises.

    Strips invisible characters, neutralizes RTL overrides, escapes
    XML envelope tag attempts, redacts scripts, flags injection phrases,
    NFC-normalizes Unicode, and HTML-unescapes once. Idempotent — running
    the result through `sanitize_for_ingestion` again is a no-op.
    """
    if not raw:
        return SanitizedText(text="", flags=())

    flags: list[str] = []
    text = raw

    # NFC-normalize first so visually-identical-but-different-codepoint
    # variants collapse to a canonical form. Catches e.g. fullwidth
    # angle brackets (U+FF1C/U+FF1E) that map to ASCII < > under NFKC.
    nfkc = unicodedata.normalize("NFKC", text)
    if nfkc != text:
        flags.append("unicode_normalized")
        text = nfkc

    # HTML entity decode once — many news sources emit &lt;script&gt;
    # which we want to see as <script> so we can strip it.
    unescaped = html.unescape(text)
    if unescaped != text:
        flags.append("html_unescaped")
        text = unescaped

    if _INVISIBLE_CHARS.search(text):
        flags.append("invisible_chars_stripped")
        text = _INVISIBLE_CHARS.sub("", text)

    if _BIDI_OVERRIDES.search(text):
        flags.append("bidi_overrides_stripped")
        text = _BIDI_OVERRIDES.sub("", text)

    if _SCRIPT_TAGS.search(text):
        flags.append("script_tags_redacted")
        text = _SCRIPT_TAGS.sub("[redacted_script]", text)

    if _TAG_CLOSE.search(text):
        flags.append("envelope_tag_close_escaped")
        text = _TAG_CLOSE.sub(lambda m: f"&lt;/{m.group('tag')}&gt;", text)

    if _TAG_OPEN.search(text):
        flags.append("envelope_tag_open_escaped")
        text = _TAG_OPEN.sub(lambda m: f"&lt;{m.group('tag')}&gt;", text)

    for pat in _INJECTION_PHRASES:
        if pat.search(text):
            flags.append(f"injection_phrase:{pat.pattern[:32]}")

    # Collapse repeated whitespace introduced by the strips.
    text = re.sub(r"[ \t]+", " ", text).strip()

    return SanitizedText(text=text, flags=tuple(flags))


def sanitize_event_text(title: str | None, summary: str | None) -> tuple[str, str, tuple[str, ...]]:
    """Convenience wrapper that sanitizes both title and summary and
    returns the combined flag list. Used by `ingestion/events.py`."""
    t = sanitize_for_ingestion(title)
    s = sanitize_for_ingestion(summary)
    merged_flags = tuple({*t.flags, *s.flags})
    return t.text, s.text, merged_flags
