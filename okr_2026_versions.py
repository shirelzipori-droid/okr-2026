"""Internal OKR 2026 snapshot codes — not shown in the live dashboard.

When you ask to restore a version (e.g. "חזור ל-V0"), use the git tag below.
Add a new entry here whenever we save a new checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OkrSnapshot:
    code: str
    tag: str
    date: str
    notes: str


# Code → git tag. Say the code (V0, V1, …) to restore that snapshot.
SNAPSHOTS: dict[str, OkrSnapshot] = {
    "V0": OkrSnapshot(
        code="V0",
        tag="okr-2026-v0",
        date="2026-07-16",
        notes=(
            "First stable checkpoint: interactive dashboard, weekly drill-down, "
            "PIN-protected Target editing (1618), Jan–Jun 2026 actuals"
        ),
    ),
    "V1": OkrSnapshot(
        code="V1",
        tag="okr-2026-v1",
        date="2026-07-19",
        notes=(
            "Before Yearly Target UI labels: yearly metrics with single Target/Actual "
            "cells (Exp/HR/Marketing/CAT/SC), editable DC yearly % + manual DC UNITS, "
            "Robotic store removed"
        ),
    ),
    "V2": OkrSnapshot(
        code="V2",
        tag="okr-2026-v2",
        date="2026-07-19",
        notes=(
            "Latest: Yearly Target column for all KPIs (Target + Gap cards), yearly "
            "single-cell Actual metrics, DC manual UNITS + editable yearly %, Cumulative "
            "Gap header (2 lines, Jan 26-Jul 26 range), Robotic store removed"
        ),
    ),
}

CURRENT_SNAPSHOT = "V2"


def get_snapshot(code: str) -> OkrSnapshot:
    key = code.strip().upper()
    if key not in SNAPSHOTS:
        known = ", ".join(sorted(SNAPSHOTS))
        raise KeyError(f"Unknown snapshot {code!r}. Known: {known}")
    return SNAPSHOTS[key]
