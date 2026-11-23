"""The judgment step: two Claude calls per batch.

Rules cannot decide these, so the model does: whether a client is a person or a company and
how the name splits, which client a matter belongs to when the old system typed the name by
hand, whether two client rows are the same client, where an unfamiliar column belongs in
Clio, a plain note for each record a person should check. Then, once code has applied the guardrails and
decided load or hold, a second call writes the message to the firm from that final state, so the
message never guesses what the guardrails will do.

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
    "required": ["contacts", "matter_clients", "column_mapping", "review_notes"],
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
    },
}

SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
}

SYSTEM = """You are the migration engineer moving a law firm's data from its old practice management system into Clio Manage. You handle one batch at a time. Rules have already cleaned the values and tied the batch to the old system's printed report; you make the calls rules cannot.

For each client row:
- type: Person for an individual, Company for a business, trust, estate, school or agency.
- For a Person, split first and last name ("Ruiz, Ana M." is first "Ana M.", last "Ruiz"). For a Company, first and last are null. name is the full display name.
- duplicate_of: if two rows in this batch are the same client (same email or phone with a name variant), set duplicate_of on the later row to the earlier row's legacy_id. Never call two different people duplicates because they share a surname.

For each matter, pick the client it belongs to (client_id = a legacy_id from this batch's clients). certain is true only when exactly one client fits. If two clients could fit, or none does, set certain false and say why in reason. A wrong match puts one client's case file under another client, so when in doubt, leave it for a person.

For each extra column listed, choose the Clio field it belongs in: responsible attorney, practice area, location (office), a matter custom field (case numbers and other matter facts with no standard field), the contact's LEDES client id or title, or ignore only for data with no value to the firm.

review_notes: for every record a person must check (an uncertain match, a possible duplicate, a value the rules flagged), one or two plain sentences to the firm's operations lead saying exactly which record to look at and ending with the exact answer you need (for example: "Please send the court case number for matter M2022 as it appears on the filing."). No jargon.
"""


SUMMARY_SYSTEM = """You write the message to a law firm's operations lead about one batch of their data moving from the old practice management system into Clio Manage. Code has already decided everything; you report it. Use only the facts given.

Three to five plain sentences, no jargon:
- If the decision is load: say the batch is being loaded into Clio, give the counts and totals that tie, and name every record in the review queue (it stays out of Clio until someone answers). Ask only for the answers the review queue needs; a batch that ties needs no approval to load. If the queue is empty, ask for nothing.
- If the decision is hold: say nothing has been loaded, name each line that does not tie with both numbers (the old system's report and the export), and say what the firm needs to check. Name review-queue records only if the queue lists them.
- Never mention a record as waiting for review unless it is in the review queue, and never say a held batch is ready or loaded."""


def summary_prompt(facts: dict) -> str:
    return "Final state of the batch:\n" + json.dumps(facts, indent=1, sort_keys=True)


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
        """The mapping decisions for a batch view, or the message to the firm for a final-state view (task: summary)."""
        if view.get("task") == "summary":
            system, schema, content = SUMMARY_SYSTEM, SUMMARY_SCHEMA, summary_prompt(view["facts"])
        else:
            system, schema, content = SYSTEM, SCHEMA, prompt(view)
        start = time.perf_counter()
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": content}],
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
