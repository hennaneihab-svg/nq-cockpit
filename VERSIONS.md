# NQ Cockpit — version history for the partner review

Each line below is a separate, complete version of the app. They live in their
own git worktrees, so they can all run at the same time without interfering
with each other or with the normal cockpit on port 8501.

| Version tag | Port | Date | What is new (one line) | What to look at |
| --- | --- | --- | --- | --- |
| `v00-base` | 8510 | 2026-10-29 | The original cockpit before the TradingView work: Today page, journal, sources and basic levels. | The Today page and the sidebar navigation. |
| `v01-terminal-ui` | 8511 | 2026-10-31 | Navigation rewritten in plain language, single-screen terminal layout, plus a launcher and Today/briefing polish. | The top navigation bar and the compact Terminal screen. |
| `v02-tradingview` | 8512 | 2026-10-31 | TradingView arrives: advanced chart on the Terminal, a new Market Map page of quotes, and a settings fix that no longer exposes a key. | The Terminal chart and the new Market Map page. |
| `v03-symbols` | 8513 | 2026-10-31 | Chart height fixed, and symbols that did not display replaced by ones TradingView really renders. | Chart sizing and the symbol lists on the Market Map. |
| `v04-mt5-import` | 8514 | 2026-10-31 | Market Map quotes go full width, the journal tab becomes Coaching, and the MT5 import gets its first fix. | The Market Map layout and the Coaching tab. |
| `v05-coaching` | 8515 | 2026-10-31 | Coaching page rebuilt as a dark, data-driven performance report. | The charts and statistics on the Coaching page. |
| `v06-coaching-polish` | 8516 | 2026-10-31 | Coaching polish: marker toggles, regime tabs, a header badge, and clearer MT5 import feedback. | The toggles and regime tabs on Coaching. |
| `v07-mt5-all-assets` | 8517 | 2026-10-31 | MT5 import now takes all symbols and trades without an R value; tests are isolated from secrets and the network. | Importing a broker statement from the Coaching page. |
| `v08-r-recovery` | 8518 | 2026-10-31 | R is recovered from the entry order, including updating trades that previously had no R. | R values in the Coaching trades table. |
| `v09-sources` | 8519 | 2026-10-31 | New free, no-key RSS news sources, a ForexFactory cache, and a source-health panel showing what is working. | The source-health panel and the news wire. |
| `v10-source-fixes` | 8520 | 2026-11-01 | Source fixes: BLS user agent, MarketWatch in the news wire, localised health panel, and all four level pills. | The news wire and the four level pills. |
| `v11-alerter` | 8521 | 2026-11-01 | A standalone Telegram alerter with rules, deduplication and scheduled task scripts. | The alerts folder and task scripts (these versions never send a message). |
| `v12-alerter-fix` | 8522 | 2026-11-06 | Alerter fixes: English/French labels from status codes, real locks only, quiet-hour hardening, plus this versions guide. | The alerter status labels and this file. |

## How to open a version (4 lines)

1. Open all of them at once by double-clicking `scripts\run_all_versions.bat` (one minimised window per version).
2. Or open a single one with `scripts\run_version.bat v05-coaching`; run it with no argument to see the tag list and ports.
3. Each version listens on port 8510 plus its number, and the normal app on port 8501 is never touched.
4. Stop them all with `scripts\stop_versions.bat`, which only stops ports 8510-8529.
