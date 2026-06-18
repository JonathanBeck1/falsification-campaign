from __future__ import annotations

from types import SimpleNamespace

from pydantic import SecretStr

from trader.notify.base import NullNotifier
from trader.notify.discord import DiscordNotifier
from trader.notify.ntfy import NtfyNotifier
from trader.notify.router import MultiNotifier, build_notifier


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        self.calls.append((title, body, error))


class FailingNotifier:
    def send(self, title: str, body: str, *, error: bool = False) -> None:
        raise RuntimeError("notify failed")


def test_multi_notifier_sends_to_all_children():
    one = RecordingNotifier()
    two = RecordingNotifier()

    MultiNotifier([one, two]).send("Research cycle succeeded", "run_id=abc", error=False)

    assert one.calls == [("Research cycle succeeded", "run_id=abc", False)]
    assert two.calls == [("Research cycle succeeded", "run_id=abc", False)]


def test_multi_notifier_suppresses_child_exceptions_and_continues():
    ok = RecordingNotifier()

    MultiNotifier([FailingNotifier(), ok]).send("Failure", "source down", error=True)

    assert ok.calls == [("Failure", "source down", True)]


def test_null_notifier_is_silent():
    assert NullNotifier().send("ignored", "ignored") is None


def test_build_notifier_is_disabled_by_default_even_with_configured_routes():
    notifier = build_notifier(
        SimpleNamespace(
            trader_alerts_enabled=False,
            discord_webhook_url=SecretStr("https://discord.example/webhook"),
            ntfy_topic="trader-alerts",
            ntfy_server_url="https://ntfy.example",
            ntfy_token=None,
        )
    )

    assert isinstance(notifier, NullNotifier)


def test_build_notifier_routes_enabled_discord_and_ntfy():
    notifier = build_notifier(
        SimpleNamespace(
            trader_alerts_enabled=True,
            discord_webhook_url=SecretStr("https://discord.example/webhook"),
            ntfy_topic="trader-alerts",
            ntfy_server_url="https://ntfy.example",
            ntfy_token=SecretStr("secret"),
        )
    )

    assert isinstance(notifier, MultiNotifier)
    assert any(isinstance(child, DiscordNotifier) for child in notifier.notifiers)
    assert any(isinstance(child, NtfyNotifier) for child in notifier.notifiers)
