"""Load requests against Clio's published v4 request schemas, and the live client with a fake HTTP session."""

import types
from decimal import Decimal

import pytest

from cutover import clio


def test_valid_bodies_pass():
    c = {
        "type": "Person",
        "name": "Ana Ruiz",
        "first_name": "Ana",
        "last_name": "Ruiz",
        "email": "a@example.com",
        "phone": "+13125550141",
    }
    assert clio.validate("/contacts.json", clio.contact_body(c)) == []
    m = {"id": "M1", "description": "Lease", "status": "open", "open_date": "2025-02-11"}
    assert clio.validate("/matters.json", clio.matter_body(m, 7)) == []
    t = {"id": "T1", "date": "2025-03-02", "hours": Decimal("1.50"), "rate": Decimal("350.00"), "note": ""}
    body = clio.time_body(t, 9)
    assert clio.validate("/activities.json", body) == []
    assert body["data"]["quantity"] == 5400.0  # seconds since API v4.0.4


def test_schema_catches_bad_requests():
    assert clio.validate("/matters.json", {"data": {"description": "x"}})  # no client
    assert clio.validate("/matters.json", {"data": {"client": {"id": 1}, "description": "x", "open_date": "3/4/25"}})
    assert clio.validate("/contacts.json", {"data": {"name": "x", "type": "Robot"}})
    assert clio.validate("/trust_requests.json", {"data": {}}) == ["no published schema for /trust_requests.json"]
    misspelt = {"data": {"client": {"id": 1}, "description": "x", "open_dat": "2025-03-04"}}
    assert any("open_dat" in e for e in clio.validate("/matters.json", misspelt))


def test_live_client_sends_bearer_and_reads_ids():
    sent = []

    class Session:
        def post(self, url, json, headers, timeout):
            sent.append((url, headers["Authorization"]))
            return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": {"id": 555}})

    api = clio.LiveClio(token="tok", host="app.clio.com", session=Session())
    body = clio.contact_body({"type": "Company", "name": "Acme Corporation"})
    assert api.post("/contacts.json", body) == 555
    assert sent == [("https://app.clio.com/api/v4/contacts.json", "Bearer tok")]


def test_live_client_refuses_invalid_request():
    api = clio.LiveClio(token="tok", session=object())
    with pytest.raises(ValueError):
        api.post("/matters.json", {"data": {"description": "no client"}})
