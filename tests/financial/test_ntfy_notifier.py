from __future__ import annotations

import httpx

from trader.notify.ntfy import NtfyNotifier


def test_ntfy_notifier_posts_title_priority_and_body(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, *, content, headers, timeout):
        calls.append({"url": url, "content": content, "headers": headers, "timeout": timeout})
        return httpx.Response(200)

    monkeypatch.setattr("trader.notify.ntfy.httpx.post", fake_post)

    NtfyNotifier(topic="trader-alerts", server_url="https://ntfy.example", timeout=2.5).send(
        "Research cycle succeeded",
        "run_id=abc",
    )

    assert calls == [
        {
            "url": "https://ntfy.example/trader-alerts",
            "content": "run_id=abc",
            "headers": {"Title": "Research cycle succeeded", "Priority": "default"},
            "timeout": 2.5,
        }
    ]


def test_ntfy_notifier_uses_bearer_token_and_urgent_priority(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, *, content, headers, timeout):
        calls.append({"url": url, "content": content, "headers": headers, "timeout": timeout})
        return httpx.Response(200)

    monkeypatch.setattr("trader.notify.ntfy.httpx.post", fake_post)

    NtfyNotifier(topic="trader-alerts", server_url="https://ntfy.example/", token="secret").send(
        "Research cycle failed",
        "source down",
        error=True,
    )

    assert calls[0]["url"] == "https://ntfy.example/trader-alerts"
    assert calls[0]["headers"] == {
        "Title": "Research cycle failed",
        "Priority": "urgent",
        "Authorization": "Bearer secret",
    }


def test_ntfy_notifier_suppresses_post_errors(monkeypatch):
    def fake_post(url, *, content, headers, timeout):
        raise RuntimeError("network down")

    monkeypatch.setattr("trader.notify.ntfy.httpx.post", fake_post)

    assert NtfyNotifier(topic="trader-alerts").send("Title", "Body") is None
