"""Load step: write approved records to Clio Manage through its v4 REST API.

Every request body is checked against the request schemas in Clio's published OpenAPI spec
(cutover/clio_openapi_subset.json, the four create endpoints this tool uses, fetched from
https://docs.developers.clio.com/openapi.json). The default target is FakeClio, which validates
and hands back ids the way the API does; LiveClio sends the same requests to a real account
(a Clio Manage trial or developer account) with an OAuth access token.

Two things are deliberately not written:
- Billed history (old invoices) does not import into Clio as bills, so each matter gets one
  note with its reconciled invoice ledger, and the balance owed is reported for the firm's
  billing lead to enter as one opening line, the way Clio's own migrations handle it.
- Trust balances are never written by software. They go on the hand-off list for the firm's
  bookkeeper, because trust accounting has to match the bank to the cent and be entered by
  the person responsible for it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import jsonschema

SPEC = json.loads((Path(__file__).parent / "clio_openapi_subset.json").read_text())
FORMATS = jsonschema.FormatChecker()


def _strict(schema: Any) -> Any:
    """The same schema, but any object with listed properties rejects field names it does not list.

    Clio ignores unknown fields, so a misspelt field name would be dropped without an error. Here it fails.
    """
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items()}
        if "properties" in out and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema


STRICT = {path: _strict(schema) for path, schema in SPEC["request_bodies"].items()}


def validate(path: str, body: dict) -> list[str]:
    """Errors against Clio's published request schema for POST {path}, plus unknown field names; empty when valid."""
    schema = STRICT.get(path)
    if schema is None:
        return [f"no published schema for {path}"]
    validator = jsonschema.Draft7Validator(schema, format_checker=FORMATS)
    return [f"{'/'.join(map(str, e.path)) or '(body)'}: {e.message}" for e in validator.iter_errors(body)]


class FakeClio:
    """Validates each request and returns sequential ids. Records every call for the report."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next = 1000

    def post(self, path: str, body: dict) -> int:
        errors = validate(path, body)
        self._next += 1
        self.calls.append({"method": "POST", "path": path, "body": body, "errors": errors, "id": self._next})
        return self._next


class LiveClio(FakeClio):
    """Sends the same validated requests to Clio. Needs CLIO_ACCESS_TOKEN (OAuth) and optional CLIO_REGION_HOST."""

    def __init__(self, token: str | None = None, host: str | None = None, session: Any = None) -> None:
        super().__init__()
        self.token = token or os.environ["CLIO_ACCESS_TOKEN"]
        self.base = f"https://{host or os.environ.get('CLIO_REGION_HOST', 'app.clio.com')}/api/v4"
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def post(self, path: str, body: dict) -> int:
        errors = validate(path, body)
        if errors:
            raise ValueError(f"refusing to send an invalid {path} request: {errors}")
        r = self.session.post(self.base + path, json=body, headers={"Authorization": f"Bearer {self.token}"}, timeout=30)
        r.raise_for_status()
        new_id = r.json()["data"]["id"]
        self.calls.append({"method": "POST", "path": path, "body": body, "errors": [], "id": new_id})
        return new_id


def contact_body(c: dict) -> dict:
    data: dict[str, Any] = {"type": c["type"], "name": c["name"]}
    if c["type"] == "Person":
        data["first_name"], data["last_name"] = c["first_name"], c["last_name"]
    if c.get("email"):
        data["email_addresses"] = [{"name": "Work", "address": c["email"], "default_email": True}]
    if c.get("phone"):
        data["phone_numbers"] = [{"name": "Work", "number": c["phone"], "default_number": True}]
    if c.get("title"):
        data["title"] = c["title"]
    if c.get("ledes_client_id"):
        data["ledes_client_id"] = c["ledes_client_id"]
    return {"data": data}


def matter_body(m: dict, client_id: int) -> dict:
    data: dict[str, Any] = {
        "client": {"id": client_id},
        "description": m["description"],
        "status": m["status"],
        "open_date": m["open_date"],
        "client_reference": m["id"],  # the old matter number, so the firm can still find it
    }
    if m.get("location"):
        data["location"] = m["location"]
    return {"data": data}


def time_body(t: dict, matter_id: int) -> dict:
    return {
        "data": {
            "type": "TimeEntry",
            "date": t["date"],
            "quantity": float(t["hours"] * 3600),  # v4.0.4+: quantity is in seconds
            "price": float(t["rate"]),
            "note": t["note"] or "Migrated time entry",
            "reference": t["id"],
            "matter": {"id": matter_id},
        }
    }


def ledger_note_body(matter: dict, invoices: list[dict], owed: str, matter_id: int, client_id: int, on: str) -> dict:
    lines = [f"Billed history migrated from the previous system (matter {matter['id']}); reconciled to its report."]
    for inv in invoices:
        lines.append(f"{inv['date']}  invoice {inv['id']}  billed {inv['amount']}  paid {inv['paid']}")
    lines.append(f"Balance owed at cut-over: {owed}")
    return {
        "data": {
            "type": "Matter",
            "subject": "Billed history before migration",
            "detail": "\n".join(lines),
            "date": on,
            "matter": {"id": matter_id},
            "contact": {"id": client_id},
        }
    }
