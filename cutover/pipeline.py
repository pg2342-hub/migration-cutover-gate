"""One batch, end to end: clean, reconcile, map (Claude), apply guardrails, decide, load.

Order matters. Rules clean every value and tie the batch to the old system's report before the
model sees it. The model's calls (client types, name splits, matter-to-client matches,
duplicates, column targets, review notes) are then applied under guardrails:
- the model never supplies a number, an ID or a date; those come from the cleaned values;
- a match to a client that is not in the batch, or one the model marks uncertain, goes to review;
- a possible duplicate holds both rows and their matters for review;
- a value the rules could not read sends its record to review;
- the batch loads only when every reconciliation line ties, and queued records never load;
- trust balances are never written; they go to the bookkeeper's hand-off list.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

from . import clean, clio
from .reconcile import breaks as find_breaks
from .reconcile import reconcile

CORE = {
    "clients": {"Client ID", "Client Name", "Email", "Phone"},
    "matters": {"Matter No", "Client", "Client ID", "Description", "Opened", "Status"},
}


def _queue(queue: list[dict], kind: str, rid: str, reason: str) -> None:
    if not any(q["id"] == rid and q["type"] == kind for q in queue):
        queue.append({"type": kind, "id": rid, "reason": reason})


def clean_batch(raw: dict) -> tuple[dict, list[dict]]:
    """Cleaned records plus a review queue of values no rule could read."""
    queue: list[dict] = []
    out: dict[str, Any] = {"clients": [], "matters": [], "time": [], "invoices": [], "trust": [], "report": raw["report"]}

    for row in raw["clients"]:
        rid = clean.text(row.get("Client ID"))
        try:
            cid = clean.legacy_id(rid)
        except clean.CleanError as e:
            _queue(queue, "client", rid, str(e))
            cid = rid
        extras = {k: clean.text(v) for k, v in row.items() if k not in CORE["clients"]}
        out["clients"].append(
            {
                "id": cid,
                "name": clean.text(row.get("Client Name")),
                "email": clean.email(row.get("Email")),
                "phone": clean.phone(row.get("Phone")),
                "extras": extras,
            }
        )

    for row in raw["matters"]:
        rid = clean.text(row.get("Matter No"))
        m: dict[str, Any] = {"id": rid, "client_text": clean.text(row.get("Client")), "client_id_text": ""}
        try:
            m["id"] = clean.legacy_id(rid)
        except clean.CleanError as e:
            _queue(queue, "matter", rid, str(e))
        cref = clean.text(row.get("Client ID"))
        if cref:
            if clean.mangled(cref):
                _queue(queue, "matter", m["id"], f"client ID {cref!r} looks rewritten by a spreadsheet")
            else:
                m["client_id_text"] = cref
        try:
            m["open_date"] = clean.iso_date(row.get("Opened"))
        except clean.CleanError as e:
            m["open_date"] = None
            _queue(queue, "matter", m["id"], str(e))
        m["description"] = clean.text(row.get("Description")) or "(no description in old system)"
        m["status"] = "closed" if clean.text(row.get("Status")).lower().startswith("clos") else "open"
        m["extras"] = {k: clean.text(v) for k, v in row.items() if k not in CORE["matters"]}
        for col, val in m["extras"].items():
            if clean.is_id_column(col) and clean.mangled(val):
                _queue(queue, "matter", m["id"], f"{col} value {val!r} looks rewritten by a spreadsheet")
        out["matters"].append(m)

    for row in raw.get("time", []):
        rid = clean.text(row.get("Entry ID"))
        try:
            out["time"].append(
                {
                    "id": clean.legacy_id(rid),
                    "matter": clean.text(row.get("Matter No")),
                    "date": clean.iso_date(row.get("Date")),
                    "hours": clean.hours(row.get("Hours")),
                    "rate": clean.money(row.get("Rate")),
                    "note": clean.text(row.get("Note")),
                }
            )
        except clean.CleanError as e:
            _queue(queue, "time", rid, str(e))

    for row in raw.get("invoices", []):
        rid = clean.text(row.get("Invoice No"))
        try:
            out["invoices"].append(
                {
                    "id": clean.legacy_id(rid),
                    "matter": clean.text(row.get("Matter No")),
                    "date": clean.iso_date(row.get("Date")),
                    "amount": clean.money(row.get("Amount")),
                    "paid": clean.money(row.get("Paid") or "0"),
                }
            )
        except clean.CleanError as e:
            _queue(queue, "invoice", rid, str(e))

    for row in raw.get("trust", []):
        mid = clean.text(row.get("Matter No"))
        try:
            out["trust"].append({"matter": mid, "balance": clean.money(row.get("Balance"))})
        except clean.CleanError as e:
            _queue(queue, "trust", mid, str(e))
    return out, queue


def mapper_view(batch: dict, rows: list[dict], queue: list[dict]) -> dict:
    """What the model sees: names, emails, typed client references and column names. No amounts."""
    extra_cols = sorted({c for m in batch["matters"] for c in m["extras"]} | {c for k in batch["clients"] for c in k["extras"]})
    return {
        "clients": [
            {"legacy_id": c["id"], "name": c["name"], "email": c["email"], "phone": c["phone"]} for c in batch["clients"]
        ],
        "matters": [
            {
                "matter_id": m["id"],
                "client_as_typed": m["client_text"],
                "client_id_as_typed": m["client_id_text"],
                "description": m["description"],
            }
            for m in batch["matters"]
        ],
        "extra_columns": [
            {
                "column": col,
                "sample": next((r["extras"][col] for r in batch["matters"] + batch["clients"] if r["extras"].get(col)), ""),
            }
            for col in extra_cols
        ],
        "flagged_by_rules": [dict(q) for q in queue],  # a copy: the queue grows after the model call
        "reconciliation": [{k: r[k] for k in ("measure", "key", "source", "migrated", "ties")} for r in rows],
    }


def run(raw: dict, mapper: Callable[[dict], dict], make_target: Callable[[], Any] = clio.FakeClio) -> dict:
    batch, queue = clean_batch(raw)
    rows = reconcile(batch)
    breaks = find_breaks(rows)
    decisions = mapper(mapper_view(batch, rows, queue))
    meta = decisions.get("_meta", {})

    notes = {n["record_id"]: n["note"] for n in decisions.get("review_notes", [])}
    mapping = {c["source_column"]: c["target"] for c in decisions.get("column_mapping", [])}
    by_contact = {c["legacy_id"]: c for c in decisions.get("contacts", [])}
    client_ids = {c["id"] for c in batch["clients"]}

    # contacts
    contacts, held_clients = [], set()
    for c in batch["clients"]:
        d = by_contact.get(c["id"])
        rec = {"id": c["id"], "email": c["email"], "phone": c["phone"], "route": "load", "reason": ""}
        if d is None:
            rec.update(type=None, name=c["name"], first_name=None, last_name=None)
            rec["route"], rec["reason"] = "review", "the mapping step returned nothing for this client"
        else:
            rec.update(type=d["type"], name=d["name"], first_name=d["first_name"], last_name=d["last_name"])
            dup = d.get("duplicate_of")
            if dup:
                if dup not in client_ids or dup == c["id"]:
                    rec["route"], rec["reason"] = "review", f"marked a duplicate of {dup}, which is not in this batch"
                else:
                    reason = notes.get(c["id"]) or f"may be the same client as {dup}"
                    rec["route"], rec["reason"] = "review", reason
                    held_clients |= {c["id"], dup}
        for col, val in c["extras"].items():
            target = mapping.get(col, "ignore")
            if target == "contact.ledes_client_id" and val:
                rec["ledes_client_id"] = val
            elif target == "contact.title" and val:
                rec["title"] = val
        contacts.append(rec)
    for rec in contacts:
        if rec["id"] in held_clients and rec["route"] == "load":
            rec["route"], rec["reason"] = "review", notes.get(rec["id"]) or "a possible duplicate of this client is in review"
    for q in queue:
        if q["type"] == "client":
            for rec in contacts:
                if rec["id"] == q["id"]:
                    rec["route"], rec["reason"] = "review", q["reason"]
    for rec in contacts:
        if rec["route"] == "review":
            _queue(queue, "client", rec["id"], rec["reason"])
    approved_clients = {c["id"] for c in contacts if c["route"] == "load"}

    # matters
    picks = {p["matter_id"]: p for p in decisions.get("matter_clients", [])}
    queued_matters = {q["id"] for q in queue if q["type"] == "matter"}
    matters, handoff = [], []
    for m in batch["matters"]:
        p = picks.get(m["id"])
        rec = {k: m[k] for k in ("id", "description", "status", "open_date")}
        rec.update(client_id=None, route="load", reason="")
        if m["id"] in queued_matters:
            rec["route"], rec["reason"] = "review", next(q["reason"] for q in queue if q["id"] == m["id"])
        elif p is None:
            rec["route"], rec["reason"] = "review", "the mapping step returned no client for this matter"
        elif not p["certain"] or not p["client_id"]:
            rec["route"], rec["reason"] = "review", notes.get(m["id"]) or p["reason"]
        elif p["client_id"] not in client_ids:
            rec["route"], rec["reason"] = "review", f"matched to client {p['client_id']}, which is not in this batch"
        else:
            rec["client_id"] = p["client_id"]
            if p["client_id"] not in approved_clients:
                rec["route"], rec["reason"] = "review", f"its client {p['client_id']} is waiting for review"
        for col, val in m["extras"].items():
            target = mapping.get(col, "ignore")
            if not val or target == "ignore":
                continue
            if target == "matter.location":
                rec["location"] = val
            elif target in ("matter.responsible_attorney", "matter.practice_area", "matter.custom_field"):
                why = "set after load; Clio needs the id of the user, practice area or custom field"
                handoff.append({"matter": m["id"], "field": target, "column": col, "value": val, "why": why})
        if rec["route"] == "review":
            _queue(queue, "matter", m["id"], rec["reason"])
        matters.append(rec)
    approved_matters = {m["id"] for m in matters if m["route"] == "load"}

    time_entries = [
        {
            **{k: t[k] for k in ("id", "matter", "date", "note")},
            "hours": str(t["hours"]),
            "rate": str(t["rate"]),
            "route": "load" if t["matter"] in approved_matters else "held with its matter",
        }
        for t in batch["time"]
    ]
    ledgers = []
    for mid in sorted({i["matter"] for i in batch["invoices"]}):
        invs = [i for i in batch["invoices"] if i["matter"] == mid]
        owed = sum((i["amount"] - i["paid"] for i in invs), Decimal("0.00"))
        ledgers.append(
            {
                "matter": mid,
                "owed": str(owed),
                "invoices": [
                    {"id": i["id"], "date": i["date"], "amount": str(i["amount"]), "paid": str(i["paid"])} for i in invs
                ],
            }
        )
    trust = [{"matter": t["matter"], "balance": str(t["balance"])} for t in batch["trust"]]

    decision = "hold" if breaks else "load"
    load_plan: list[dict] = []
    if decision == "load":
        api = make_target()
        ids: dict[str, int] = {}
        for c in contacts:
            if c["route"] == "load":
                ids[c["id"]] = api.post("/contacts.json", clio.contact_body(c))
        for m in matters:
            if m["route"] == "load":
                ids["m:" + m["id"]] = api.post("/matters.json", clio.matter_body(m, ids[m["client_id"]]))
        for t in batch["time"]:
            if t["matter"] in approved_matters:
                api.post("/activities.json", clio.time_body(t, ids["m:" + t["matter"]]))
        for led in ledgers:
            if led["matter"] in approved_matters:
                m = next(x for x in matters if x["id"] == led["matter"])
                api.post(
                    "/notes.json",
                    clio.ledger_note_body(
                        m, led["invoices"], led["owed"], ids["m:" + m["id"]], ids[m["client_id"]], m["open_date"]
                    ),
                )
        load_plan = api.calls

    return {
        "decision": decision,
        "breaks": breaks,
        "reconciliation": rows,
        "contacts": contacts,
        "matters": matters,
        "time": time_entries,
        "ledgers": ledgers,
        "trust_handoff": trust,
        "field_handoff": handoff,
        "mapping": mapping,
        "queue": queue,
        "load_plan": load_plan,
        "summary": decisions.get("summary", ""),
        "_meta": meta,
    }
