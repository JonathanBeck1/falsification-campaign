from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from trader import cli
from trader.enrichment.schema import ENRICHER_CLASSIFIER, PROMPT_TEMPLATE_VERSION
from trader.normalization.models import Event, ModelOutputMeta
from trader.paper.intents import PaperTradeIntent
from trader.storage.store import Store


def _settings(db_path: Path, *, live: bool = False):
    return SimpleNamespace(
        sqlite_path=db_path,
        trader_live=live,
        trader_starting_cash=100_000.0,
        trader_max_position_pct=0.95,
        trader_max_daily_loss_pct=0.03,
        kill_switch_path=db_path.parent / ".kill",
    )


def _enriched_event(event_id: str = "evt-aapl") -> Event:
    now = datetime(2026, 5, 21, 12, 0, tzinfo=UTC)
    event = Event(
        event_id=event_id,
        source="demo_news",
        title="Apple raises guidance",
        summary="Apple raises guidance after services strength.",
        published_at=now,
        observed_at=now,
        ingested_at=now,
        classified_at=now,
        event_type="guidance_raise",
        sentiment="positive",
        sentiment_score=0.8,
        urgency="high",
    )
    event.model_outputs.append(
        ModelOutputMeta(
            classifier=ENRICHER_CLASSIFIER,
            prompt_version=PROMPT_TEMPLATE_VERSION,
            raw_output=(
                '{"schema_version":"v1","prompt_template_version":"tmpl-v1",'
                f'"event_id":"{event_id}","sentiment_label":"positive","sentiment_score":0.9,'
                '"urgency":"high","novelty_score":0.8,"event_type":"guidance_raise",'
                '"key_claims":[{"text":"Apple raised guidance.","quote":"Apple raises guidance","from_field":"title"}],'
                '"tickers_affected":["AAPL"],"is_actionable":true,"confidence":0.82,"abstain_reason":null}'
            ),
            validation_status="auto_passed",
            created_at=now,
        )
    )
    return event


def test_cli_stage_paper_intents_scores_risk_reviews_and_saves(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    store.save_news_event(_enriched_event())
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(
        [
            "stage-paper-intents",
            "--source",
            "demo_news",
            "--min-score",
            "60",
            "--limit",
            "20",
            "--last-price",
            "100",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert "staged=1" in out
    rows = store.list_paper_trade_intents(limit=5)
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["risk_status"] == "approved"
    assert rows[0]["final_action"] == "BUY"
    assert rows[0]["final_qty"] == 250


def test_cli_simulate_paper_intents_uses_simbroker_only(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    store = Store(db_path)
    store.save_paper_trade_intent(
        PaperTradeIntent(
            intent_id="intent-1",
            event_id="event-1",
            created_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
            ticker="QQQ",
            direction="bullish",
            candidate_score=72,
            confidence=0.8,
            proposed_action="BUY",
            proposed_target_pct=0.25,
            risk_status="approved",
            risk_reason="target 25%",
            final_action="BUY",
            final_qty=3,
            status="staged",
        )
    )
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path))

    rc = cli.main(["simulate-paper-intents", "--limit", "10", "--last-price", "500"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "simulated=1" in out
    row = store.list_paper_trade_intents(limit=1)[0]
    assert row["status"] == "simulated"
    assert row["simulated_order_id"].startswith("sim-PaperIntentEngine-")
    assert store.get_decisions_for_brain("PaperIntentEngine") == []


def test_cli_simulate_paper_intents_refuses_live_mode(monkeypatch, tmp_path: Path, capsys):
    db_path = tmp_path / "trader.sqlite"
    Store(db_path)
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(db_path, live=True))

    rc = cli.main(["simulate-paper-intents", "--last-price", "500"])

    assert rc == 1
    assert "Refusing to simulate paper intents while TRADER_LIVE=true" in capsys.readouterr().out
