from __future__ import annotations

from trader import cli


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bool]] = []

    def send(self, title: str, body: str, *, error: bool = False) -> None:
        self.calls.append((title, body, error))


def test_cli_notify_test_uses_configured_notifier(monkeypatch, capsys):
    notifier = RecordingNotifier()
    monkeypatch.setattr(cli, "build_notifier", lambda: notifier)

    rc = cli.main(["notify-test", "--title", "Trader test", "--body", "ntfy route works"])

    assert rc == 0
    assert notifier.calls == [("Trader test", "ntfy route works", False)]
    assert "Notification route tested" in capsys.readouterr().out
