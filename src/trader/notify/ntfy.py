"""ntfy phone notifier. Best-effort; never raises into pipeline code."""

from __future__ import annotations

import contextlib

import httpx


class NtfyNotifier:
    def __init__(
        self,
        *,
        topic: str,
        server_url: str = "https://ntfy.sh",
        token: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.topic = topic.strip("/")
        self.server_url = server_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        headers = {
            "Title": title,
            "Priority": "urgent" if error else "default",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with contextlib.suppress(Exception):
            httpx.post(
                f"{self.server_url}/{self.topic}",
                content=body,
                headers=headers,
                timeout=self.timeout,
            )
