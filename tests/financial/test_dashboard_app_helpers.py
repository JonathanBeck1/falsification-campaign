from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


class _FakeColumn:
    def __enter__(self) -> _FakeColumn:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _FakeStreamlit(ModuleType):
    def __init__(self) -> None:
        super().__init__("streamlit")
        self.session_state: dict[str, Any] = {}
        self.query_params: dict[str, Any] = {}

    def cache_data(self, **_: object):
        def decorator(fn):
            return fn

        return decorator

    def set_page_config(self, **_: object) -> None:
        return None

    def html(self, _: str) -> None:
        return None

    def columns(self, spec: int | list[object]) -> list[_FakeColumn]:
        count = spec if isinstance(spec, int) else len(spec)
        return [_FakeColumn() for _ in range(count)]

    def radio(
        self,
        _label: str,
        options: list[str],
        *,
        index: int = 0,
        **_: object,
    ) -> str:
        return options[index]

    def selectbox(
        self,
        _label: str,
        options: list[str],
        *,
        index: int = 0,
        **_: object,
    ) -> str:
        return options[index]

    def caption(self, _: str) -> None:
        return None

    def code(self, _: str, **__: object) -> None:
        return None

    def altair_chart(self, *_: object, **__: object) -> None:
        return None


def _load_dashboard_app(monkeypatch) -> tuple[ModuleType, _FakeStreamlit]:
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    module_path = Path(__file__).resolve().parents[2] / "apps" / "dashboard.py"
    spec = importlib.util.spec_from_file_location("dashboard_app_for_tests", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "dashboard_app_for_tests", module)
    spec.loader.exec_module(module)
    return module, fake_streamlit


def test_filter_news_rows_handles_ticker_source_type_and_urgency(monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)
    rows = [
        {"tickers": "QQQ, SPY", "source": "yahoo_finance", "event_type": "fed_commentary", "urgency": "high"},
        {"tickers": "AAPL", "source": "cnbc.com", "event_type": "earnings_surprise", "urgency": "normal"},
    ]

    assert module._filter_news_rows(  # type: ignore[attr-defined]
        rows,
        ticker="SPY",
        source="yahoo_finance",
        event_type="fed_commentary",
        urgency="high",
    ) == [rows[0]]
    assert module._filter_news_rows(  # type: ignore[attr-defined]
        rows,
        ticker="ALL",
        source="ALL",
        event_type="ALL",
        urgency="ALL",
    ) == rows


def test_event_tape_links_rows_to_news_desk_event_selection(monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)

    markup = module._event_tape(  # type: ignore[attr-defined]
        [
            {
                "event_id": "evt one",
                "observed_at": "2026-05-20T10:00:00+00:00",
                "source": "yahoo_finance",
                "tickers": "SPY",
                "event_type": "fed_commentary",
                "urgency": "high",
                "sentiment": "neutral",
                "title": "Fed commentary moves SPY",
            }
        ]
    )

    assert 'class="tape-link"' in markup
    assert "?terminal_module=NEWS+DESK&event_id=evt%20one" in markup
    assert "Fed commentary moves SPY" in markup


def test_query_value_unwraps_strings_and_legacy_lists(monkeypatch):
    module, fake_streamlit = _load_dashboard_app(monkeypatch)

    fake_streamlit.query_params = {"event_id": ["evt-1"], "terminal_module": "NEWS DESK"}

    assert module._query_value("event_id") == "evt-1"  # type: ignore[attr-defined]
    assert module._query_value("terminal_module") == "NEWS DESK"  # type: ignore[attr-defined]
    assert module._query_value("missing") is None  # type: ignore[attr-defined]


def test_selected_news_row_uses_query_param_and_falls_back_to_first(monkeypatch):
    module, fake_streamlit = _load_dashboard_app(monkeypatch)
    rows = [{"event_id": "one", "title": "First"}, {"event_id": "two", "title": "Second"}]

    fake_streamlit.query_params = {"event_id": "two"}
    assert module._selected_news_row(rows)["title"] == "Second"  # type: ignore[attr-defined]

    fake_streamlit.query_params = {"event_id": "missing"}
    assert module._selected_news_row(rows)["title"] == "First"  # type: ignore[attr-defined]


def test_safe_report_preview_reads_only_inside_reports_dir(tmp_path: Path, monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "daily.md"
    report.write_text("# Daily\n\nAlpha", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(module, "REPORTS_DIR", reports)

    assert module._safe_report_preview(str(report)) == "# Daily\n\nAlpha"  # type: ignore[attr-defined]
    assert module._safe_report_preview(str(outside)) == "Report path is outside the reports directory."  # type: ignore[attr-defined]
    assert module._safe_report_preview(str(reports / "missing.md")).startswith("Could not read report:")  # type: ignore[attr-defined]


def test_research_run_detail_surfaces_selected_artifacts(monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)
    row = {
        "run_id": "run-1",
        "status": "succeeded",
        "started_at": "2026-05-20T10:00:00+00:00",
        "finished_at": "2026-05-20T10:02:00+00:00",
        "benchmark": "SPY",
        "entry_time": "observed_at",
        "horizons": "5m,1h",
        "candidate_count": 4,
        "outcome_report_path": "output/reports/outcomes.md",
        "review_report_path": "output/reports/review.md",
        "manifest_path": "output/reports/manifest.md",
        "error": "",
    }

    markup = module._research_run_detail(row)  # type: ignore[attr-defined]

    assert "run-1" in markup
    assert "succeeded" in markup
    assert "output/reports/outcomes.md" in markup
    assert "output/reports/manifest.md" in markup
    assert "No research run selected" in module._research_run_detail(None)  # type: ignore[attr-defined]


def test_source_health_alerts_surface_feed_errors(monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)
    rows = [
        {"source": "fed", "latest_status": "error", "latest_error": "timeout"},
        {"source": "yahoo_news", "latest_status": "ok", "latest_error": ""},
    ]

    alerts = module._source_health_alerts(rows)  # type: ignore[attr-defined]
    markup = module._source_health_badges(rows)  # type: ignore[attr-defined]

    assert alerts == [
        {
            "level": "error",
            "label": "Source fetch failed",
            "detail": "fed latest fetch failed: timeout",
        }
    ]
    assert "fed" in markup
    assert "error" in markup
    assert "yahoo_news" in markup


def test_paper_desk_module_and_summary(monkeypatch):
    module, _ = _load_dashboard_app(monkeypatch)
    rows = [
        {"status": "staged", "risk_status": "approved"},
        {"status": "risk_blocked", "risk_status": "blocked"},
        {"status": "simulated", "risk_status": "approved"},
    ]

    assert "PAPER DESK" in module.MODULES  # type: ignore[attr-defined]
    markup = module._paper_intent_summary(rows)  # type: ignore[attr-defined]

    assert "Execution is simulated only" in markup
    assert "staged" in markup
    assert "risk_blocked" in markup
    assert "simulated" in markup
