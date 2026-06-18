"""Tests for `LLMClient` + the Anthropic prompt-caching extension.

Network is mocked at the `litellm.completion` boundary — no real API calls.
`_is_anthropic` is patched per-test when provider behavior matters; otherwise
the helper uses LiteLLM's real provider table.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from trader.llm import client as client_module
from trader.llm.client import LLMClient, SystemContentBlock


@pytest.fixture(autouse=True)
def _reset_warn_once_registries(monkeypatch):
    """Module-level warn-once sets would otherwise leak state between tests."""
    monkeypatch.setattr(client_module, "_WARNED_NON_ANTHROPIC", set())
    monkeypatch.setattr(client_module, "_WARNED_SHORT_BLOCK", set())


# ---------- helpers ----------


def _fake_completion(
    *,
    content: str = '{"ok": true}',
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost: float | None = 0.001,
):
    """Build a fake litellm response object that matches what LLMClient reads."""
    prompt_tokens_details = SimpleNamespace(cached_tokens=cached_tokens)
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=prompt_tokens_details,
        cache_creation_input_tokens=cache_creation_tokens,
    )
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    resp = SimpleNamespace(
        choices=[choice],
        usage=usage,
        _hidden_params={"response_cost": cost} if cost is not None else {},
    )
    return resp


class _CompletionSpy:
    """Wraps `_fake_completion`, captures the kwargs the client passed."""

    def __init__(self, **fake_kwargs: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fake_kwargs = fake_kwargs

    def __call__(self, **kwargs: Any):
        self.calls.append(kwargs)
        return _fake_completion(**self._fake_kwargs)


@pytest.fixture
def patched_completion(monkeypatch):
    """Default Anthropic-route + JSON-content spy. Tests override via `set_response`."""
    spy = _CompletionSpy(content='{"ok": true}')
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    # Default: assume Anthropic. Tests that need non-Anthropic patch _is_anthropic directly.
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)
    return spy


# ---------- backward-compat: str system ----------


def test_str_system_preserves_simple_message_shape(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    resp = client.complete(system="You are a classifier.", user="Hello")

    assert resp.parsed == {"ok": True}
    call = patched_completion.calls[0]
    messages = call["messages"]
    assert messages == [
        {"role": "system", "content": "You are a classifier."},
        {"role": "user", "content": "Hello"},
    ]
    # No cache_control anywhere on the str path.
    assert "cache_control" not in json.dumps(messages)


def test_str_system_works_on_non_anthropic(monkeypatch):
    spy = _CompletionSpy()
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: False)

    client = LLMClient(model="gpt-4o")
    client.complete(system="hi", user="hello")
    # Unchanged shape — str path doesn't even consult provider detection.
    assert spy.calls[0]["messages"][0] == {"role": "system", "content": "hi"}


# ---------- list[SystemContentBlock] on Anthropic ----------


def test_list_blocks_emits_cache_control_on_cacheable_only(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    long_text = "x" * 5000  # over the short-block warning threshold
    blocks = [
        SystemContentBlock(text=long_text, cache_ttl="5m"),
        SystemContentBlock(text=long_text + "Y", cache_ttl="none"),
    ]
    client.complete(system=blocks, user="u")

    sys_content = patched_completion.calls[0]["messages"][0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in sys_content[1]
    assert sys_content[0]["text"] == long_text
    assert sys_content[1]["text"] == long_text + "Y"


def test_list_blocks_1h_ttl_emits_ttl_field(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    blocks = [SystemContentBlock(text="x" * 5000, cache_ttl="1h")]
    client.complete(system=blocks, user="u")
    sys_content = patched_completion.calls[0]["messages"][0]["content"]
    assert sys_content[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_too_many_breakpoints_raises():
    client = LLMClient(model="claude-haiku-4-5-20251001")
    blocks = [SystemContentBlock(text=f"block-{i}" * 1000, cache_ttl="5m") for i in range(5)]
    with pytest.raises(ValueError, match="too many cache breakpoints"):
        client.complete(system=blocks, user="u")


def test_all_blocks_none_raises():
    client = LLMClient(model="claude-haiku-4-5-20251001")
    blocks = [
        SystemContentBlock(text="aaa", cache_ttl="none"),
        SystemContentBlock(text="bbb", cache_ttl="none"),
    ]
    with pytest.raises(ValueError, match="no blocks are cacheable"):
        client.complete(system=blocks, user="u")


def test_empty_list_raises():
    client = LLMClient(model="claude-haiku-4-5-20251001")
    with pytest.raises(ValueError, match="empty"):
        client.complete(system=[], user="u")


def test_empty_text_block_raises():
    client = LLMClient(model="claude-haiku-4-5-20251001")
    blocks = [
        SystemContentBlock(text="", cache_ttl="5m"),
    ]
    with pytest.raises(ValueError, match="empty text"):
        client.complete(system=blocks, user="u")


def test_short_block_warning_dedups_by_model(patched_completion):
    """Different short blocks under the same model should warn ONCE, not
    once-per-length. Hot loops with varied prompts must not spam logs."""
    client = LLMClient(model="claude-haiku-4-5-20251001")
    # Three different short-block lengths, all under Haiku's ~8000-char floor.
    client.complete(system=[SystemContentBlock(text="a" * 100, cache_ttl="5m")], user="u")
    client.complete(system=[SystemContentBlock(text="b" * 200, cache_ttl="5m")], user="u")
    client.complete(system=[SystemContentBlock(text="c" * 500, cache_ttl="5m")], user="u")
    # Only one warning entry — keyed by model, not by length.
    assert {"claude-haiku-4-5-20251001"} == client_module._WARNED_SHORT_BLOCK


def test_short_block_threshold_is_model_aware(patched_completion):
    """Haiku needs ~8000 chars to actually cache; Sonnet/Opus only ~4000.

    A 5000-char block on Haiku should warn (too short); the same block on
    Sonnet should NOT warn (above the Sonnet floor)."""
    # Haiku: 5000 chars triggers the warning.
    haiku = LLMClient(model="claude-haiku-4-5-20251001")
    haiku.complete(system=[SystemContentBlock(text="x" * 5000, cache_ttl="5m")], user="u")
    assert "claude-haiku-4-5-20251001" in client_module._WARNED_SHORT_BLOCK

    # Sonnet: 5000 chars does NOT trigger the warning (above the ~4000 floor).
    sonnet = LLMClient(model="claude-sonnet-4-6-20250101")
    sonnet.complete(system=[SystemContentBlock(text="x" * 5000, cache_ttl="5m")], user="u")
    assert "claude-sonnet-4-6-20250101" not in client_module._WARNED_SHORT_BLOCK


# ---------- non-Anthropic with list[SystemContentBlock] ----------


def test_non_anthropic_with_list_concatenates_and_warns_once(monkeypatch):
    spy = _CompletionSpy()
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: False)

    client = LLMClient(model="gpt-4o")
    blocks = [
        SystemContentBlock(text="part-A-" + "x" * 5000, cache_ttl="5m"),
        SystemContentBlock(text="part-B", cache_ttl="none"),
    ]
    client.complete(system=blocks, user="u")
    client.complete(system=blocks, user="u")  # second call — registry should not grow further

    sys_msg = spy.calls[0]["messages"][0]
    # Content collapsed to a flat string for non-Anthropic providers.
    assert isinstance(sys_msg["content"], str)
    assert sys_msg["content"] == "part-A-" + "x" * 5000 + "part-B"
    assert "cache_control" not in json.dumps(spy.calls[0])
    # Warn-once: only one entry in registry despite two calls with the same model.
    assert {"gpt-4o"} == client_module._WARNED_NON_ANTHROPIC


# ---------- prompt-hash stability ----------


def test_prompt_hash_stable_across_str_and_list_with_same_logical_content(patched_completion):
    """Critical: migrating a caller from str → list[SystemContentBlock] must NOT
    silently change `prompt_hash`. The hash is content-addressed by semantics."""
    client = LLMClient(model="claude-haiku-4-5-20251001")
    text = "x" * 5000  # long enough to avoid the short-block warning

    r_str = client.complete(system=text, user="hello")
    r_list = client.complete(
        system=[SystemContentBlock(text=text, cache_ttl="5m")],
        user="hello",
    )
    assert r_str.prompt_hash == r_list.prompt_hash


def test_prompt_hash_differs_when_text_differs(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    r1 = client.complete(system="alpha", user="u")
    r2 = client.complete(system="beta", user="u")
    assert r1.prompt_hash != r2.prompt_hash


def test_prompt_hash_concatenates_block_text_in_order(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    longA = "A" * 5000
    longB = "B" * 5000
    r_split = client.complete(
        system=[
            SystemContentBlock(text=longA, cache_ttl="5m"),
            SystemContentBlock(text=longB, cache_ttl="none"),
        ],
        user="u",
    )
    r_joined = client.complete(system=longA + longB, user="u")
    assert r_split.prompt_hash == r_joined.prompt_hash


# ---------- usage / cost ----------


def test_cached_and_creation_tokens_populated(monkeypatch):
    """Verifies wiring only — the cost number is whatever LiteLLM hands back
    via `_hidden_params.response_cost`. LiteLLM's actual cost math on cached
    responses is opaque from our side; we just pass it through. To verify
    real cost-on-cache math, run a marked real-LLM smoke test (out of scope
    for this unit suite)."""
    spy = _CompletionSpy(cached_tokens=420, cache_creation_tokens=2048, cost=0.005)
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)

    client = LLMClient(model="claude-haiku-4-5-20251001")
    resp = client.complete(system="x", user="y")
    assert resp.cached_tokens == 420
    assert resp.cache_creation_tokens == 2048
    assert resp.cost_usd == 0.005


def test_missing_usage_fields_default_to_zero(monkeypatch):
    # Build a response with no prompt_tokens_details and no cache_creation_input_tokens.
    msg = SimpleNamespace(content="{}")
    choice = SimpleNamespace(message=msg)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    resp = SimpleNamespace(choices=[choice], usage=usage, _hidden_params={})

    import litellm

    monkeypatch.setattr(litellm, "completion", lambda **_kw: resp)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)

    client = LLMClient(model="claude-haiku-4-5-20251001")
    out = client.complete(system="x", user="y")
    assert out.cached_tokens == 0
    assert out.cache_creation_tokens == 0
    assert out.cost_usd is None


def test_dict_usage_details_and_response_cost_are_read(monkeypatch):
    msg = SimpleNamespace(content="{}")
    choice = SimpleNamespace(message=msg)
    usage = {
        "prompt_tokens": 123,
        "completion_tokens": 45,
        "prompt_tokens_details": {"cached_tokens": 67},
        "cache_creation_input_tokens": 89,
    }
    resp = SimpleNamespace(choices=[choice], usage=usage, response_cost=0.0123)

    import litellm

    monkeypatch.setattr(litellm, "completion", lambda **_kw: resp)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)

    client = LLMClient(model="claude-haiku-4-5-20251001")
    out = client.complete(system="x", user="y")

    assert out.input_tokens == 123
    assert out.output_tokens == 45
    assert out.cached_tokens == 67
    assert out.cache_creation_tokens == 89
    assert out.cost_usd == 0.0123


def test_response_format_json_false_skips_parsing(monkeypatch):
    spy = _CompletionSpy(content="not json at all")
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)

    client = LLMClient(model="claude-haiku-4-5-20251001")
    out = client.complete(system="x", user="y", response_format_json=False)
    assert out.parsed is None
    assert out.content == "not json at all"
    assert "response_format" not in spy.calls[0]


def test_invalid_json_yields_parsed_none(monkeypatch):
    spy = _CompletionSpy(content="this is not json")
    import litellm

    monkeypatch.setattr(litellm, "completion", spy)
    monkeypatch.setattr(client_module, "_is_anthropic", lambda model: True)

    client = LLMClient(model="claude-haiku-4-5-20251001")
    out = client.complete(system="x", user="y")
    assert out.parsed is None
    assert out.content == "this is not json"


def test_max_tokens_and_temperature_pass_through(patched_completion):
    client = LLMClient(model="claude-haiku-4-5-20251001")
    client.complete(system="x", user="y", max_tokens=512, temperature=0.05)
    call = patched_completion.calls[0]
    assert call["max_tokens"] == 512
    assert call["temperature"] == 0.05


# ---------- _is_anthropic ----------


def test_is_anthropic_via_litellm_helper(monkeypatch):
    import litellm

    monkeypatch.setattr(
        litellm, "get_llm_provider", lambda model: ("claude-3", "anthropic", None, None)
    )
    assert client_module._is_anthropic("claude-haiku-4-5") is True


def test_is_anthropic_returns_false_for_openai(monkeypatch):
    import litellm

    monkeypatch.setattr(
        litellm, "get_llm_provider", lambda model: ("gpt-4o", "openai", None, None)
    )
    assert client_module._is_anthropic("gpt-4o") is False


def test_is_anthropic_recognizes_vertex_and_bedrock_claude_routes(monkeypatch):
    """LiteLLM returns provider='vertex_ai' for Vertex and 'bedrock' for
    Bedrock — neither equals 'anthropic'. We must still accept them when the
    model name itself identifies Claude, otherwise the cache_control path
    silently misses these routes."""
    import litellm

    monkeypatch.setattr(
        litellm,
        "get_llm_provider",
        lambda model: (model, "vertex_ai", None, None),
    )
    assert client_module._is_anthropic("vertex_ai/claude-3-5-sonnet") is True

    monkeypatch.setattr(
        litellm,
        "get_llm_provider",
        lambda model: (model, "bedrock", None, None),
    )
    assert client_module._is_anthropic("bedrock/anthropic.claude-3-haiku") is True


def test_is_anthropic_rejects_vertex_non_claude(monkeypatch):
    """A Vertex Gemini model returns provider='vertex_ai' but is NOT
    Anthropic — cache_control would be invalid. Reject."""
    import litellm

    monkeypatch.setattr(
        litellm,
        "get_llm_provider",
        lambda model: (model, "vertex_ai", None, None),
    )
    assert client_module._is_anthropic("vertex_ai/gemini-1.5-pro") is False


def test_is_anthropic_falls_back_to_heuristic_when_litellm_raises(monkeypatch):
    import litellm

    def _boom(model):
        raise RuntimeError("unknown model")

    monkeypatch.setattr(litellm, "get_llm_provider", _boom)
    assert client_module._is_anthropic("claude-future-model") is True
    assert client_module._is_anthropic("anthropic/claude-foo") is True
    assert client_module._is_anthropic("bedrock/anthropic.claude-3") is True
    assert client_module._is_anthropic("vertex_ai/claude-experimental") is True
    assert client_module._is_anthropic("gpt-9000") is False
