"""Tiny LiteLLM wrapper. Adds: prompt-hash logging, cost tracking, JSON-mode default.

Why LiteLLM: one client interface for Anthropic / OpenAI / local Ollama / others.
We log every call to the `llm_calls` table so we can see exactly what each brain
spent and on what.

Anthropic prompt caching: pass `system=[SystemContentBlock(...), ...]` with at
least one block whose `cache_ttl` is `"5m"` or `"1h"`. Plain string `system`
keeps the original behavior (no caching).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Literal

import structlog

log = structlog.get_logger()


CacheTTL = Literal["none", "5m", "1h"]


@dataclass(frozen=True, slots=True)
class SystemContentBlock:
    """One piece of a system prompt that can be independently cached.

    Pass a list of these to `LLMClient.complete(system=...)` to enable Anthropic
    prompt caching. Mark a block with `cache_ttl="5m"` (default Anthropic
    ephemeral) or `"1h"` (longer TTL) to cache it; `"none"` skips caching for
    that block.

    Anthropic limits cached blocks to 4 cache breakpoints per request. The
    client enforces this and raises `ValueError` if exceeded.
    """

    text: str
    cache_ttl: CacheTTL = "none"


@dataclass(frozen=True)
class LLMResponse:
    content: str
    parsed: dict[str, Any] | None
    model: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int            # tokens read from cache (cheap)
    cache_creation_tokens: int    # tokens written to cache on this call (1.25x base price for Anthropic)
    cost_usd: float | None
    latency_ms: int
    prompt_hash: str


# Module-level warn-once registries. Keep log volume sane in hot loops.
_WARNED_NON_ANTHROPIC: set[str] = set()
_WARNED_SHORT_BLOCK: set[str] = set()


def _is_anthropic(model: str) -> bool:
    """Reliable provider check via LiteLLM's helper; falls back to prefix match.

    Recognizes direct Anthropic, Bedrock Claude, Vertex Claude. LiteLLM
    returns provider as `"anthropic"` for direct routes, `"bedrock"` for
    Bedrock, and `"vertex_ai"` for Vertex — so we accept the latter two only
    when the model name itself mentions Claude/Anthropic (a Bedrock or Vertex
    model that isn't Claude must not receive `cache_control`).

    Falls back to a string heuristic if LiteLLM raises (e.g. for a model name
    it doesn't recognize yet).
    """
    try:
        import litellm  # lazy

        _, provider, _, _ = litellm.get_llm_provider(model)
        if provider == "anthropic":
            return True
        if provider in ("bedrock", "vertex_ai"):
            m = model.lower()
            return "claude" in m or "anthropic" in m
        return False
    except Exception:
        m = model.lower()
        return (
            m.startswith("claude")
            or m.startswith("anthropic/")
            or "anthropic.claude" in m
            or "vertex_ai/claude" in m
        )


def _short_block_char_floor(model: str) -> int:
    """Rough chars-below-which Anthropic silently skips caching.

    Anthropic's minimum cacheable length is ~1024 tokens for Sonnet/Opus and
    ~2048 for Haiku. At ~4 chars/token that's roughly 4000 chars and 8000
    chars respectively. This is a warning threshold, not a hard limit — the
    real cutoff is upstream and may change.
    """
    return 8000 if "haiku" in model.lower() else 4000


def _ttl_to_cache_control(ttl: CacheTTL) -> dict[str, str] | None:
    """Translate the public TTL enum into Anthropic's `cache_control` payload."""
    if ttl == "none":
        return None
    if ttl == "5m":
        return {"type": "ephemeral"}
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    raise ValueError(f"unknown cache_ttl: {ttl!r}")


def _validate_system_blocks(blocks: list[SystemContentBlock]) -> None:
    """Reject misuse early — see brain/18 for why each rule exists."""
    if not blocks:
        raise ValueError("system blocks list is empty; pass a non-empty list or a str")
    for i, b in enumerate(blocks):
        if not b.text:
            raise ValueError(f"SystemContentBlock[{i}] has empty text")
    cacheable_count = sum(1 for b in blocks if b.cache_ttl != "none")
    if cacheable_count == 0:
        raise ValueError(
            "no blocks are cacheable (all cache_ttl='none'); pass a plain str for that case"
        )
    if cacheable_count > 4:
        raise ValueError(
            f"too many cache breakpoints: {cacheable_count} > 4 (Anthropic limit)"
        )


def _normalize_messages_for_hash(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Strip wire-shape details so the same logical prompt hashes the same.

    Two semantically-identical prompts must produce the same `prompt_hash`
    regardless of whether `system` was a plain str or a list of blocks. We
    normalize by flattening each message's content into a single string and
    discarding `cache_control` keys.
    """
    norm: list[dict[str, str]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
            text = "".join(parts)
        else:
            text = str(content)
        norm.append({"role": str(msg.get("role", "")), "content": text})
    return norm


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Read a value from either an attribute-style object or a dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _build_system_message(
    system: str | list[SystemContentBlock],
    *,
    model: str,
) -> dict[str, Any]:
    """Produce the wire-format system message.

    - `str` → plain content (no caching). No validation runs on this path.
    - `list[SystemContentBlock]` → validated for all providers (empty list,
      empty text, all-`"none"`, >4 cacheable all raise `ValueError`). The
      list form is opt-in for prompt caching; if a caller wants to send a
      plain string, they should pass a `str`.
    - When the list form is used AND the model is Anthropic, we emit
      content-blocks with `cache_control` markers.
    - When the list form is used AND the model is NOT Anthropic, we
      concatenate to a flat string (no `cache_control` would be valid for
      that provider) and log a one-time warning per model.
    """
    if isinstance(system, str):
        return {"role": "system", "content": system}

    _validate_system_blocks(system)

    if not _is_anthropic(model):
        if model not in _WARNED_NON_ANTHROPIC:
            _WARNED_NON_ANTHROPIC.add(model)
            log.warning(
                "llm_cache_control_unsupported_provider",
                model=model,
                note="falling back to concatenated string; cache_ttl ignored",
            )
        return {"role": "system", "content": "".join(b.text for b in system)}

    floor = _short_block_char_floor(model)
    blocks: list[dict[str, Any]] = []
    for block in system:
        wire: dict[str, Any] = {"type": "text", "text": block.text}
        cache_control = _ttl_to_cache_control(block.cache_ttl)
        if cache_control is not None:
            wire["cache_control"] = cache_control
            if len(block.text) < floor and model not in _WARNED_SHORT_BLOCK:
                # Warn once per model. Different short blocks under the same
                # model are the same problem — no value in re-warning.
                _WARNED_SHORT_BLOCK.add(model)
                log.warning(
                    "llm_cache_block_likely_too_short",
                    model=model,
                    chars=len(block.text),
                    char_floor=floor,
                    note="Anthropic silently skips caching below this floor",
                )
        blocks.append(wire)
    return {"role": "system", "content": blocks}


class LLMClient:
    def __init__(self, model: str | None = None) -> None:
        from trader.config import get_settings

        s = get_settings()
        self.model = model or s.trader_llm_model

    def _prompt_hash(self, messages: list[dict[str, Any]]) -> str:
        # Hash by semantics (concatenated text per message) so the same logical
        # prompt produces the same hash regardless of cache_control wire shape.
        # Important for the `llm_calls.prompt_hash` audit column to stay
        # meaningful as callers migrate to cached prompts.
        normalized = _normalize_messages_for_hash(messages)
        h = hashlib.sha256()
        h.update(json.dumps(normalized, sort_keys=True, default=str).encode())
        return h.hexdigest()[:16]

    def complete(
        self,
        *,
        system: str | list[SystemContentBlock],
        user: str,
        response_format_json: bool = True,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Single-shot completion. Returns parsed JSON if response_format_json=True.

        Pass `system` as either a plain string (no caching, original behavior)
        or a list of `SystemContentBlock` to enable Anthropic prompt caching on
        the blocks marked `cache_ttl` != `"none"`.

        Caching is only emitted for Anthropic models (direct, Bedrock, Vertex);
        other providers get a concatenated string and a one-time warning.
        """
        import litellm  # lazy

        system_message = _build_system_message(system, model=self.model)
        messages: list[dict[str, Any]] = [
            system_message,
            {"role": "user", "content": user},
        ]
        prompt_hash = self._prompt_hash(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format_json:
            # Anthropic via LiteLLM silently ignores response_format; we recover
            # by parsing whatever JSON the model emits and falling back to
            # parsed=None on failure. OpenAI honors it.
            kwargs["response_format"] = {"type": "json_object"}

        t0 = time.perf_counter()
        resp = litellm.completion(**kwargs)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        content = resp.choices[0].message.content or ""
        parsed: dict[str, Any] | None = None
        if response_format_json:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None

        usage = getattr(resp, "usage", None)
        input_tokens = _field(usage, "prompt_tokens") if usage else None
        output_tokens = _field(usage, "completion_tokens") if usage else None

        # LiteLLM exposes cost via _hidden_params or response_cost; both can be None.
        hidden_params = getattr(resp, "_hidden_params", None) or {}
        cost = _field(hidden_params, "response_cost")
        if cost is None:
            cost = getattr(resp, "response_cost", None)

        cached_tokens = 0
        cache_creation_tokens = 0
        if usage is not None:
            details = _field(usage, "prompt_tokens_details", {}) or {}
            cached_tokens = int(_field(details, "cached_tokens", 0) or 0)
            # Anthropic-specific: tokens *written* to cache on this call. Billed at
            # ~1.25x base input price. LiteLLM passes this through on the usage
            # object for Anthropic responses; absent on other providers.
            cache_creation_tokens = int(_field(usage, "cache_creation_input_tokens", 0) or 0)

        return LLMResponse(
            content=content,
            parsed=parsed,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=float(cost) if cost is not None else None,
            latency_ms=latency_ms,
            prompt_hash=prompt_hash,
        )
