# OKR 2026 — ISR Wolt Market 1P

Dashboard and validation pipeline for OKR 2026 metrics (Jan–Dec 2026 targets, Jan–Jun 2026 Snowflake actuals).

## Main deliverable

Open in a browser:

`auto_outputs/okr_2026_interactive_dashboard.html`

Tabs: **Main KPIs**, **KPI by Leader**, **Target (יעדים)**, **לבדיקה**.

Target overrides and manual actuals are saved in the browser (`localStorage`).

## Rebuild

```powershell
cd "C:\Users\ShirelZipori\OneDrive - Wolt Enterprises Oy\Documents\ניתוחים\OKR 2026"
pip install -r requirements_snowflake.txt
python okr_2026_validation.py
python okr_2026_dashboard.py --skip-fetch
python build_okr_2026_interactive_dashboard.py --skip-fetch
```

Use `--skip-fetch` on the last two commands when reusing cached Snowflake data from `auto_outputs/okr_2026_validation.html`.

## Snowflake auth

Copy `snowflake_secrets.env` from Weekly Presentation (not committed) or use Okta via `~/.snowflake/connections.toml`.

## Key files

| File | Role |
|------|------|
| `okr_2026_validation.py` | Fetch Snowflake, validation HTML |
| `okr_2026_dashboard.py` | Static dashboard + review CSV |
| `build_okr_2026_interactive_dashboard.py` | Interactive HTML builder |
| `okr_2026_default_targets.py` | Monthly targets Jan–Dec 2026 |
| `okr_2026_metrics_registry.py` | Metric lists, owners, workflow |
| `okr_2026_user_metrics.csv` | Optional manual metric overrides |

Saved checkpoint: July 2026.
