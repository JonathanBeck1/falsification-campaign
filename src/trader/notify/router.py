from __future__ import annotations

import contextlib

from trader.notify.base import Notifier, NullNotifier


class MultiNotifier:
    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = list(notifiers)

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        for notifier in self.notifiers:
            with contextlib.suppress(Exception):
                notifier.send(title, body, error=error)


def _secret_value(value) -> str | None:
    if value is None:
        return None
    get_secret_value = getattr(value, "get_secret_value", None)
    if get_secret_value is not None:
        return str(get_secret_value())
    return str(value)


def build_notifier(settings=None) -> Notifier:
    if settings is None:
        from trader.config import get_settings

        settings = get_settings()
    if not getattr(settings, "trader_alerts_enabled", False):
        return NullNotifier()

    notifiers: list[Notifier] = []
    discord_webhook_url = _secret_value(getattr(settings, "discord_webhook_url", None))
    if discord_webhook_url:
        from trader.notify.discord import DiscordNotifier

        notifiers.append(DiscordNotifier(discord_webhook_url))

    ntfy_topic = getattr(settings, "ntfy_topic", None)
    if ntfy_topic:
        from trader.notify.ntfy import NtfyNotifier

        notifiers.append(
            NtfyNotifier(
                topic=str(ntfy_topic),
                server_url=str(getattr(settings, "ntfy_server_url", "https://ntfy.sh")),
                token=_secret_value(getattr(settings, "ntfy_token", None)),
            )
        )

    if not notifiers:
        return NullNotifier()
    if len(notifiers) == 1:
        return notifiers[0]
    return MultiNotifier(notifiers)
