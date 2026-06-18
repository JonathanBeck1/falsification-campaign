from __future__ import annotations

from typing import Protocol


class Notifier(Protocol):
    def send(self, title: str, body: str, *, error: bool = False) -> None: ...


class NullNotifier:
    """Default notifier. Silent and safe for local research runs."""

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        return None
