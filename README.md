# OKR 2026 V0 — ISR Wolt Market 1P

Dashboard and validation pipeline for OKR 2026 metrics (Jan–Dec 2026 targets, Jan–Jun 2026 Snowflake actuals).

**Current version:** **V0** (tag `okr-2026-v0` · July 2026)

## Main deliverable
**Live dashboard (share this link):**

https://shirelzipori-droid.github.io/okr-2026/

Local file:

`auto_outputs/okr_2026_interactive_dashboard.html`

Tabs: **Main KPIs**, **KPI by Leader**, **Target (יעדים)**, **For review**, **TO DELETE**.

## Metric workflow (Review → Dashboard → Target)

1. **For review** — new metrics start here with a dedicated review screen (card/table + Snowflake vs Looker + source note).
2. **Main KPIs** — only after you promote a metric from For review (e.g. “Use in dashboard”).
3. **Target** — when a metric is on Main KPIs, it must also appear on the Target tab with monthly goals (`okr_2026_default_targets.py`).

See `.cursor/rules/okr-review-promotion-workflow.mdc` for the full checklist.

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

After rebuild, **commit and push to GitHub** so https://shirelzipori-droid.github.io/okr-2026/ updates (allow 1–2 min, then hard refresh).

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

## Versions

| Version | Tag | Notes |
|---------|-----|-------|
| **V0** | `okr-2026-v0` | First stable checkpoint: interactive dashboard, weekly drill-down, PIN-protected Target editing, Jan–Jun 2026 actuals |