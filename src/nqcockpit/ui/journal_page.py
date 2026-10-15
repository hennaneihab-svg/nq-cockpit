"""Page Streamlit P09 — Journal de bord et métriques de performance.

Design System Bloomberg x TradingView :
- Thème Slate #131722, bordures 1px #2A2E39, accents marque #FA7900
- Nombres et résultats au format tabulaire
- Statut "échantillon insuffisant" visible et non masqué
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.errors import StreamlitAPIException

from nqcockpit.broker.mt5_client import MT5Client
from nqcockpit.config import load_config
from nqcockpit.env import get_mt5_credentials, save_mt5_credentials
from nqcockpit.journal.engine import (
    compute_daily_stats,
    compute_performance_stats,
    finalize_trade,
    generate_coaching_report,
    segment_performance,
)
from nqcockpit.journal.importer import import_trades_from_csv
from nqcockpit.journal.models import (
    GammaRegime,
    TradeDirection,
    TradeEntry,
    VolRegime,
)
from nqcockpit.journal.store import delete_trade, load_trades, save_trade
from nqcockpit.ui.components import render_terminal_metric
from nqcockpit.ui.db import get_ui_db
from nqcockpit.ui.i18n import t, tr_text


@st.cache_resource
def _get_config():
    return load_config()


def render_journal_page() -> None:
    """Rendu complet du Journal de bord."""
    try:
        st.set_page_config(
            page_title=t("NQ Cockpit · Journal", "NQ Cockpit · Trade Journal"),
            layout="wide",
        )
    except StreamlitAPIException:
        pass

    # CSS Swetrix
    st.markdown("""
    <style>
    .stApp {
        background-color: #020617;
        color: #F8FAFC;
        font-family: -apple-system, system-ui, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .stDataFrame, .stTable {
        background-color: #0F172A;
        border: 1px solid rgba(51, 65, 85, 0.6);
        border-radius: 8px;
    }
    .insuf {
        color: #94A3B8;
        font-style: italic;
        font-family: ui-monospace, monospace;
    }
    .section-header {
        font-family: -apple-system, system-ui, sans-serif;
        color: #F8FAFC;
        font-size: 1.05rem;
        font-weight: 600;
        letter-spacing: -0.01em;
        margin-bottom: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    config = _get_config()
    tz_market = ZoneInfo(config.timezones.market)
    db_path = Path(config.data.db_path)
    conn = get_ui_db(str(db_path))

    MIN_TRADES = config.validation.min_sessions

    # ---------------------------------------------------------------------------
    # Navigation interne du Journal (Onglets horizontaux)
    # ---------------------------------------------------------------------------

    hdr_sec = t("JOURNAL DE BORD // SECTIONS", "TRADE JOURNAL // SECTIONS")
    st.markdown(
        f'<div class="section-header">{hdr_sec}</div>',
        unsafe_allow_html=True,
    )
    sub_tabs = [
        t("Enregistrer un trade", "Record a Trade"),
        t("Import MT5 & CSV", "MT5 & CSV Import"),
        t("Journal du jour", "Daily Journal"),
        t("Performance globale", "Global Performance"),
        t("Coaching", "Coaching"),
    ]
    page_idx = st.radio(
        t("Section Journal", "Journal Section"),
        options=list(range(len(sub_tabs))),
        format_func=lambda idx: sub_tabs[idx],
        index=0,
        horizontal=True,
        label_visibility="collapsed",
    )

    # ---------------------------------------------------------------------------
    # Page 1 — Enregistrer un trade
    # ---------------------------------------------------------------------------

    if page_idx == 0:
        hdr_new = t("SAISIE D'UN NOUVEAU TRADE", "RECORD A NEW TRADE")
        st.markdown(
            f'<div class="section-header">{hdr_new}</div>',
            unsafe_allow_html=True,
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            session_date = st.date_input(
                t("Date séance (NY)", "Session Date (NY)"),
                value=datetime.now(tz_market).date(),
            )
            instrument = st.selectbox(
                t("Instrument", "Instrument"), ["MNQ", "NQ"], index=0
            )
            direction = st.selectbox(
                t("Direction", "Direction"), ["LONG", "SHORT", "NONE"], index=0
            )
            window_name = st.selectbox(
                t("Fenêtre", "Window"),
                ["trade1", "trade2", ""] + [
                    w.name
                    for w in config.trading_windows_algiers
                    if w.name not in ("trade1", "trade2")
                ],
                index=0,
            )

        with col2:
            entry_price = st.number_input(
                t("Prix d'entrée", "Entry Price"),
                value=0.0,
                step=0.25,
                format="%.2f",
            )
            stop_price = st.number_input(
                t("Stop Loss (initial)", "Stop Loss (initial)"),
                value=0.0,
                step=0.25,
                format="%.2f",
            )
            tp1_price = st.number_input(
                t("TP1 (optionnel)", "TP1 (optional)"),
                value=0.0,
                step=0.25,
                format="%.2f",
            )
            exit_price = st.number_input(
                t("Prix de sortie", "Exit Price"),
                value=0.0,
                step=0.25,
                format="%.2f",
            )
            exit_reasons_raw = ["SL", "TP1", "TP2", "Manuel", "Temps"]
            exit_reasons_disp = {
                "SL": "SL",
                "TP1": "TP1",
                "TP2": "TP2",
                "Manuel": t("Manuel", "Manual"),
                "Temps": t("Temps", "Time"),
            }
            exit_reason = st.selectbox(
                t("Raison sortie", "Exit Reason"),
                options=exit_reasons_raw,
                format_func=lambda r: exit_reasons_disp.get(r, r),
            )

        with col3:
            fees_points = st.number_input(
                t("Frais (points NQ)", "Fees (NQ points)"),
                value=0.0,
                step=0.01,
                format="%.2f",
            )
            sl_moved = st.checkbox(
                t("SL déplacé après entrée", "SL moved after entry")
            )
            early_exit = st.checkbox(t("Sortie anticipée", "Early exit"))
            risk_pct_used = st.number_input(
                t("Risque utilisé (%)", "Risk used (%)"),
                value=0.5,
                step=0.1,
                format="%.2f",
            )
            minutes_after_last_sl = st.number_input(
                t("Minutes après dernier SL", "Minutes after last SL"),
                value=0.0,
                step=1.0,
                format="%.0f",
            )

        st.divider()
        col4, col5 = st.columns(2)
        with col4:
            setup_tag = st.text_input(
                t(
                    "Tag setup (ex. ICT_BOS, FVG, VWAP_rejet)",
                    "Setup tag (e.g. ICT_BOS, FVG, VWAP_reject)",
                )
            )
            gamma_regime = st.selectbox(
                t("Régime gamma", "Gamma Regime"),
                [r.value for r in GammaRegime],
                index=2,
            )
            vol_regime = st.selectbox(
                t("Régime volatilité", "Volatility Regime"),
                [r.value for r in VolRegime],
                index=2,
            )

        with col5:
            event_risk_label = st.text_input(
                t(
                    "Contexte événement (ex. 'CPI Tier1 dans 2h')",
                    "Event context (e.g. 'CPI Tier1 in 2h')",
                )
            )
            notes = st.text_area(t("Notes", "Notes"), height=80)
            screenshot_path = st.text_input(
                t("Chemin capture (optionnel)", "Screenshot path (optional)")
            )

        if st.button(
            t("Enregistrer le trade", "Save Trade"), type="primary"
        ):
            if entry_price == 0 or stop_price == 0 or exit_price == 0:
                st.error(
                    t(
                        "[ERREUR] Prix d'entrée, stop et sortie obligatoires.",
                        "[ERROR] Entry, stop, and exit prices are required.",
                    )
                )
            elif abs(entry_price - stop_price) < 0.01:
                st.error(
                    t(
                        "[ERREUR] Entrée et Stop identiques — risque initial nul.",
                        "[ERROR] Identical Entry and Stop — zero initial risk.",
                    )
                )
            else:
                last_sl_mins = (
                    minutes_after_last_sl if minutes_after_last_sl > 0 else None
                )
                trade = TradeEntry(
                    trade_id=str(uuid.uuid4()),
                    recorded_at=datetime.now(timezone.utc),
                    session_date=str(session_date),
                    instrument=instrument,
                    direction=TradeDirection(direction),
                    entry_price=entry_price,
                    stop_price=stop_price,
                    tp1_price=tp1_price if tp1_price != 0 else None,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    fees_points=fees_points,
                    window_name=window_name,
                    minutes_after_last_sl=last_sl_mins,
                    event_risk_label=event_risk_label,
                    gamma_regime=GammaRegime(gamma_regime),
                    vol_regime=VolRegime(vol_regime),
                    day_of_week=session_date.weekday(),
                    sl_moved=sl_moved,
                    early_exit=early_exit,
                    risk_pct_used=risk_pct_used,
                    setup_tag=setup_tag,
                    notes=notes,
                    screenshot_path=screenshot_path,
                )
                trade = finalize_trade(trade)
                save_trade(conn, trade)

                r_str = f"{trade.r_realized:+.3f}R"
                st.success(
                    t(
                        f"[CONFIRMATION] Trade enregistré · "
                        f"R réalisé : **{r_str}** · Résultat : **{trade.outcome.value}**",
                        f"[CONFIRMED] Trade saved · "
                        f"Realized R: **{r_str}** · Outcome: **{trade.outcome.value}**",
                    )
                )
                st.rerun()

    # ---------------------------------------------------------------------------
    # Page 2 — Import MT5 & CSV
    # ---------------------------------------------------------------------------

    elif page_idx == 1:
        hdr_imp = t(
            "IMPORTATION AUTOMATIQUE (MT5) & FICHIERS CSV",
            "AUTOMATIC IMPORT (MT5) & CSV FILES",
        )
        st.markdown(
            f'<div class="section-header">{hdr_imp}</div>',
            unsafe_allow_html=True,
        )

        st.info(
            t(
                "Conformément à la règle R9, l'intégration MetaTrader 5 fonctionne **strictement "
                "en lecture seule** (aucun passage d'ordre). Les identifiants sont stockés "
                "exclusivement dans votre fichier local .env (hors Git).",
                "In accordance with Rule R9, MetaTrader 5 integration operates in **strictly "
                "read-only mode** (zero order execution). Credentials are stored "
                "exclusively in your local .env file (excluded from Git).",
            )
        )

        col_mt5, col_csv = st.columns([1, 1], gap="medium")

        with col_mt5:
            st.markdown(
                t(
                    "### 🔌 Passerelle MetaTrader 5 (MT5)",
                    "### 🔌 MetaTrader 5 (MT5) Gateway",
                )
            )

            client = MT5Client()
            status = client.get_status()

            if status.is_ok:
                srv_str = status.server or t("Serveur standard", "Standard server")
                st.success(
                    t(
                        f"**[STATUT MT5 · OK]** Connecté au compte "
                        f"{status.account_login} ({srv_str})",
                        f"**[MT5 STATUS · OK]** Connected to account "
                        f"{status.account_login} ({srv_str})",
                    )
                )
                acc = client.get_account_info()
                if acc:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        render_terminal_metric(
                            t("Solde", "Balance"),
                            f"{acc.balance:,.2f} {acc.currency}",
                        )
                    with c2:
                        render_terminal_metric(
                            t("Equity", "Equity"),
                            f"{acc.equity:,.2f} {acc.currency}",
                        )
                    with c3:
                        render_terminal_metric(
                            t("Mode", "Mode"), acc.trade_mode
                        )

                open_positions = client.get_open_positions()
                if open_positions:
                    st.markdown(
                        t(
                            f"**Positions en cours ({len(open_positions)})**",
                            f"**Open Positions ({len(open_positions)})**",
                        )
                    )
                    pos_rows = [
                        {
                            t("Ticket", "Ticket"): p.ticket,
                            t("Symbole", "Symbol"): p.symbol,
                            t("Sens", "Side"): p.direction.value,
                            t("Volume", "Volume"): p.volume,
                            t("Entrée", "Entry"): p.price_open,
                            t("Prix actuel", "Current Price"): p.price_current,
                            "PnL ($)": round(p.profit, 2),
                        }
                        for p in open_positions
                    ]
                    st.dataframe(pos_rows, use_container_width=True)
            else:
                st.warning(
                    t(
                        f"**[STATUT MT5 · DÉGRADÉ]** {status.reason}\n\n"
                        "_Le terminal MetaTrader 5 doit être installé et lancé "
                        "localement sur Windows._",
                        f"**[MT5 STATUS · DEGRADED]** {tr_text(status.reason)}\n\n"
                        "_The MetaTrader 5 terminal must be installed and running "
                        "locally on Windows._",
                    )
                )

            with st.expander(
                t(
                    "⚙️ Configuration des identifiants MT5 (.env)",
                    "⚙️ MT5 Credentials Configuration (.env)",
                ),
                expanded=not status.is_ok,
            ):
                st.caption(
                    t(
                        "Les identifiants sont écrits directement dans le fichier .env "
                        "sans modifier les autres variables.",
                        "Credentials are written directly to the .env file "
                        "without modifying other environment variables.",
                    )
                )
                creds = get_mt5_credentials()
                login_default = creds.get("login") or ""
                server_default = creds.get("server") or ""
                path_default = creds.get("path") or ""
                tz_default = creds.get("broker_tz") or "UTC"

                cfg_login = st.text_input(
                    t("Numéro de compte (Login)", "Account Number (Login)"),
                    value=str(login_default) if login_default else "",
                )
                cfg_password = st.text_input(
                    t("Mot de passe (masqué)", "Password (masked)"),
                    type="password",
                    help=t(
                        "Stocké uniquement dans .env. Jamais loggé ni réaffiché en clair.",
                        "Stored only in .env. Never logged or displayed in plain text.",
                    ),
                )
                if creds.get("has_password"):
                    st.caption(
                        t(
                            "🔒 Un mot de passe est déjà enregistré dans .env. "
                            "Laissez ce champ vide pour le conserver.",
                            "🔒 A password is already saved in .env. "
                            "Leave this field blank to keep it.",
                        )
                    )

                cfg_server = st.text_input(
                    t(
                        "Serveur Broker (ex: ICMarketsSC-Demo)",
                        "Broker Server (e.g. ICMarketsSC-Demo)",
                    ),
                    value=server_default,
                )
                cfg_path = st.text_input(
                    t(
                        "Chemin terminal64.exe (optionnel si installation standard)",
                        "Path to terminal64.exe (optional for standard installation)",
                    ),
                    value=path_default,
                )
                cfg_tz = st.text_input(
                    t(
                        "Fuseau horaire serveur broker (zoneinfo, ex: UTC, Europe/Athens)",
                        "Broker server timezone (zoneinfo, e.g. UTC, Europe/Athens)",
                    ),
                    value=tz_default,
                )

                if st.button(
                    t(
                        "Enregistrer & Connecter MT5",
                        "Save & Connect MT5",
                    ),
                    type="primary",
                ):
                    if not cfg_login or not cfg_server:
                        st.error(
                            t(
                                "Le numéro de compte et le serveur broker sont obligatoires.",
                                "Account number and broker server are required.",
                            )
                        )
                    else:
                        saved = save_mt5_credentials(
                            login=cfg_login,
                            password=cfg_password,
                            server=cfg_server,
                            path=cfg_path,
                            broker_tz=cfg_tz,
                        )
                        if saved:
                            re_client = MT5Client()
                            re_status = re_client.connect()
                            if re_status.is_ok:
                                st.success(
                                    t(
                                        "Identifiants sauvegardés et connexion MT5 réussie !",
                                        "Credentials saved and MT5 connected successfully!",
                                    )
                                )
                            else:
                                st.warning(
                                    t(
                                        f"Identifiants enregistrés dans .env. "
                                        f"Statut MT5 : {re_status.reason}",
                                        f"Credentials saved in .env. "
                                        f"MT5 Status: {tr_text(re_status.reason)}",
                                    )
                                )
                            st.rerun()
                        else:
                            st.error(
                                t(
                                    "Échec d'écriture dans le fichier .env.",
                                    "Failed to write to .env file.",
                                )
                            )

            st.markdown(
                t(
                    "#### 📥 Importer les trades fermés",
                    "#### 📥 Import Closed Trades",
                )
            )
            period_opts_lbl = [
                t("Aujourd'hui", "Today"),
                t("Derniers 7 jours", "Last 7 days"),
                t("Derniers 30 jours", "Last 30 days"),
                t("Tout l'historique", "Full history"),
            ]
            period_idx = st.selectbox(
                t("Période d'historique", "History Period"),
                options=[0, 1, 2, 3],
                format_func=lambda idx: period_opts_lbl[idx],
                index=1,
            )
            symbol_filter = st.text_input(
                t(
                    "Filtrer par symbole (ex: NQ, NAS100, laisser vide pour tout)",
                    "Filter by symbol (e.g. NQ, NAS100, leave blank for all)",
                ),
                value="",
            )

            now_utc = datetime.now(timezone.utc)
            if period_idx == 0:
                d_from = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            elif period_idx == 1:
                d_from = now_utc - timedelta(days=7)
            elif period_idx == 2:
                d_from = now_utc - timedelta(days=30)
            else:
                d_from = None

            if st.button(
                t("Importer depuis MT5", "Import from MT5"),
                disabled=not status.is_ok,
            ):
                with st.spinner(
                    t(
                        "Récupération des deals et consolidation en cours...",
                        "Fetching deals and consolidating positions...",
                    )
                ):
                    import_res = client.import_trades_to_journal(
                        conn=conn,
                        date_from=d_from,
                        symbol=symbol_filter if symbol_filter.strip() else None,
                        config=config,
                    )
                if import_res.is_success:
                    st.success(
                        t(
                            f"**Succès !** {import_res.imported} trade(s) importé(s), "
                            f"{import_res.duplicates} doublon(s) ignoré(s) sur "
                            f"{import_res.total_positions} position(s) fermée(s).",
                            f"**Success!** {import_res.imported} trade(s) imported, "
                            f"{import_res.duplicates} duplicate(s) skipped out of "
                            f"{import_res.total_positions} closed position(s).",
                        )
                    )
                    st.rerun()
                else:
                    st.error(
                        t(
                            f"Erreur d'import : {', '.join(import_res.errors)}",
                            f"Import error: {', '.join(import_res.errors)}",
                        )
                    )

        with col_csv:
            st.markdown(
                t(
                    "### 📄 Importation alternative CSV (P10)",
                    "### 📄 Alternative CSV Import (P10)",
                )
            )
            st.caption(
                t(
                    "Vous pouvez importer des trades depuis un fichier CSV exporté "
                    "de votre plateforme de trading ou de Notion.",
                    "You can import trades from a CSV file exported "
                    "from your trading platform or Notion.",
                )
            )

            uploaded_file = st.file_uploader(
                t(
                    "Déposer un fichier CSV de trades",
                    "Upload a trades CSV file",
                ),
                type=["csv"],
                help=t(
                    "Colonnes requises: session_date, instrument, direction, prix...",
                    "Required columns: session_date, instrument, direction, prices...",
                ),
            )

            if uploaded_file is not None:
                if st.button(
                    t(
                        "Lancer l'importation du fichier CSV",
                        "Run CSV File Import",
                    )
                ):
                    try:
                        content = uploaded_file.getvalue().decode("utf-8-sig")
                        csv_stream = io.StringIO(content)
                        csv_summary = import_trades_from_csv(csv_stream, conn, config)

                        if csv_summary.is_success:
                            msg_ok = t(
                                f"**Import CSV terminé !** {csv_summary.imported} trade(s), "
                                f"{csv_summary.duplicates} doublon(s), "
                                f"{csv_summary.rejected} rejeté(s) / {csv_summary.total_rows}.",
                                f"**CSV Import complete!** {csv_summary.imported} trade(s), "
                                f"{csv_summary.duplicates} duplicate(s), "
                                f"{csv_summary.rejected} rejected / {csv_summary.total_rows}.",
                            )
                            st.success(msg_ok)
                            if csv_summary.warnings:
                                with st.expander(
                                    t("Avertissements CSV", "CSV Warnings")
                                ):
                                    for w in csv_summary.warnings:
                                        st.write(f"- {tr_text(w)}")
                            st.rerun()
                        else:
                            st.error(
                                t(
                                    f"Erreurs d'import CSV : {', '.join(csv_summary.errors)}",
                                    f"CSV import errors: {', '.join(csv_summary.errors)}",
                                )
                            )
                    except Exception as exc:
                        st.error(
                            t(
                                f"Erreur lors de la lecture du fichier : {exc}",
                                f"Error reading file: {exc}",
                            )
                        )

    # ---------------------------------------------------------------------------
    # Page 3 — Journal du jour
    # ---------------------------------------------------------------------------

    elif page_idx == 2:
        hdr_daily = t("JOURNAL DE SÉANCE DÉTAILLÉ", "DETAILED SESSION JOURNAL")
        st.markdown(
            f'<div class="section-header">{hdr_daily}</div>',
            unsafe_allow_html=True,
        )

        today_ny = datetime.now(tz_market).date()
        selected_date = st.date_input(
            t("Date séance", "Session Date"), value=today_ny
        )
        session_str = str(selected_date)

        trades = load_trades(conn, session_date=session_str)

        if not trades:
            st.info(
                t(
                    "Aucun trade enregistré pour cette date.",
                    "No trades recorded for this date.",
                )
            )
        else:
            stats = compute_daily_stats(session_str, trades, config)

            # KPI cards
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                render_terminal_metric(
                    t("Trades", "Trades"), str(stats.n_trades)
                )
            with c2:
                render_terminal_metric(
                    t("Wins / Losses", "Wins / Losses"),
                    f"{stats.n_wins} / {stats.n_losses}",
                )
            with c3:
                r_kind = "pos" if stats.r_total >= 0 else "neg"
                render_terminal_metric(
                    t("R total", "Total R"),
                    f"{stats.r_total:+.3f}R",
                    status_kind=r_kind,
                )
            with c4:
                render_terminal_metric(
                    t("Conformité", "Compliance"),
                    f"{stats.compliance_rate:.0%}",
                )

            if stats.limit_hit:
                limit_r = config.rules.daily_loss_limit_r
                st.error(
                    t(
                        f"[VERROU] LIMITE JOURNALIÈRE ATTEINTE — "
                        f"{stats.r_total:+.3f}R (limite : -{limit_r}R)",
                        f"[LOCK] DAILY LOSS LIMIT REACHED — "
                        f"{stats.r_total:+.3f}R (limit: -{limit_r}R)",
                    )
                )

            # Tableau des trades
            st.markdown(t("#### Liste des Trades", "#### Trade List"))
            rows = []
            for tr in sorted(trades, key=lambda x: x.recorded_at):
                rows.append({
                    "ID": tr.trade_id[:8],
                    t("Direction", "Direction"): tr.direction.value,
                    t("Entrée", "Entry"): tr.entry_price,
                    "Stop": tr.stop_price,
                    t("Sortie", "Exit"): tr.exit_price,
                    t("R réalisé", "Realized R"): f"{tr.r_realized:+.3f}",
                    t("Résultat", "Outcome"): tr.outcome.value,
                    t("Fenêtre", "Window"): tr.window_name,
                    "Setup": tr.setup_tag,
                })

            st.dataframe(rows, use_container_width=True)

            # Captures d'écran associées
            screenshot_trades = [
                tr for tr in trades if tr.screenshot_path and tr.screenshot_path.strip()
            ]
            if screenshot_trades:
                st.markdown(
                    t(
                        "#### Captures d'écran associées",
                        "#### Attached Screenshots",
                    )
                )
                for tr in screenshot_trades:
                    p_img = Path(tr.screenshot_path)
                    st.write(
                        f"**Trade `{tr.trade_id[:8]}`** "
                        f"({tr.direction.value} @ {tr.entry_price:.2f}) :"
                    )
                    if p_img.is_file():
                        st.image(
                            str(p_img),
                            caption=(
                                f"Screenshot Trade {tr.trade_id[:8]} — "
                                f"{tr.setup_tag or 'Setup'}"
                            ),
                        )
                    else:
                        st.warning(
                            t(
                                f"[AVERTISSEMENT] Image introuvable : `{tr.screenshot_path}`",
                                f"[WARNING] Image not found: `{tr.screenshot_path}`",
                            )
                        )

            # Violations
            if stats.violations:
                st.markdown(
                    t(
                        f"#### Violations de Règles ({len(stats.violations)})",
                        f"#### Rule Violations ({len(stats.violations)})",
                    )
                )
                for v in stats.violations:
                    st.warning(f"**[{v.violation.value}]** {tr_text(v.detail)}")

            # Tilt alerts
            if stats.tilt_alerts:
                st.markdown(
                    t(
                        f"#### Alertes de Tilt ({len(stats.tilt_alerts)})",
                        f"#### Tilt Alerts ({len(stats.tilt_alerts)})",
                    )
                )
                for a in stats.tilt_alerts:
                    st.error(f"**[TILT]** {tr_text(a.reason)}")

            # Suppression
            st.markdown(t("#### Supprimer un trade", "#### Delete a Trade"))
            trade_ids = [tr.trade_id for tr in trades]
            to_delete = st.selectbox(
                t("Trade ID à supprimer", "Trade ID to delete"),
                ["—"] + trade_ids,
            )
            if to_delete != "—" and st.button(
                t(
                    "Supprimer le trade sélectionné",
                    "Delete Selected Trade",
                )
            ):
                n = delete_trade(conn, to_delete)
                if n:
                    st.success(
                        t(
                            f"Trade {to_delete[:8]}… supprimé.",
                            f"Trade {to_delete[:8]}… deleted.",
                        )
                    )
                    st.rerun()

    # ---------------------------------------------------------------------------
    # Page 4 — Performance globale
    # ---------------------------------------------------------------------------

    elif page_idx == 3:
        hdr_perf = t(
            "PERFORMANCE GLOBALE AGREGÉE",
            "AGGREGATED GLOBAL PERFORMANCE",
        )
        st.markdown(
            f'<div class="section-header">{hdr_perf}</div>',
            unsafe_allow_html=True,
        )

        all_trades = load_trades(conn)
        if not all_trades:
            st.info(
                t(
                    "Aucun trade enregistré dans le journal.",
                    "No trades recorded in the journal.",
                )
            )
        else:
            stats = compute_performance_stats(all_trades, min_trades=MIN_TRADES)
            computed_str = (
                stats.computed_at.strftime("%Y-%m-%d %H:%M UTC")
                if stats.computed_at else "—"
            )
            st.caption(
                t(
                    f"Calculé à {computed_str} · n = {stats.n_trades} trades",
                    f"Computed at {computed_str} · n = {stats.n_trades} trades",
                )
            )

            if not stats.sample_sufficient:
                msg = t(
                    f'<p class="insuf">[STATUT ÉCHANTILLON] Échantillon insuffisant : '
                    f'{stats.n_trades}/{MIN_TRADES} trades. '
                    "Les statistiques avancées ne sont pas encore calculées.</p>",
                    f'<p class="insuf">[SAMPLE STATUS] Insufficient sample: '
                    f'{stats.n_trades}/{MIN_TRADES} trades. '
                    "Advanced statistics are not yet computed.</p>",
                )
                st.markdown(msg, unsafe_allow_html=True)

            # Métriques de base (disponibles même sans seuil)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                render_terminal_metric(
                    t("Trades totaux", "Total Trades"), str(stats.n_trades)
                )
            with c2:
                wr_str = f"{stats.win_rate:.1%}" if stats.win_rate is not None else "—"
                render_terminal_metric("Win Rate", wr_str)
            with c3:
                compl_val = f"{stats.compliance_rate:.0%}" if stats.compliance_rate else "—"
                render_terminal_metric(
                    t("Conformité", "Compliance"), compl_val
                )
            with c4:
                streak_val = str(stats.max_loss_streak) if stats.sample_sufficient else "—"
                render_terminal_metric("Max Loss Streak", streak_val)

            if stats.sample_sufficient:
                st.divider()
                c5, c6, c7, c8 = st.columns(4)
                with c5:
                    exp_r_val = stats.expectancy_r
                    exp_r_str = f"{exp_r_val:+.3f}R" if exp_r_val is not None else "—"
                    exp_kind = "pos" if exp_r_val and exp_r_val >= 0 else "neg"
                    render_terminal_metric(
                        t("Espérance (R)", "Expectancy (R)"),
                        exp_r_str,
                        status_kind=exp_kind,
                    )
                with c6:
                    pf_val = f"{stats.profit_factor:.2f}" if stats.profit_factor else "—"
                    render_terminal_metric("Profit Factor", pf_val)
                with c7:
                    dd_str = f"-{stats.max_drawdown_r:.3f}R"
                    render_terminal_metric("Max DD (R)", dd_str, status_kind="neg")
                with c8:
                    exp_c_val = stats.expectancy_r_compliant
                    exp_c_str = (
                        f"{exp_c_val:+.3f}R"
                        if exp_c_val is not None
                        else t("insuffisant", "insufficient")
                    )
                    render_terminal_metric(
                        t("Espérance Conformes", "Compliant Expectancy"),
                        exp_c_str,
                    )

            # Segmentation
            st.divider()
            st.markdown(
                t(
                    "#### Performance par Segment",
                    "#### Performance by Segment",
                )
            )
            seg_by = st.selectbox(
                t("Segmenter par", "Segment by"),
                ["setup_tag", "gamma_regime", "vol_regime", "day_of_week", "event_risk"],
            )
            seg = segment_performance(all_trades, by=seg_by)

            seg_rows = []
            for label, s in seg.items():
                suf = (
                    "OK" if s.sample_sufficient
                    else t(
                        f"INSUFFISANT ({s.n_trades}/{s.min_trades_required})",
                        f"INSUFFICIENT ({s.n_trades}/{s.min_trades_required})",
                    )
                )
                seg_rows.append({
                    t("Segment", "Segment"): tr_text(label),
                    "n": s.n_trades,
                    "Win Rate": f"{s.win_rate:.1%}" if s.win_rate is not None else "—",
                    t("Espérance (R)", "Expectancy (R)"): (
                        f"{s.expectancy_r:+.3f}" if s.expectancy_r is not None
                        else t("insuf.", "insuf.")
                    ),
                    "Profit Factor": f"{s.profit_factor:.2f}" if s.profit_factor else "—",
                    t("Échantillon", "Sample"): suf,
                })

            st.dataframe(seg_rows, use_container_width=True)

    # ---------------------------------------------------------------------------
    # Page 5 — Coaching
    # ---------------------------------------------------------------------------

    elif page_idx == 4:
        hdr_coach = t(
            "RAPPORT DE COACHING ET ANALYTICS",
            "COACHING REPORT & ANALYTICS",
        )
        st.markdown(
            f'<div class="section-header">{hdr_coach}</div>',
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns([1, 2])
        with col1:
            period_type = st.radio(
                t("Période", "Period"),
                options=["hebdo", "mensuel"],
                format_func=lambda p: (
                    t("hebdo", "weekly") if p == "hebdo" else t("mensuel", "monthly")
                ),
            )
            period_label = st.text_input(
                t(
                    "Label (ex. S39-2026, Oct-2026)",
                    "Label (e.g. W39-2026, Oct-2026)",
                ),
                value="S39-2026",
            )
            gen_btn = st.button(
                t("Générer le rapport", "Generate Report"), type="primary"
            )

        if gen_btn:
            all_trades = load_trades(conn)
            report = generate_coaching_report(
                all_trades,
                period=period_type,
                period_label=period_label,
                config=config,
            )

            if report.insufficient_data:
                st.warning(
                    t(
                        f"[DONNÉES INSUFFISANTES] {period_label} : "
                        f"{report.stats.n_trades if report.stats else 0}/{MIN_TRADES} trades. "
                        "Rapport partiel.",
                        f"[INSUFFICIENT DATA] {period_label}: "
                        f"{report.stats.n_trades if report.stats else 0}/{MIN_TRADES} trades. "
                        "Partial report.",
                    )
                )

            p_disp = (
                t("HEBDO", "WEEKLY")
                if period_type == "hebdo"
                else t("MENSUEL", "MONTHLY")
            )
            st.markdown(
                f"#### {t('Rapport', 'Report')} {p_disp} · {period_label}"
            )
            st.caption(
                t(
                    f"Généré à {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
                    f"Generated at {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
                )
            )

            # Top fuites
            st.markdown(
                t("#### Top 3 Fuites Chiffrées", "#### Top 3 Quantified Leaks")
            )
            for i, leak in enumerate(report.top_leaks, 1):
                st.markdown(f"**{i}.** {tr_text(leak)}")

            # Règle & force
            col3, col4 = st.columns(2)
            with col3:
                st.markdown(
                    t("#### Règle à Renforcer", "#### Rule to Reinforce")
                )
                st.info(tr_text(report.rule_to_reinforce) or "—")
            with col4:
                st.markdown(
                    t("#### Force à Conserver", "#### Strength to Keep")
                )
                st.success(tr_text(report.strength_to_keep) or "—")

            # Objectifs
            st.markdown(
                t("#### Objectifs Mesurables", "#### Measurable Goals")
            )
            for goal in report.measurable_goals:
                st.markdown(f"- {tr_text(goal)}")

            # Stats résumé
            if report.stats and report.stats.sample_sufficient:
                st.divider()
                st.markdown(
                    t(
                        "#### Statistiques de la Période",
                        "#### Period Statistics",
                    )
                )
                d = report.stats.to_dict()
                st.json(d)


if __name__ == "__main__":
    render_journal_page()
