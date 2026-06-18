"""One-trading-day runner. Pulls a snapshot, runs every brain, executes via SimBroker,
records everything, posts a summary to Discord.

This is the *core* function called by the scheduler each day.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

import structlog

from trader.adapters.alpaca.market import fetch_daily_bars
from trader.adapters.alpaca.news import fetch_alpaca_news
from trader.adapters.macro.fed import fetch_fed_press
from trader.adapters.macro.fred import fetch_macro
from trader.adapters.news.finnhub import fetch_news
from trader.adapters.news.web import fetch_web_news
from trader.adapters.news.yahoo import fetch_yahoo_news, merge_news
from trader.adapters.sec.edgar import fetch_sec_8k_filings
from trader.backtesting.baselines.buy_and_hold import BuyAndHoldBrain
from trader.config import Settings, get_settings
from trader.execution.broker import SimBroker
from trader.execution.risk import AccountState, RiskGate
from trader.ingestion.heartbeat import HeartbeatTracker, gate_llm_brains_on_freshness
from trader.ingestion.source_health import CompositeSourceTracker, StoreSourceHealthTracker
from trader.notify.discord import build_notifier
from trader.signals.base import Brain, Decision
from trader.signals.classical import ClassicalBrain
from trader.signals.sentiment_momentum import SentimentMomentumBrain
from trader.signals.variants import (
    BrainVariantConfig,
    all_phase_variants,
    build_brain,
    max_position_pct_for_profile,
    variant_requires_store,
)
from trader.storage.snapshot import DailySnapshot, build_snapshot
from trader.storage.store import Store

INTER_LLM_CALL_SLEEP_SECONDS = 0.5

log = structlog.get_logger()


def _shared_risk_gate(settings: Settings) -> RiskGate:
    return RiskGate(
        max_position_pct=settings.trader_max_position_pct,
        max_daily_loss_pct=settings.trader_max_daily_loss_pct,
        kill_switch_path=settings.kill_switch_path,
    )


def _variant_risk_gate(settings: Settings, config: BrainVariantConfig) -> RiskGate:
    """Per-variant gate. Only `max_position_pct` varies by risk profile —
    hard limits (kill switch, daily loss) are identical across variants.
    """
    return RiskGate(
        max_position_pct=max_position_pct_for_profile(config.risk_profile),
        max_daily_loss_pct=settings.trader_max_daily_loss_pct,
        kill_switch_path=settings.kill_switch_path,
    )


def all_brains(settings: Settings, store: Store | None = None) -> list[Brain]:
    """Phase 1 brain roster: 3 unchanged baselines + 6 Phase-1 variants.

    Per brain/10_llm_agent_boundaries.md, LLMs do not make trade decisions.
    Variants of `HybridBrain` use an LLM only to extract structured features;
    a deterministic `SizingPolicy` decides.

    Per brain/20_llm_decision_boundary_adr.md (drift 2), the daily LLM budget
    is checked BEFORE adding any LLM brain to the roster, not after the call —
    so we cannot spend past the cap.

    Per brain/decisions/2026-05-21-horse-race-phase-1.md, this returns 9 brains:
    BuyAndHold + Classical + SentimentMomentum + 6 Phase-1 variants. Tests can
    monkeypatch this function to scope a run to a fake brain.
    """
    brains: list[Brain] = [
        BuyAndHoldBrain(),
        ClassicalBrain(),
    ]
    if store is not None:
        brains.append(SentimentMomentumBrain(store=store))

    llm_available = settings.anthropic_api_key is not None or settings.openai_api_key is not None
    budget_exhausted = (
        store is not None
        and store.llm_cost_today() >= settings.trader_llm_daily_budget_usd
    )
    if budget_exhausted:
        log.info(
            "llm_budget_exhausted_skipping_llm_variants",
            today_usd=store.llm_cost_today() if store is not None else 0.0,
            cap_usd=settings.trader_llm_daily_budget_usd,
        )

    for variant in all_phase_variants():
        if variant_requires_store(variant) and store is None:
            continue
        if variant.llm_model is not None and (not llm_available or budget_exhausted):
            continue
        brains.append(
            build_brain(
                variant,
                store=store,
                daily_budget_usd=settings.trader_llm_daily_budget_usd,
            )
        )

    return brains


def risk_gate_for(brain: Brain, settings: Settings) -> RiskGate:
    """Return the RiskGate for a brain. Variants get a per-profile gate;
    everything else falls back to the shared global gate.

    Hard limits (kill switch, daily loss) are identical across variants —
    only `max_position_pct` varies by risk profile.
    """
    variant_by_name = {v.name: v for v in all_phase_variants()}
    config = variant_by_name.get(brain.name)
    if config is None:
        return _shared_risk_gate(settings)
    return _variant_risk_gate(settings, config)


def _safe_fetch_source(source: str, fetcher, heartbeat=None):
    """Run `fetcher()`, log any exception, and record to the heartbeat
    tracker. Returns [] on failure so callers can treat all sources
    uniformly."""
    if heartbeat is not None:
        start_fetch = getattr(heartbeat, "start_fetch", None)
        if start_fetch is not None:
            with contextlib.suppress(Exception):
                start_fetch(source)
    try:
        result = fetcher()
    except Exception as exc:
        log.warning("source_fetch_failed", source=source, error=str(exc))
        if heartbeat is not None:
            heartbeat.record_fetch(source, item_count=0, error=str(exc))
        return []
    if heartbeat is not None:
        heartbeat.record_fetch(source, item_count=len(result))
    return result


def fetch_source_news(
    ticker: str,
    context_tickers: list[str],
    sec_tickers: list[str] | None,
    *,
    lookback_days: int | None = None,
    heartbeat=None,
) -> dict[str, list]:
    """Return news items keyed by source-adapter name.

    Used both to build the merged snapshot AND to feed source-specific
    normalizers (`trader.normalization.*`). All adapters are best-effort —
    a failure on any one returns an empty list, doesn't break the run.

    `lookback_days`, when set, overrides the per-source defaults for adapters
    that support a lookback window (finnhub, alpaca_news, fed, web_news).
    Yahoo and SEC don't accept it — yfinance returns "what's on the page now"
    and SEC uses a per-ticker count. Default `None` preserves prior behavior.

    Fed RSS default changed from 14 → 90 days: the FOMC publishes monetary-
    policy items roughly every 6 weeks, so a 14-day window persisted zero Fed
    events on most days (see brain/decisions/2026-05-19-milestone-1-first-event-report.md).
    90 days reliably captures the last meeting plus its minutes.
    """
    finnhub_lookback = lookback_days if lookback_days is not None else 3
    alpaca_lookback = lookback_days if lookback_days is not None else 3
    fed_lookback = lookback_days if lookback_days is not None else 90
    web_lookback = lookback_days if lookback_days is not None else 3
    return {
        "finnhub": _safe_fetch_source(
            "finnhub",
            lambda: fetch_news(ticker, lookback_days=finnhub_lookback, limit=15),
            heartbeat=heartbeat,
        ),
        "alpaca_news": _safe_fetch_source(
            "alpaca_news",
            lambda: fetch_alpaca_news(context_tickers, lookback_days=alpaca_lookback, limit=30),
            heartbeat=heartbeat,
        ),
        "yahoo_news": _safe_fetch_source(
            "yahoo_news",
            lambda: fetch_yahoo_news(context_tickers, per_ticker_limit=8),
            heartbeat=heartbeat,
        ),
        "sec_edgar": (
            _safe_fetch_source(
                "sec_edgar",
                lambda: fetch_sec_8k_filings(sec_tickers, count_per_ticker=3),
                heartbeat=heartbeat,
            )
            if sec_tickers
            else []
        ),
        "fed": _safe_fetch_source(
            "fed", lambda: fetch_fed_press(lookback_days=fed_lookback), heartbeat=heartbeat
        ),
        "web_news": _safe_fetch_source(
            "web_news", lambda: fetch_web_news(lookback_days=web_lookback), heartbeat=heartbeat
        ),
    }


def _merge_source_news(by_source: dict[str, list]) -> list:
    """Merge news adapter outputs in deterministic source-priority order."""
    return merge_news(
        by_source.get("finnhub", []),
        by_source.get("alpaca_news", []),
        by_source.get("sec_edgar", []),
        by_source.get("fed", []),
        by_source.get("yahoo_news", []),
        by_source.get("web_news", []),
    )


def fetch_today_snapshot(
    ticker: str,
    context_tickers: list[str] | None = None,
    sec_tickers: list[str] | None = None,
) -> DailySnapshot:
    """Pull price bars + news from all configured sources + macro.

    News sources (all best-effort — a failure on any one returns empty, doesn't
    break the run):
      - Finnhub company news for the trade ticker
      - Alpaca News (Benzinga) for the context tickers
      - Yahoo Finance news for the context tickers
      - SEC EDGAR 8-K filings for the index constituents we track
      - Federal Reserve monetary-policy press releases

    `context_tickers` is the broader set we fetch news for; defaults to just the
    trade ticker. `sec_tickers` defaults to settings.sec_tickers via the caller.
    """
    bars = fetch_daily_bars(ticker, lookback_days=260)
    if not bars:
        raise RuntimeError(f"No bars returned for {ticker}")

    context = context_tickers or [ticker]
    by_source = fetch_source_news(ticker, context, sec_tickers)

    # Ordering matters for dedup: earlier sources win on duplicate headlines.
    # Order roughly by timestamp reliability + signal density.
    news = _merge_source_news(by_source)
    macro = fetch_macro()
    return build_snapshot(
        ticker=ticker,
        trade_date=bars[-1].timestamp.date(),
        bars=bars,
        news=news,
        macro=macro,
    )


def run_one_day(
    snapshot: DailySnapshot | None = None,
    *,
    sleep_fn: Callable[[float], None] | None = None,
) -> dict[str, Decision]:
    """Run all brains for one trading day. Returns {brain_name: Decision}.

    If `snapshot` is None we fetch a fresh one (live mode). Otherwise we use the
    one passed in (used by the replay harness).

    `sleep_fn` is the inter-LLM-call throttle. Defaults to `time.sleep`. Tests
    can pass a recorder or no-op to skip the 500ms pause between LLM brains.
    """
    s = get_settings()
    store = Store(s.sqlite_path)
    notifier = build_notifier()
    if sleep_fn is None:
        sleep_fn = time.sleep

    heartbeat = HeartbeatTracker()
    source_health = StoreSourceHealthTracker(store)
    source_tracker = CompositeSourceTracker(heartbeat, source_health)
    if snapshot is None:
        from trader.ingestion.events import persist_source_events

        log.info(
            "fetching_snapshot",
            ticker=s.trader_ticker,
            context_tickers=s.context_tickers,
            sec_tickers=s.sec_tickers,
        )
        bars = fetch_daily_bars(s.trader_ticker, lookback_days=260)
        if not bars:
            raise RuntimeError(f"No bars returned for {s.trader_ticker}")
        by_source = fetch_source_news(
            s.trader_ticker, s.context_tickers, s.sec_tickers, heartbeat=source_tracker
        )
        event_counts = persist_source_events(
            store=store,
            by_source=by_source,
            ticker=s.trader_ticker,
            context_tickers=s.context_tickers,
            source_tracker=source_tracker,
        )
        log.info("news_events_persisted", counts=event_counts)
        news = _merge_source_news(by_source)
        snapshot = build_snapshot(
            ticker=s.trader_ticker,
            trade_date=bars[-1].timestamp.date(),
            bars=bars,
            news=news,
            macro=fetch_macro(),
        )

    # Persist the snapshot once.
    store.save_snapshot(
        snapshot_id=snapshot.snapshot_id,
        trade_date=snapshot.trade_date.isoformat(),
        ticker=snapshot.ticker,
        payload=snapshot.to_payload(),
    )

    last_price = snapshot.latest_bar.close
    decisions: dict[str, Decision] = {}
    summary_lines: list[str] = []

    # Freshness gate (audit problem #2): if every news adapter is stale,
    # refuse to run LLM-using brains for this cycle. Deterministic brains
    # still run on whatever data is in the snapshot.
    freshness = gate_llm_brains_on_freshness(heartbeat)

    llm_calls_used = 0
    llm_brain_ran_in_cycle = False

    for brain in all_brains(s, store=store):
        risk = risk_gate_for(brain, s)
        if brain.uses_llm and freshness.should_skip_llm:
            log.warning(
                "skipping_llm_brain_due_to_stale_data",
                brain=brain.name,
                stale_sources=freshness.stale_sources,
            )
            store.record_event(
                "warn",
                brain.name,
                f"llm_skipped_freshness_gate stale={','.join(freshness.stale_sources)}",
            )
            continue

        # Per-brain virtual portfolio + halt check BEFORE brain.decide() so
        # halted brains don't spend an LLM call (PR #59 gate-ordering).
        sim = SimBroker(
            brain=brain.name,
            ticker=snapshot.ticker,
            store=store,
            starting_cash=s.trader_starting_cash,
            last_price=last_price,
        )
        prior_equity = store.get_latest_equity(brain.name)
        equity_session_start = float(prior_equity["equity"]) if prior_equity else sim.equity()
        account = AccountState(
            cash=sim.cash(),
            position_qty=sim.position_qty(),
            avg_cost=sim.avg_cost(),
            equity_today=sim.equity(),
            equity_session_start=equity_session_start,
            day_trades_last_5d=store.count_day_trades_last_n_days(brain.name, n_days=5),
        )
        halted, reason = risk.trading_halted(account=account, llm_cost_today_usd=store.llm_cost_today())
        if halted:
            log.warning("trading_halted", brain=brain.name, reason=reason)
            store.record_event("kill", brain.name, reason)
            summary_lines.append(f"{brain.name}: HALTED — {reason}")
            continue

        # Horse-race LLM-call cap and inter-call sleep. Keeps per-cycle LLM
        # spend bounded once the 19-brain matrix is running.
        if brain.uses_llm and llm_calls_used >= s.trader_max_llm_calls_per_cycle:
            log.warning(
                "skipping_llm_brain_due_to_call_cap",
                brain=brain.name,
                cap=s.trader_max_llm_calls_per_cycle,
            )
            store.record_event(
                "warn",
                brain.name,
                f"llm_skipped_call_cap cap={s.trader_max_llm_calls_per_cycle}",
            )
            continue
        if brain.uses_llm and llm_brain_ran_in_cycle:
            sleep_fn(INTER_LLM_CALL_SLEEP_SECONDS)

        try:
            decision = brain.decide(snapshot)
            if brain.uses_llm:
                llm_calls_used += 1
                llm_brain_ran_in_cycle = True
        except Exception as exc:
            log.exception("brain_failed", brain=brain.name)
            store.record_event("error", brain.name, f"decide() raised: {exc}")
            continue

        decisions[brain.name] = decision
        decision_id = store.save_decision(
            snapshot_id=snapshot.snapshot_id,
            brain=brain.name,
            action=decision.action,
            target_pct=decision.target_pct,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            llm_cost_usd=decision.llm_cost_usd,
        )
        if decision.llm_prompt_hash:
            store.record_llm_call(
                decision_id=decision_id,
                brain=brain.name,
                model=decision.llm_model or "unknown",
                prompt_hash=decision.llm_prompt_hash,
                input_tokens=decision.llm_input_tokens,
                output_tokens=decision.llm_output_tokens,
                cached_tokens=decision.llm_cached_tokens,
                cost_usd=decision.llm_cost_usd,
                latency_ms=decision.llm_latency_ms,
            )
            # Post-LLM cost halt re-check (Codex re-review 2026-05-20):
            # the pre-decision halt above caught already-exhausted state,
            # but if THIS brain's call pushes spend OVER the cap, we
            # must block the order — otherwise an LLM brain whose call
            # crosses the cap still trades. Only re-check for LLM brains
            # (the cap can only have moved if a call was just recorded).
            halted_after_llm, reason = risk.trading_halted(
                account=account, llm_cost_today_usd=store.llm_cost_today()
            )
            if halted_after_llm:
                log.warning(
                    "trading_halted_post_llm", brain=brain.name, reason=reason
                )
                store.record_event(
                    "kill", brain.name, f"post-llm-cap: {reason}"
                )
                summary_lines.append(f"{brain.name}: HALTED — {reason}")
                continue

        verdict = risk.review(
            proposed_action=decision.action,
            proposed_target_pct=decision.target_pct,
            last_price=last_price,
            account=account,
        )
        if not verdict.approved:
            store.record_event("warn", brain.name, f"order rejected: {verdict.reason}")
            summary_lines.append(f"{brain.name}: REJECT — {verdict.reason}")
            continue

        if verdict.final_action == "HOLD" or verdict.final_qty == 0:
            store.record_equity(brain.name, snapshot.trade_date.isoformat(), sim.equity())
            summary_lines.append(f"{brain.name}: HOLD  (target {decision.target_pct:.0%}, eq ${sim.equity():,.0f})")
            continue

        try:
            fill = sim.fill_at_market(
                side="buy" if verdict.final_action == "BUY" else "sell",
                qty=verdict.final_qty,
                price=last_price,
                decision_id=decision_id,
            )
            store.record_equity(brain.name, snapshot.trade_date.isoformat(), sim.equity())
            summary_lines.append(
                f"{brain.name}: {verdict.final_action} {fill.filled_qty} @ ${fill.filled_avg_price:.2f}  "
                f"(eq ${sim.equity():,.0f}, conf {decision.confidence:.2f})"
            )
        except Exception as exc:
            log.exception("sim_fill_failed", brain=brain.name)
            store.record_event("error", brain.name, f"sim fill failed: {exc}")
            summary_lines.append(f"{brain.name}: SIM ERROR — {exc}")

    # Post summary
    title = f"{snapshot.ticker} {snapshot.trade_date} — daily run"
    body = "\n".join(summary_lines)
    notifier.send(title, body)
    log.info("run_complete", n_brains=len(decisions), trade_date=snapshot.trade_date.isoformat())
    return decisions
