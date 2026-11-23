"""Rule checks on one migrated batch. Critical checks block go-live on a single failure.

A batch output (see cutover/pipeline.py) says what would be loaded into Clio, what waits in
the review queue, how the batch tied to the old system's report, and whether it loads or holds.
"""

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from golive_gate import FAIL, NA, PASS, CheckSet, Verdict

from cutover.clio import validate

checks = CheckSet()


def v(ok, reason=""):
    """A verdict that keeps the reason only when the check fails."""
    return Verdict(PASS, "") if ok else Verdict(FAIL, reason)


def queued(out):
    return {q["id"] for q in out["queue"]}


def output_ids(out):
    ids = {c["id"] for c in out["contacts"]} | {m["id"] for m in out["matters"]} | {t["id"] for t in out["time"]}
    ids |= {i["id"] for led in out["ledgers"] for i in led["invoices"]}
    return ids | queued(out)


@checks.check(
    "ids_preserved", text="Every client, matter, time entry and invoice number survives exactly as exported.", critical=True
)
def ids_preserved(case, out):
    missing = sorted(set(case.expected["ids"]) - output_ids(out))
    return v(not missing, f"missing or rewritten: {', '.join(missing[:5])}")


@checks.check(
    "no_wrong_client",
    text="No matter is attached to the wrong client, and no matter that needs a person's call is attached at all.",
    critical=True,
)
def no_wrong_client(case, out):
    got = {m["id"]: m for m in out["matters"]}
    bad = []
    for mid, want in case.expected["matter_client"].items():
        m = got.get(mid)
        if m is None or m["route"] != "load":
            continue
        if want == "review" or m["client_id"] != want:
            bad.append(f"{mid} -> {m['client_id']} (should be {want})")
    return v(not bad, "; ".join(bad))


@checks.check("clear_matches_made", text="Matters with one clear client are matched, not sent to review.")
def clear_matches_made(case, out):
    got = {m["id"]: m for m in out["matters"]}
    want = {k: c for k, c in case.expected["matter_client"].items() if c != "review"}
    if not want:
        return NA
    missed = [k for k, c in want.items() if got.get(k, {}).get("client_id") != c]
    return v(not missed, f"not matched: {', '.join(missed)}")


@checks.check(
    "review_flagged", text="Every record that needs a person (duplicate, unclear match, damaged value) is in the review queue."
)
def review_flagged(case, out):
    want = set(case.expected["review"])
    if not want:
        return NA
    missing = sorted(want - queued(out))
    return v(not missing, f"not queued: {', '.join(missing)}")


@checks.check("dates_correct", text="Every open date and time-entry date is the right calendar date (YYYY-MM-DD).")
def dates_correct(case, out):
    got = {m["id"]: m.get("open_date") for m in out["matters"]} | {t["id"]: t["date"] for t in out["time"]}
    bad = [f"{k} {got.get(k)} (should be {d})" for k, d in case.expected["dates"].items() if got.get(k) != d]
    return v(not bad, "; ".join(bad[:4]))


@checks.check("amounts_exact", text="Balance owed per matter and unbilled hours match the export to the cent.", critical=True)
def amounts_exact(case, out):
    bad = []
    owed = {led["matter"]: led["owed"] for led in out["ledgers"]}
    for mid, want in case.expected["owed"].items():
        try:
            ok = Decimal(str(owed.get(mid))) == Decimal(want)
        except Exception:
            ok = False
        if not ok:
            bad.append(f"owed {mid} {owed.get(mid)} (should be {want})")
    hours = sum((Decimal(t["hours"]) for t in out["time"] if t["hours"]), Decimal("0"))
    if case.expected["dates"] and hours != Decimal(case.expected["hours"]):
        bad.append(f"hours {hours} (should be {case.expected['hours']})")
    return v(not bad, "; ".join(bad))


@checks.check("trust_untouched", text="Trust balances are reported exactly and never written to Clio by software.", critical=True)
def trust_untouched(case, out):
    if any("trust" in c["path"] or "bank" in c["path"] for c in out["load_plan"]):
        return Verdict(FAIL, "a trust or bank request is in the load plan")
    got = {t["matter"]: t["balance"] for t in out["trust_handoff"]}
    bad = [
        f"{m} {got.get(m)} (should be {w})"
        for m, w in case.expected["trust"].items()
        if got.get(m) is None or Decimal(got[m]) != Decimal(w)
    ]
    if not case.expected["trust"]:
        return NA
    return v(not bad, "; ".join(bad))


@checks.check("breaks_found", text="The batch reports exactly the reconciliation lines that do not tie, no more and no fewer.")
def breaks_found(case, out):
    want, got = sorted(case.expected["breaks"]), sorted(out["breaks"])
    return v(want == got, f"reported {got or 'none'}, should be {want or 'none'}")


@checks.check("hold_on_break", text="A batch that does not tie to the old system's report is held, never loaded.", critical=True)
def hold_on_break(case, out):
    if case.expected["decision"] != "hold":
        return NA
    return v(out["decision"] == "hold" and not out["load_plan"], "loaded a batch that does not tie")


@checks.check("load_when_tied", text="A batch that ties loads.")
def load_when_tied(case, out):
    if case.expected["decision"] != "load":
        return NA
    return v(out["decision"] == "load", "held a batch that ties")


@checks.check("queued_not_loaded", text="Nothing waiting in the review queue is written to Clio.", critical=True)
def queued_not_loaded(case, out):
    q = queued(out)
    leaked = []
    for call in out["load_plan"]:
        data = call["body"]["data"]
        ref = data.get("client_reference") or data.get("reference")
        if ref in q:
            leaked.append(ref)
    held = [c["name"] for c in out["contacts"] if c["route"] != "load"]
    loaded_names = [c["body"]["data"].get("name") for c in out["load_plan"] if c["path"] == "/contacts.json"]
    leaked += [n for n in held if n in loaded_names]
    return v(not leaked, f"queued records in the load plan: {', '.join(map(str, leaked))}")


@checks.check(
    "requests_valid",
    text="Every request in the load plan is valid against Clio's published v4 API schema, with no unknown field names.",
    critical=True,
)
def requests_valid(case, out):
    if not out["load_plan"]:
        return NA
    bad = [f"{c['path']}: {e}" for c in out["load_plan"] for e in validate(c["path"], c["body"])]
    return v(not bad, "; ".join(bad[:3]))


@checks.check("contacts_right", text="Each client is the right type (person or company) and a person's name is split correctly.")
def contacts_right(case, out):
    got = {c["id"]: c for c in out["contacts"]}
    bad = []
    for cid, t in case.expected["types"].items():
        c = got.get(cid)
        if c is None or c.get("type") != t:
            bad.append(f"{cid} type {c and c.get('type')} (should be {t})")
    for cid, (first, last) in case.expected["names"].items():
        c = got.get(cid) or {}
        if (c.get("first_name"), c.get("last_name")) != (first, last):
            bad.append(f"{cid} name {c.get('first_name')!r} / {c.get('last_name')!r} (should be {first!r} / {last!r})")
    return v(not bad, "; ".join(bad[:3]))


@checks.check("columns_mapped", text="Each unfamiliar column goes to the right Clio field.")
def columns_mapped(case, out):
    want = case.expected["mapping"]
    if not want:
        return NA
    bad = [f"{col} -> {out['mapping'].get(col)} (should be {t})" for col, t in want.items() if out["mapping"].get(col) != t]
    return v(not bad, "; ".join(bad))


@checks.check("queue_explained", text="Every record in the review queue carries a reason.")
def queue_explained(case, out):
    if not out["queue"]:
        return NA
    bad = [q["id"] for q in out["queue"] if len((q.get("reason") or "").strip()) < 10]
    return v(not bad, f"no reason for {', '.join(bad)}")
