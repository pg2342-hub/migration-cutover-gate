"""The judgment step: one Claude call per batch.

Rules cannot decide these, so the model does: whether a client is a person or a company and
how the name splits, which client a matter belongs to when the old system typed the name by
hand, whether two client rows are the same client, where an unfamiliar column belongs in
Clio, a plain note for each record a person should check, and the message to the firm.

The model never touches a number, an ID or a date. It returns references and decisions only,
and the pipeline applies them with rules as guardrails (see pipeline.py).
"""

from __future__ import annotations

import json
import time
from typing import Any

MODEL = "claude-opus-5-5"
EFFORT = "low"
# USD per million tokens (input, output), first-party list prices.
PRICES = {"claude-opus-5-5": (4.00, 20.00), "claude-opus-4-8": (5.00, 25.00), "claude-sonnet-5-5": (2.00, 10.00)}

TARGETS = [
    "matter.responsible_attorney",
    "matter.practice_area",
    "matter.location",
    "matter.custom_field",
    "contact.ledes_client_id",
    "contact.title",
    "ignore",
]

_str_or_null = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["contacts", "matter_clients", "column_mapping", "review_notes", "summary"],
    "properties": {
        "contacts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["legacy_id", "type", "first_name", "last_name", "name", "duplicate_of"],
                "properties": {
                    "legacy_id": {"type": "string"},
                    "type": {"type": "string", "enum": ["Person", "Company"]},
                    "first_name": _str_or_null,
                    "last_name": _str_or_null,
                    "name": {"type": "string"},
                    "duplicate_of": _str_or_null,
                },
            },
        },
        "matter_clients": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["matter_id", "client_id", "certain", "reason"],
                "properties": {
                    "matter_id": {"type": "string"},
                    "client_id": _str_or_null,
                    "certain": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        },
        "column_mapping": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_column", "target"],
                "properties": {"source_column": {"type": "string"}, "target": {"type": "string", "enum": TARGETS}},
            },
        },
        "review_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["record_id", "note"],
                "properties": {"record_id": {"type": "string"}, "note": {"type": "string"}},
            },
        },
        "summary": {"type": "string"},
    },
}

SYSTEM = """You are the migration engineer moving a law firm's data from its old practice management system into Clio Manage. You handle one batch at a time. Rules have already cleaned the values and tied the batch to the old system's printed report; you make the calls rules cannot.

For each client row:
- type: Person for an individual, Company for a business, trust, estate, school or agency.
- For a Person, split first and last name ("Ruiz, Ana M." is first "Ana M.", last "Ruiz"). For a Company, first and last are null. name is the full display name.
- duplicate_of: if two rows in this batch are the same client (same email or phone with a name variant), set duplicate_of on the later row to the earlier row's legacy_id. Never call two different people duplicates because they share a surname.

For each matter, pick the client it belongs to (client_id = a legacy_id from this batch's clients). certain is true only when exactly one client fits. If two clients could fit, or none does, set certain false and say why in reason. A wrong match puts one client's case file under another client, so when in doubt, leave it for a person.

For each extra column listed, choose the Clio field it belongs in: responsible attorney, practice area, location (office), a matter custom field (case numbers and other matter facts with no standard field), the contact's LEDES client id or title, or ignore only for data with no value to the firm.

review_notes: for every record a person must check (an uncertain match, a possible duplicate, a value the rules flagged), one or two plain sentences to the firm's operations lead saying exactly what to look at and what answer you need. No jargon.

summary: three to five plain sentences to the firm's operations lead. State whether the batch is ready to load or on hold, the numbers that tie or do not tie (from the reconciliation given to you), and the exact sign-off or answers you need. The rule is fixed: the batch is on hold if any reconciliation line does not tie; otherwise it loads, and records waiting for review stay out until someone answers. Never say a held batch is ready."""


def prompt(view: dict) -> str:
    return "Batch to map:\n" + json.dumps(view, indent=1, sort_keys=True)


class ClaudeMapper:
    """Calls Claude through the Anthropic SDK; reads credentials the way the SDK does."""

    def __init__(self, model: str = MODEL, effort: str = EFFORT, client: Any = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort

    def __call__(self, view: dict) -> dict:
        start = time.perf_counter()
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt(view)}],
        )
        latency = time.perf_counter() - start
        if response.stop_reason == "refusal":
            raise RuntimeError("the model declined this batch")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("the mapping was cut off at max_tokens")
        text = next(b.text for b in response.content if b.type == "text")
        decisions = json.loads(text)
        decisions["_meta"] = {
            "model": getattr(response, "model", self.model),
            "cost_usd": self.cost(response),
            "latency_s": round(latency, 3),
        }
        return decisions

    def cost(self, response: Any) -> float:
        price = PRICES.get(getattr(response, "model", self.model)) or PRICES.get(self.model, (0.0, 0.0))
        usage = response.usage
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cached = getattr(usage, "cache_read_input_tokens", 0) or 0
        tokens_in = (usage.input_tokens or 0) + written * 1.25 + cached * 0.05
        return (tokens_in * price[0] + (usage.output_tokens or 0) * price[1]) / 1e6
