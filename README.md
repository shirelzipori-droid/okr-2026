# OKR 2026 — ISR Wolt Market 1P

Dashboard and validation pipeline for OKR 2026 metrics (Jan–Dec 2026 targets, Jan–Jun 2026 Snowflake actuals).

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
| `okr_2026_versions.py` | Internal snapshot codes (V0, V1, …) — not shown in dashboard |
| `restore_okr_version.py` | Restore a snapshot by code |

## Internal snapshots (not shown in dashboard)

Use short codes to save or restore a known state. The live dashboard always shows **OKR 2026** only.

| Code | Git tag | Saved |
|------|---------|-------|
| **V0** | `okr-2026-v0` | 2026-07-16 — first stable checkpoint |
| **V1** | `okr-2026-v1` | 2026-07-19 — yearly single-cell metrics + DC; before Yearly Target UI labels |
| **V2** | `okr-2026-v2` | 2026-07-19 — **latest** — Yearly Target for all KPIs, Cumulative Gap header |

**List snapshots:**

```powershell
python restore_okr_version.py --list
```

**Restore a snapshot (latest = V2):**

```powershell
python restore_okr_version.py V2
git checkout main   # back to latest when done
```

Or tell Cursor: *"חזור ל-V2"* — it will use tag `okr-2026-v2`.

When saving a new checkpoint, add an entry to `okr_2026_versions.py` and create a git tag (e.g. `okr-2026-v1`).
