# Rapport de livraison P09 — Journal de bord, discipline et métriques de performance

**Date** : 2026-09-30  
**Commit précédent (P08)** : `26cfdf3`

---

## Ce qui est livré

### Fichiers créés

| Fichier | Rôle |
|---------|------|
| `src/nqcockpit/journal/models.py` | `TradeEntry`, `DisciplineFlag`, `TiltAlert`, `DailyStats`, `PerformanceStats`, `CoachingReport` |
| `src/nqcockpit/journal/store.py` | SQLite CRUD (table `trades`) — requêtes paramétrées |
| `src/nqcockpit/journal/engine.py` | `finalize_trade`, `detect_violations` (7 types), `detect_tilt_alerts`, `compute_daily_stats`, `compute_performance_stats`, `segment_performance`, `generate_coaching_report`, `log_trade` |
| `src/nqcockpit/journal/__init__.py` | Exports publics |
| `src/nqcockpit/ui/journal_page.py` | Page Streamlit 4 sections (saisie, journal jour, stats globales, coaching) |
| `tests/test_p09_journal.py` | 26 tests pytest |
| `reports/p09_report.md` | Ce rapport |

### Fichiers modifiés

| Fichier | Ce qui change |
|---------|---------------|
| `src/nqcockpit/cli.py` | Sous-commande `journal` (stats, daily, coaching, ui) + `_handle_journal()` + suppression du doublon `ui` dans `main()` |

---

## Architecture

```
TradeEntry (models) ──► finalize_trade() ──► r_realized, outcome
       │
       ├──► save_trade() (store / SQLite)
       │
       ├──► detect_violations() ──► 7 DisciplineFlag typés avec cause explicite
       │        - OUT_OF_WINDOW
       │        - TRADE_LIMIT
       │        - TRADE2_AFTER_LOSS
       │        - QUICK_REENTRY
       │        - MOVED_SL
       │        - EARLY_EXIT
       │        - OVERSIZED
       │
       └──► compute_daily_stats() ──► DailyStats (R total, limit_hit, conformité)
                    │
                    └──► detect_tilt_alerts() ──► TiltAlert (2 pertes consécutives, rentrée rapide)

load_trades() ──► compute_performance_stats() ──► PerformanceStats
                         - Wilson IC 95% pour win rate
                         - IC normal 95% pour espérance (n >= min_trades)
                         - Drawdown max en R, série de pertes max
                         - Espérance conformes vs non-conformes

                 ──► segment_performance(by=...) ──► dict[str, PerformanceStats]
                         - setup_tag, gamma_regime, vol_regime, day_of_week, event_risk

                 ──► generate_coaching_report() ──► CoachingReport
                         - Top 3 fuites chiffrées (impact en R)
                         - Règle à renforcer (violation la plus fréquente)
                         - Force à conserver (compliance ou série de pertes)
                         - Objectifs mesurables
```

---

## Règles de discipline vérifiées

| Règle | Paramètre config | Violation détectée |
|-------|-----------------|-------------------|
| Hors fenêtre de trading | `trading_windows_algiers` | `OUT_OF_WINDOW` |
| > N trades/jour | `rules.max_trades_per_day` | `TRADE_LIMIT` |
| Trade2 après perte T1 | `rules.cancel_trade2_if_trade1_loss` | `TRADE2_AFTER_LOSS` |
| Rentrée < cooldown | `rules.cooldown_after_sl_minutes` | `QUICK_REENTRY` |
| SL déplacé | `trade.sl_moved` | `MOVED_SL` |
| Sortie anticipée | `trade.early_exit` | `EARLY_EXIT` |
| Surtaill | `risk.risk_per_trade_pct` | `OVERSIZED` |

---

## Tests

**26/26 tests passés — 0.40s**

| Groupe | Tests |
|--------|-------|
| T1 : finalize_trade | Long/Short WIN, LOSS, calcul R |
| T2 : store | Save/load, delete, multi-session |
| T3 : violations | 7 violations (cause explicite vérifiée) |
| T4 : tilt | 2 pertes consécutives |
| T5 : daily stats | limit_hit, compliance_rate |
| T6 : perf stats | Insuffisant, Wilson CI bornes, suffisant |
| T7 : segment | setup_tag, gamma_regime |
| T8 : coaching | Insuffisant, langue factuelle (interdits vérifiés), objectifs |
| T9 : CLI | Parse args journal stats/coaching |

---

## Statut de livraison

| Composant | Statut |
|-----------|--------|
| Store SQLite | ✅ OK |
| Calcul R | ✅ OK |
| Violations (7) | ✅ OK — cause explicite, jamais masquée |
| Tilt alerts | ✅ OK — signal seulement, ne bloque pas |
| Stats (Wilson IC) | ✅ OK — `sample_sufficient` garde |
| Segment | ✅ OK |
| Coaching | ✅ OK — factuel, langue neutre testée |
| UI Streamlit | ✅ OK — jamais masquer insuffisant |
| CLI | ✅ OK |
| Ruff | ✅ 0 erreur |
| Tests | ✅ 192/192 (166 P01-P08 + 26 P09) |

---

## Prochaine étape : P10

Module d'intégration finale — tableau de bord consolidé combinant P01–P09 en un flux opérationnel unique : briefing matinal automatisé, scheduler de snapshots, alertes push locales.
