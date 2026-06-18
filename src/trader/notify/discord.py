"""Discord webhook notifier. Best-effort; never raises into the trading loop."""

from __future__ import annotations

import contextlib

import httpx

from trader.notify.base import Notifier


class DiscordNotifier:
    def __init__(self, webhook_url: str, timeout: float = 5.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        prefix = ":rotating_light: " if error else ":bar_chart: "
        # Discord webhook content max 2000 chars; truncate to be safe.
        content = f"**{prefix}{title}**\n```\n{body[:1700]}\n```"
        # Notifications must never break the trading loop.
        with contextlib.suppress(Exception):
            httpx.post(self.webhook_url, json={"content": content}, timeout=self.timeout)


def build_notifier() -> Notifier:
    from trader.notify.router import build_notifier as build

    return build()
