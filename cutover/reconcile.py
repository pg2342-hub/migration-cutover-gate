"""Tie the migrated records back to the old system's own report.

The old system prints its totals (client and matter counts, unbilled hours, what each matter
still owes, what each matter holds in trust). Those printed numbers are the answer key: a batch
loads only when every one of them matches what is about to be migrated, to the cent.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from . import clean


def _d(value) -> Decimal:
    return clean.money(value)


def reconcile(batch: dict) -> list[dict]:
    """One row per measure: what the report says, what the cleaned records add up to, and whether they tie."""
    report = batch["report"]
    rows: list[dict] = []

    def add(measure: str, key: str, source, migrated) -> None:
        rows.append(
            {"measure": measure, "key": key, "source": str(source), "migrated": str(migrated), "ties": source == migrated}
        )

    add("client count", "all", int(report["clients"]), len({c["id"] for c in batch["clients"]}))
    add("matter count", "all", int(report["matters"]), len({m["id"] for m in batch["matters"]}))

    hours = sum((t["hours"] for t in batch["time"]), Decimal("0.00"))
    add("unbilled hours", "all", clean.hours(report["unbilled_hours"]), hours)

    owed: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for inv in batch["invoices"]:
        owed[inv["matter"]] += inv["amount"] - inv["paid"]
    for matter in sorted(set(report.get("ar", {})) | set(owed)):
        source = _d(report["ar"][matter]) if matter in report.get("ar", {}) else Decimal("0.00")
        add("balance owed", matter, source, owed.get(matter, Decimal("0.00")))

    trust = {t["matter"]: t["balance"] for t in batch["trust"]}
    for matter in sorted(set(report.get("trust", {})) | set(trust)):
        source = _d(report["trust"][matter]) if matter in report.get("trust", {}) else Decimal("0.00")
        add("trust balance", matter, source, trust.get(matter, Decimal("0.00")))
    return rows


def breaks(rows: list[dict]) -> list[str]:
    return [f"{r['measure']}:{r['key']}" for r in rows if not r["ties"]]
