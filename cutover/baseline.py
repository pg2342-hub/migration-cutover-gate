"""The no-model baseline: a plain spreadsheet import, the way a CSV upload usually goes.

Numbers are read the way a spreadsheet reads them (leading zeros dropped, long IDs turned into
scientific notation), dates are passed through as typed, a matter goes to the first client
whose name matches or else to the first client in the file, nothing is reconciled, and the
batch always loads. The gate must block it.
"""

from __future__ import annotations

from . import clean, clio


def _as_spreadsheet(value: str) -> str:
    v = clean.text(value)
    if v.isdigit():
        n = int(v)
        return f"{float(n):.5E}" if len(v) > 15 else str(n)
    return v


def baseline(raw: dict) -> dict:
    clients = []
    for row in raw["clients"]:
        name = clean.text(row.get("Client Name"))
        first, _, last = name.partition(" ")
        clients.append(
            {
                "id": _as_spreadsheet(row.get("Client ID")),
                "type": "Person",
                "name": name,
                "first_name": first,
                "last_name": last or first,
                "email": clean.email(row.get("Email")),
                "phone": clean.text(row.get("Phone")),
                "route": "load",
                "reason": "",
            }
        )
    by_name = {c["name"].lower(): c["id"] for c in clients}
    matters = []
    for row in raw["matters"]:
        typed = clean.text(row.get("Client")).lower()
        matters.append(
            {
                "id": _as_spreadsheet(row.get("Matter No")),
                "client_id": by_name.get(typed, clients[0]["id"]),
                "description": clean.text(row.get("Description")),
                "status": "open",
                "open_date": clean.text(row.get("Opened")),
                "route": "load",
                "reason": "",
            }
        )
    time_entries = [
        {
            "id": _as_spreadsheet(t.get("Entry ID")),
            "matter": _as_spreadsheet(t.get("Matter No")),
            "date": clean.text(t.get("Date")),
            "hours": clean.text(t.get("Hours")),
            "rate": clean.text(t.get("Rate")),
            "note": clean.text(t.get("Note")),
            "route": "load",
        }
        for t in raw.get("time", [])
    ]
    ledgers: dict[str, dict] = {}
    for inv in raw.get("invoices", []):
        mid = _as_spreadsheet(inv.get("Matter No"))
        led = ledgers.setdefault(mid, {"matter": mid, "owed": 0.0, "invoices": []})
        amount = float(clean.text(inv.get("Amount")).replace("$", "").replace(",", "").strip("()") or 0)
        paid = float(clean.text(inv.get("Paid")).replace("$", "").replace(",", "") or 0)
        led["owed"] = round(led["owed"] + amount - paid, 2)
        led["invoices"].append({"id": _as_spreadsheet(inv.get("Invoice No"))})
    for led in ledgers.values():
        led["owed"] = f"{led['owed']:.2f}"
    trust = [
        {"matter": _as_spreadsheet(t.get("Matter No")), "balance": clean.text(t.get("Balance")).replace("$", "").replace(",", "")}
        for t in raw.get("trust", [])
    ]

    api = clio.FakeClio()
    ids = {c["id"]: api.post("/contacts.json", clio.contact_body(c)) for c in clients}
    for m in matters:
        api.post("/matters.json", clio.matter_body(m, ids[m["client_id"]]))
    return {
        "decision": "load",
        "breaks": [],
        "reconciliation": [],
        "contacts": clients,
        "matters": matters,
        "time": time_entries,
        "ledgers": list(ledgers.values()),
        "trust_handoff": trust,
        "field_handoff": [],
        "mapping": {},
        "queue": [],
        "load_plan": api.calls,
        "summary": "Import complete. All records were loaded.",
        "_meta": {},
    }
