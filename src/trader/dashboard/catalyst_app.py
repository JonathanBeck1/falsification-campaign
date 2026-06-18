"""Catalyst research dashboard — see what the pipeline has done, in the browser.

Reads the real research artifacts (research/*.md, output/catalysts/*.csv) and the
parsed CEF-resolution table, and presents them as an interactive local UI.

Launch from the worktree root:
    .venv/bin/streamlit run src/trader/dashboard/catalyst_app.py
Then open the URL it prints (default http://localhost:8501).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "research"
OUT = ROOT / "output" / "catalysts"

st.set_page_config(page_title="Catalyst Research", page_icon="📊", layout="wide")


# --------------------------------------------------------------------------- data
@st.cache_data
def load_cef_resolution() -> pd.DataFrame | None:
    """Parse the 9-column per-campaign table out of the resolution report."""
    p = RESEARCH / "cef_resolution_report.md"
    if not p.exists():
        return None
    rows = []
    for line in p.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 9 or cells[0] in ("Ticker", "") or set(cells[0]) <= set("-"):
            continue
        rows.append(cells)
    if not rows:
        return None
    df = pd.DataFrame(
        rows,
        columns=["ticker", "name", "date_13d", "sponsor", "class", "outcome", "trigger", "res_date", "days"],
    )
    df["days"] = pd.to_numeric(df["days"].replace("—", None), errors="coerce")
    df["date_13d"] = pd.to_datetime(df["date_13d"], errors="coerce")
    df["resolved"] = df["outcome"].str.lower().ne("ongoing")
    return df


@st.cache_data
def load_csv(name: str) -> pd.DataFrame | None:
    p = OUT / name
    return pd.read_csv(p) if p.exists() else None


SCOREBOARD = pd.DataFrame(
    [
        # ---- Original hand-built tests ----
        ("Intraday iron condor", "liquid index", "❌ no edge", "crushed by buy & hold"),
        ("VRP premium-selling", "liquid index", "❌ no edge", "+$1,273 was selection bias → break-even"),
        ("IPO lock-up expiry", "single-name IPOs", "❌ no edge", "CAR[0,+21] +0.9% (t=0.8); decayed"),
        ("Follow Saba 13D (broad, 6m)", "CEF niche", "❌ killed by frictions", "+1m pop +1.4% → +0.4% net of cost"),
        ("SPAC trust-arb", "SPAC niche", "❌ no edge", "trades at premium; below T-bills"),
        ("Index-rebalance effect", "S&P 500", "❌ no edge", "additions -0.7% (t=-1.3); gone since ~2010"),
        ("CEF discount-capture", "CEF niche", "❌ falsified (real data)", "real backtest gate FAIL; +10.5% was outliers+glitch"),
        # ---- Mining campaign (3,647 strategies + 2,410 events) ----
        ("Price strategies x 15 ETFs", "liquid index", "❌ 0 survivors", "870 variants, best DSR 55%"),
        ("QQQ option signals v1", "QQQ options", "❌ 0 survivors", "48 variants, all noise"),
        ("QQQ option signals v2 (GEX/skew/flow)", "QQQ options", "❌ 0 survivors", "56 richer features, all noise"),
        ("Cross-sectional / pairs", "ETF pairs", "⚠️ 28 → 0 after friction", "all SPY/IVV artifact, 0.998 corr, ~3bp alpha vs ~5bp cost"),
        ("Multi-asset / regime", "TLT/GLD/VIX/HYG", "❌ 0 survivors", "53 variants, all noise"),
        ("Intraday QQQ (overnight/gap/lunch)", "intraday", "🪦 killed: data bug", "Sharpe 11 was parity-spot artifact, not real QQQ"),
        ("PEAD post-earnings drift", "mid-cap names", "🪦 killed: look-ahead", "+3.74% was day-0 in cohort AND CAR; fixed = -3.70%"),
        ("8-K item-type breakdown", "mega-caps", "❌ no item-effect", "1315 filings; OOS sign flips (-1.0% vs +2.3%)"),
        ("Small-cap / niche universe", "IJR/REIT/BDC/MLP", "❌ 0 survivors", "1044 variants, all noise"),
        ("Pre-2010 OOS extension", "SPY/DIA/EWJ 1993+", "❌ 0 survivors", "174 variants, regime-change confirms decay"),
    ],
    columns=["Idea/Space", "Arena", "Verdict", "Key result"],
)


# --------------------------------------------------------------------------- pages
def page_scoreboard() -> None:
    st.title("📊 Catalyst Research — Live View")
    st.caption("Everything the falsification pipeline has tested, and where it landed.")
    st.dataframe(SCOREBOARD, width='stretch', hide_index=True)
    st.info(
        "**Bottom line:** no systematic edge for this shop — now *measured*, not estimated. "
        "**17 spaces tested rigorously** (7 hand-built + 10 mining-lab spaces, 3,647 variants + "
        "2,410 events). All falsified — 14 under the deflated-Sharpe + OOS gate, and 3 'passes' "
        "caught by human sanity checks the lab alone couldn't enforce: cross-sectional pair-trade "
        "frictions, intraday parity-spot data bug, and PEAD cohort look-ahead. The durable asset "
        "is the falsification machine itself: it caught a +10.5% mirage AND a Sharpe-11 data bug "
        "AND a t=6.11 look-ahead before any dollar was risked."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spaces tested", "17")
    c2.metric("Variants / events", "6,057")
    c3.metric("Falsified", "17")
    c4.metric("Genuine survivors", "0")


def page_cef() -> None:
    st.title("📈 CEF Activist Campaigns (Saba)")
    df = load_cef_resolution()
    if df is None:
        st.warning("No resolution data found. Run the CEF resolution study first.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Campaigns", len(df))
    c2.metric("Resolved", f"{int(df.resolved.sum())}  ({df.resolved.mean():.0%})")
    med = df.loc[df.resolved, "days"].median()
    c3.metric("Median days to resolve", "—" if pd.isna(med) else int(med))

    st.subheader("Resolution rate by sponsor")
    by_sponsor = (
        df.groupby("sponsor").agg(rate=("resolved", "mean"), n=("resolved", "size")).sort_values("rate", ascending=False)
    )
    st.bar_chart(by_sponsor["rate"])
    st.caption("Fast resolvers (Tortoise/ClearBridge/MFS/Pioneer) vs draggers (Invesco/abrdn/BNY Mellon).")

    cc1, cc2 = st.columns(2)
    with cc1:
        st.subheader("By asset class")
        st.bar_chart(df.groupby("class").resolved.mean())
    with cc2:
        st.subheader("Campaign timeline (by quarter)")
        timeline = df.set_index("date_13d").resample("QE").size()
        st.bar_chart(timeline)

    st.subheader("Time-to-resolution (resolved only)")
    days = df.loc[df.resolved, "days"].dropna()
    if len(days):
        bins = pd.cut(days, bins=[0, 365, 547, 730, 912, 1095, 2000],
                      labels=["<1y", "1-1.5y", "1.5-2y", "2-2.5y", "2.5-3y", ">3y"])
        st.bar_chart(bins.value_counts().sort_index())

    st.subheader("All campaigns")
    f1, f2, f3 = st.columns(3)
    spon = f1.multiselect("Sponsor", sorted(df.sponsor.unique()))
    cls = f2.multiselect("Class", sorted(df["class"].unique()))
    only_res = f3.checkbox("Resolved only")
    view = df.copy()
    if spon:
        view = view[view.sponsor.isin(spon)]
    if cls:
        view = view[view["class"].isin(cls)]
    if only_res:
        view = view[view.resolved]
    st.dataframe(
        view[["ticker", "name", "date_13d", "sponsor", "class", "outcome", "trigger", "days"]],
        width='stretch', hide_index=True,
    )


def page_ipo() -> None:
    st.title("🏛️ IPO Universe (lock-up study)")
    ipo = load_csv("ipo_universe.csv")
    if ipo is None:
        st.warning("No IPO universe found. Run the lock-up study first.")
        return
    ipo["ipo_date"] = pd.to_datetime(ipo["ipo_date"], errors="coerce")
    c1, c2 = st.columns(2)
    c1.metric("Genuine IPOs", len(ipo))
    c2.metric("With ticker", int(ipo["ticker"].notna().sum()))
    st.subheader("IPOs per quarter")
    st.bar_chart(ipo.dropna(subset=["ipo_date"]).set_index("ipo_date").resample("QE").size())
    st.subheader("All IPOs")
    st.dataframe(ipo, width='stretch', hide_index=True)


def page_reports() -> None:
    st.title("📄 Research Reports")
    files = sorted(RESEARCH.glob("*.md"))
    if not files:
        st.warning("No reports found.")
        return
    choice = st.selectbox("Report", [f.name for f in files])
    st.markdown((RESEARCH / choice).read_text())


def page_coverage() -> None:
    st.title("🗄️ Options Data Coverage")
    p = OUT / "data_coverage.json"
    if not p.exists():
        st.warning("No coverage summary yet. Run the overnight runner or the coverage refresh.")
        return
    cov = json.loads(p.read_text())
    ref = cov["reference_full_days"]
    st.caption(f"Reference (full history) = {ref} trading days, 2020-01-02 → present.")
    tickers = cov["tickers"]
    cols = st.columns(len(tickers))
    rows = []
    for col, (t, d) in zip(cols, tickers.items(), strict=False):
        col.metric(t, f"{d['pct_of_reference']:.0f}%", f"{d['days']}/{ref} days · {d['rows']/1e6:.0f}M rows")
        rows.append({"ticker": t, **d})
    df = pd.DataFrame(rows)
    st.bar_chart(df.set_index("ticker")["pct_of_reference"])
    st.dataframe(df, width="stretch", hide_index=True)
    spy = tickers.get("SPY")
    if spy and spy["pct_of_reference"] < 95:
        st.warning(
            f"**SPY is only {spy['pct_of_reference']:.0f}% backfilled** "
            f"({spy['days']} sampled days, through {spy['last']}) and not yet in the lake. "
            "The overnight runner resumes this backfill when the ThetaData terminal is running."
        )


def page_survival() -> None:
    st.title("🎚️ CEF Discount-Capture — Interactive Estimate")
    st.caption("Bounded estimate, NOT a backtest. Move the sliders to see the alpha range move.")
    c1, c2 = st.columns(2)
    res = c1.slider("Resolution rate (% of campaigns that resolve)", 20, 80, 60, 5) / 100
    disc = c1.slider("Entry discount captured on resolution (%)", 2, 20, 10, 1) / 100
    fric = c2.slider("Round-trip friction (%)", 0.0, 3.0, 1.0, 0.25) / 100
    hold = c2.slider("Median hold to resolution (years)", 1.0, 3.0, 2.0, 0.5)
    total = res * disc - fric
    ann = (1 + total) ** (1 / hold) - 1
    st.metric("Estimated annualized alpha (over the asset class)", f"{ann*100:+.2f}% / yr")
    st.caption("Formula: resolution_rate x entry_discount - friction, annualized over the hold.")
    rates, discs = [0.40, 0.50, 0.60, 0.70], [0.06, 0.10, 0.14]
    table = {
        f"{int(d*100)}% discount": [f"{((1 + (r*d - fric)) ** (1/hold) - 1)*100:+.1f}%" for r in rates]
        for d in discs
    }
    st.subheader("Sensitivity (annualized alpha)")
    st.dataframe(pd.DataFrame(table, index=[f"{int(r*100)}% resolve" for r in rates]), width="stretch")
    st.info(
        "This is the **only surviving lead** — and it's modest, slow (~2yr holds), convex "
        "(~half the basket does nothing), and capacity-limited. Real validation needs delisted "
        "price data (a free Tiingo key, or filing-based terminal values)."
    )


def _render_lab(d: dict, beta_note: str) -> None:
    st.caption(f"Last run: {d.get('run_at', '?')} · deflated Sharpe (multiple-testing) + out-of-sample")
    c1, c2, c3 = st.columns(3)
    c1.metric("Variants tested", d["n_trials"])
    c2.metric("Survivors (real edge)", d["n_survivors"])
    c3.metric("Noise 'winners' at naive p<0.05", f"~{d['expected_false_winners_p05']:.0f}")
    best = d.get("best")
    if best:
        real = d["best_dsr"] >= 0.95
        st.markdown(f"**Best in-sample:** `{best['name']}` — IS {best['is_sharpe']:.2f}, OOS {best['oos_sharpe']:.2f}")
        msg = (f"Deflated-Sharpe probability it's real: {d['best_dsr']:.0%} → "
               + ("✅ REAL after correction" if real else "❌ NOISE (fails deflation)"))
        (st.success if real else st.error)(msg)
    cols = ["name", "family", "ticker", "is_sharpe", "oos_sharpe"]
    st.markdown(f"**Survivors — cleared deflation AND held out-of-sample: {d['n_survivors']}**")
    if d["survivors"]:
        st.dataframe(pd.DataFrame(d["survivors"])[cols], width="stretch", hide_index=True)
    else:
        st.info("None — the best 'winners' fail the correction and/or fall apart out-of-sample.")
    if d["leaderboard"]:
        st.markdown("**Leaderboard by out-of-sample Sharpe:**")
        st.dataframe(pd.DataFrame(d["leaderboard"])[cols], width="stretch", hide_index=True)
        st.caption(beta_note)


_LAB_LABELS = {
    "strategy_lab.json": "📈 Price strategies (15 ETFs)",
    "options_lab.json": "🧬 QQQ option signals",
    "options_lab_v2.json": "🧬 QQQ options v2 (GEX/skew/flow)",
    "cross_sectional_lab.json": "🔀 Cross-sectional / pairs ⚠️",
    "multi_asset_lab.json": "🌐 Multi-asset / regime",
    "small_universe_lab.json": "🐭 Small-cap / niche ETFs",
    "pre2010_lab.json": "🕰️ Pre-2010 OOS extension",
}
_LAB_KILL_NOTES = {
    "cross_sectional_lab.json": (
        "⚠️ The 28 'survivors' below are ALL SPY/IVV (or similar near-identical-asset) pair "
        "trades. Daily return correlation 0.998; per-day 'alpha' ~3bp vs realistic pair "
        "frictions ~5bp. Net of cost = zero. Counted as KILL. "
        "(brain/decisions/2026-06-09-cross-sectional-spy-ivv-killed.md)"
    ),
}
_DISABLED_LABS = [
    ("⏱️ Intraday QQQ", "17 variants", "🪦 KILLED — data quality bug",
     "ThetaData's `underlying_price` is put-call-parity-derived synthetic, not real QQQ "
     "spot. Stale option quotes contaminate the open minute. Sharpe 11 gap_fade was a "
     "data artifact, not edge. Disabled until real minute spot is wired in. "
     "(brain/decisions/2026-06-09-intraday-lab-data-quality-kill.md)"),
    ("📊 PEAD post-earnings drift", "1,095 events", "🪦 KILLED — look-ahead",
     "Cohort split used sign of day-0 return; CAR window includes day-0. Same return "
     "defines cohort AND is measured. Fixed-window diff is -3.70% (opposite sign). "
     "(brain/decisions/2026-06-09-pead-lookahead-killed.md)"),
    ("📑 8-K item-type breakdown", "1,315 filings", "❌ Gate FAILED",
     "Best item (2.02 results): CAR[0,+21] +0.87% (t=1.97, marginal). OOS sign flips "
     "(-1.0% early, +2.3% late). No item-type effect. Also includes day-0 in CAR (same "
     "look-ahead risk as PEAD)."),
]


def _discover_labs() -> list[tuple[str, str, Path]]:
    out: list[tuple[str, str, Path]] = []
    for name, label in _LAB_LABELS.items():
        p = OUT / name
        if p.exists():
            out.append((name, label, p))
    # also catch any *_lab.json the table doesn't know about
    for p in sorted(OUT.glob("*_lab.json")):
        if p.name not in _LAB_LABELS:
            out.append((p.name, f"📊 {p.stem.replace('_', ' ')}", p))
    return out


def page_lab() -> None:
    st.title("🧪 Strategy-Mining Lab")
    st.caption("Every space tested — labs with live JSON below, killed/event studies summarized at the bottom.")
    labs = _discover_labs()

    # totals across alive + disabled spaces
    alive_trials = alive_survivors = 0
    for _name, _label, p in labs:
        d = json.loads(p.read_text())
        alive_trials += d.get("n_trials", 0)
        # cross-sectional survivors are friction-killed; don't count them as "real"
        if "cross_sectional" not in _name:
            alive_survivors += d.get("n_survivors", 0)
    disabled_count = len(_DISABLED_LABS)
    disabled_events = sum(int(v.replace(",", "").split()[0]) for _, v, _, _ in _DISABLED_LABS)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Live mining labs", len(labs))
    c2.metric("Killed / disabled labs", disabled_count)
    c3.metric("Total variants + events", alive_trials + disabled_events)
    c4.metric("Genuine survivors", alive_survivors)
    st.markdown("---")

    if not labs:
        st.warning("No lab results yet — wait for the nightly loop or run a lab runner.")
    else:
        tabs = st.tabs([label for _name, label, _p in labs])
        for tab, (name, _label, p) in zip(tabs, labs, strict=False):
            with tab:
                if name in _LAB_KILL_NOTES:
                    st.error(_LAB_KILL_NOTES[name])
                _render_lab(json.loads(p.read_text()),
                            "Heads-up: top OOS names are often market beta, not alpha.")

    st.markdown("---")
    st.subheader("🪦 Killed / disabled spaces (still part of the campaign)")
    st.caption("These spaces produced results but were disabled by sanity checks the lab couldn't enforce on its own.")
    for label, size, verdict, note in _DISABLED_LABS:
        with st.expander(f"{label}  ·  {size}  ·  {verdict}"):
            st.write(note)


PAGES = {
    "📊 Scoreboard": page_scoreboard,
    "🗄️ Data Coverage": page_coverage,
    "🧪 Strategy Lab": page_lab,
    "📈 CEF Campaigns": page_cef,
    "🎚️ Survival Estimate": page_survival,
    "🏛️ IPO Universe": page_ipo,
    "📄 Reports": page_reports,
}


def _loop_status() -> dict[str, bool]:
    import subprocess
    out: dict[str, bool] = {}
    for label, pattern in (("SPY long-run", "spy_long_run.sh"),
                           ("Nightly loop", "nightly_loop.sh")):
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        out[label] = r.returncode == 0 and bool(r.stdout.strip())
    return out


def main() -> None:
    st.sidebar.title("Catalyst Research")
    choice = st.sidebar.radio("View", list(PAGES))
    st.sidebar.caption(f"Reading from\n`{ROOT.name}/`")
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Loops**")
    for label, alive in _loop_status().items():
        st.sidebar.markdown(f"{'🟢' if alive else '⚪️'} {label}")
    PAGES[choice]()


main()
