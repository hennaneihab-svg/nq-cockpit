# THE COCKPIT — Complete Project Guide

This document explains how THE COCKPIT works, its daily practical utility for the trader, its deliberate design boundaries, and everything that can be customized without touching application source code.

---

## 1. What It Is

THE COCKPIT is a pre-market workstation and decision-support engine engineered specifically for discretionary trading on Nasdaq 100 futures contracts (NQ and MNQ).

It serves to prepare every session with structured rigor, identify high-impact macroeconomic risks, calculate exact position sizes, and log trades to drive continuous performance improvements.

What it is not:
- **Not a trade signal engine**: It issues no buy or sell alerts and makes no directional predictions on market trends.
- **Not an execution terminal**: It sends no orders to brokers. Real trade execution is always handled manually on your primary trading platform.

---

## 2. What the Tool Does Concretely (Module by Module)

### P04 — Key Structural Levels & Option Walls (GEX)
- **What it displays**: The reference synthetic NQ spot price, overnight and prior session high/low pivots, and primary option structural levels (Call Wall and Put Wall) derived from the NDX index.
- **Why it matters**: Market makers hedging option exposure create structural supply and demand zones. Large option open-interest walls frequently act as statistical magnets or resistance pivots. The module automatically converts underlying NDX index values into actionable NQ points.

### P05 — Macroeconomic Event Radar
- **What it displays**: A structured calendar of high-impact US economic releases (CPI, NFP, FOMC rate decisions, PCE, GDP) paired with an active countdown timer.
- **Why it matters**: Major macroeconomic prints often trigger violent 50-to-150 point volatility spikes within seconds. The radar highlights these events well in advance to prevent traders from getting caught in erratic slippage.

### P06 — Event Playbook & Stand-Aside Rules
- **What it displays**: Non-negotiable mandatory stand-aside protocols (*No-Trade* flags) around high-impact releases.
- **Why it matters**: The system mandates stepping away 5 minutes before and 3 minutes after any Tier 1 event, with an extended 90-minute cooldown protocol following regime-altering announcements (e.g., FOMC rate releases).

### P07 — Volatility Regimes & Expected Move
- **What it displays**: The options-implied daily expected move in NQ points, the percentage of that expected range already consumed during overnight Globex trading, and the prevailing volatility regime (Positive vs. Negative Gamma).
- **Why it matters**: If 80% of the daily expected range has already expanded prior to 15:30 (Wall Street cash open), the probability of continued runaway expansion is statistically low. Recognizing whether gamma is positive (mean-reverting conditions) or negative (accelerating momentum) informs optimal trade selection.

### P08 — Consolidated Session Day Profile
- **What it displays**: A single unified snapshot 15 minutes prior to the US cash open.
- **Why it matters**: It aggregates all risk parameters, gamma regimes, and calendar events into a 5-second visual decision: either a green banner ("Trading Allowed") or a red banner ("No-Trade Flag Active"). The trader knows immediately whether capital risk is justified.

### P09 — Discipline Rules & Risk Sizing
- **What it displays**: A strict position sizing calculator paired with a mandatory pre-trade discipline checklist.
- **Why it matters**: It eliminates emotional math under pressure. It computes the exact allowable contract size (NQ or MNQ) based on account equity and stop loss distance, automatically rounding down (`Math.floor`). It requires a written trade plan and checklist verification before issuing a "GO" verdict.

### P10 — Trading Journal (Log)
- **What it displays**: A detailed 16-variable trade entry interface (entry, stop, target, exit, commissions, emotion, plan adherence) and a searchable historical trade log.
- **Why it matters**: It automatically calculates net R-Multiple payoffs and archives execution notes to maintain objective, unvarnished discipline records.

### P11 — Algorithmic Coaching & Analytics
- **What it displays**: Systematic detection of behavioral capital leaks (overtrading, revenge trading, moving stop losses) alongside interactive visual analytics (equity curves, payoff distributions, win rates by session hour).
- **Why it matters**: Traders struggle with subjective memory. The algorithm highlights what generates edge versus what destroys capital without emotional bias.

### P12 — Pre-Market Briefing & Alerts
- **What it displays**: A consolidated pre-session written report summarizing the trading day.
- **Why it matters**: Generates a structured Markdown report in one click, with optional Google Gemini AI executive summaries and optional private Telegram channel dispatch.

### P13 — Unified Dark UI (Streamlit)
- **What it displays**: A clean, modern Slate-950 dark theme dashboard organized across 5 intuitive navigation pages.
- **Why it matters**: Includes dual live clocks (Algiers / New York) without eye strain, ensuring clean visual ergonomics during intensive market hours.

### P14 — Network Hardening & Algeria Resilience
- **What it does**: Robust technical architecture engineered to operate reliably from Algeria using 100% free data feeds (Yahoo Finance, CBOE, FRED, BLS).
- **Why it matters**: If a remote site blocks or times out, the system automatically falls back to secondary feeds and displays a visible `DEGRADED` badge rather than fabricating inaccurate data.

### P15 — MetaTrader 5 Gateway (Read-Only)
- **What it displays**: Automated ingestion of closed trade executions and real-time account balances directly from local MT5 terminals.
- **Why it matters**: Eliminates tedious manual trade entry. The module is strictly **read-only**: no order execution or order routing functions exist in the codebase, guaranteeing account security.

### P16 — Native Desktop Application
- **What it does**: Packages the application into a standalone Windows executable (`NQCockpit.exe`) with a dedicated desktop window and custom icon.
- **Why it matters**: Eliminates browser clutter. The underlying server binds strictly to the local loopback interface (`127.0.0.1`), preventing any exposure on local or external networks.

### P17 — Mega-Cap Tech Earnings Radar
- **What it displays**: Reporting schedules for the 8 dominant tech heavyweights (Nvidia, Apple, Microsoft, Amazon, Alphabet, Meta, Broadcom, Tesla).
- **Why it matters**: These 8 companies account for over 50% of the Nasdaq 100 weighting. Earnings releases before market open (BMO) or after market close (AMC) can trigger massive index gap moves.

---

## 3. Why It Differs from an Execution Terminal

THE COCKPIT is intentionally not designed to replace **NinjaTrader**, **TradingView**, or your standard execution platform:

1. **Zero duplication of intraday price charts**: THE COCKPIT does not display market depth ladders (DOM), tick footprints, delta charts, or moving averages. NinjaTrader handles intraday execution exceptionally well.
2. **A clear operational divide**: NinjaTrader is used to **execute the trade** (click buy, place bracket orders, manage stops). THE COCKPIT is used to **decide whether you are permitted to trade** and identifies the broader statistical environment.
3. **Unique Core Value**:
   - Macroeconomic and event-risk awareness.
   - Institutional options mechanics and gamma pivot walls.
   - A rigid discipline gate that prevents impulsive overtrading.

---

## 4. What Can Be Customized Without Code Changes

The following parameters can be customized directly by the owner by editing standard text configuration files, requiring zero programming skills:

### Inside `config.yaml`

- **Your Authorized Trading Windows (Algiers Kill Zones)**:
  ```yaml
  trading_windows_algiers:
    - {name: trade1, start: "15:30", end: "17:00"}
    - {name: trade2, start: "17:00", end: "18:30"}
  ```
  *You can adjust start/end times or add custom session windows to match your schedule.*

- **Discipline Rules and Daily Drawdown Caps**:
  ```yaml
  rules:
    max_trades_per_day: 2               # Maximum trades allowed per day
    cancel_trade2_if_trade1_loss: true  # Lock trade 2 if trade 1 closes negative
    cooldown_after_sl_minutes: 15       # Mandatory cooldown after stop loss hit
    daily_loss_limit_r: 2.0             # Daily maximum loss threshold in R-multiples
  ```

- **Tilt Prevention Parameters**:
  ```yaml
  rules:
    tilt:
      vengeance_minutes: 30             # Timeframe to detect revenge trade attempts
      size_multiplier_threshold: 1.5     # Threshold detecting abnormal position sizing
      frequency_max_trades: 3           # Alert if execution count exceeds limit
      frequency_window_minutes: 45
  ```

- **Account Capital & Default Contract**:
  ```yaml
  risk:
    instrument: MNQ                     # Default to MNQ ($2/pt) or NQ ($20/pt)
    risk_per_trade_pct: 0.5             # Percentage risked per trade (e.g. 0.5% or 1.0%)
    account_size: 50000                 # Total account equity in USD
  ```

- **Event Stand-Aside Buffers**:
  ```yaml
  events:
    stand_aside_before_minutes: 5       # Pre-event stand-aside buffer (minutes)
    wait_after_minutes: 3               # Post-event stand-aside buffer (minutes)
    post_event_buffer_minutes: 90       # Extended volatility buffer for major releases
  ```

- **Tracked Mega-Cap Tickers (P17)**:
  ```yaml
  events:
    megacaps: [NVDA, MSFT, AAPL, AMZN, GOOGL, META, AVGO, TSLA]
  ```

### Inside the Secret `.env` File

- Google Gemini API Key (`GEMINI_API_KEY`) for AI briefing synthesis.
- Telegram credentials (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) for mobile alerts.
- MT5 credentials (`MT5_LOGIN`, `MT5_SERVER`, `MT5_PATH`) if connecting custom accounts.

---

## 5. What Cannot Be Customized Without Code Development

The following changes **cannot be achieved via configuration files** and require a dedicated development cycle:

1. **Adding non-Nasdaq assets (e.g., Gold GC, Crude Oil CL, S&P 500 ES, Euro 6E)**:
   The options scrapers, CBOE parsers, price conversions, and gamma engines are engineered specifically for NDX/NQ.
2. **Modifying GEX or Gamma Flip mathematical algorithms**:
   These calculations are built directly into core Python libraries (`src/nqcockpit/levels/`).
3. **Connecting direct broker order execution (Interactive Brokers, Tradovate, Rithmic)**:
   The application intentionally contains no order routing architecture for safety.
4. **Altering visual layout structure or creating new core navigation pages**:
   UI templates and page routers are programmed in `src/nqcockpit/ui/`.
5. **Connecting paid commercial options feeds (e.g., SpotGamma, MenthorQ, Volland)**:
   The software is strictly designed to operate on free, resilient public endpoints.

---

## 6. Pending Development Roadmap

The following modules have been validated conceptually and remain queued for future iterations:

1. **Direct-Scraped CME FedWatch Barometer**:
   Real-time Federal Reserve rate decision probabilities scraped directly from public CME endpoints without requiring paid subscriptions.
2. **Institutional Sentiment & Positioning Panel**:
   Integrated dashboard tracking CBOE equity Put/Call ratios, AAII retail investor sentiment surveys, and the Fear & Greed index.
