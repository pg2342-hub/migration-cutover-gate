"""An oracle for the mapping step: the decisions a correct model would return for a case.

Used by the tests to show the pipeline, guardrails and checks reach GO when the model is right,
and to plant single mistakes and watch the right check catch them.
"""

from golive_gate import load_cases

from cutover.reconcile import breaks as find_breaks

CASES = {c.id: c for c in load_cases("evals/cases.yml")}


def oracle(case):
    exp = case.expected
    dups = {}
    if case.id == "a03":
        dups = {"C1025": "C1024"}

    def mapper(view):
        contacts = []
        for c in view["clients"]:
            t = exp["types"][c["legacy_id"]]
            first, last = exp["names"].get(c["legacy_id"], [None, None])
            contacts.append(
                {
                    "legacy_id": c["legacy_id"],
                    "type": t,
                    "first_name": first,
                    "last_name": last,
                    "name": c["name"],
                    "duplicate_of": dups.get(c["legacy_id"]),
                }
            )
        picks, notes = [], []
        for m in view["matters"]:
            want = exp["matter_client"][m["matter_id"]]
            if want == "review":
                picks.append(
                    {"matter_id": m["matter_id"], "client_id": None, "certain": False, "reason": "two clients could fit"}
                )
                notes.append(
                    {"record_id": m["matter_id"], "note": f"Please confirm which client matter {m['matter_id']} belongs to."}
                )
            else:
                picks.append({"matter_id": m["matter_id"], "client_id": want, "certain": True, "reason": "one clear match"})
        for d in dups:
            notes.append(
                {"record_id": d, "note": f"Rows {d} and {dups[d]} share an email and phone; please confirm they are one client."}
            )
        mapping = [
            {"source_column": e["column"], "target": exp["mapping"].get(e["column"], "ignore")} for e in view["extra_columns"]
        ]
        held = bool(find_breaks(view["reconciliation"]))
        summary = (
            "This batch is on hold because a reconciliation line does not tie." if held else "This batch ties and is loading."
        )
        return {
            "contacts": contacts,
            "matter_clients": picks,
            "column_mapping": mapping,
            "review_notes": notes,
            "summary": summary,
            "_meta": {"model": "oracle", "cost_usd": 0.0, "latency_s": 0.0},
        }

    return mapper
