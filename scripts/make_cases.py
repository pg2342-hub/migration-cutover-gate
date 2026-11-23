"""Write evals/cases.yml: 30 constructed migration batches for a fictional 12-lawyer firm.

Each batch is what the old practice management system exports for a few clients (clients,
matters, unbilled time, billed invoices, trust balances, all as text the way a CSV holds it)
plus the totals the old system prints on its own reports. Each case also says what a correct
migration produces. Truth values are written next to the raw text, so the expectations are
computed from the truth, never from the pipeline.

Groups:
  routine (10)  clean exports that should tie and load
  messy (8)     values a spreadsheet or the old system mangled: leading zeros, long IDs,
                mixed date formats, accounting negatives, h:mm hours, unfamiliar columns
  match (6)     matters whose client was typed by hand: one clear match, two possible
                matches, a client not in the batch, a duplicate client row
  break (6)     the export and the report disagree (a missing invoice, a dropped time
                entry, a trust balance off by a cent), or agree only if amounts are read exactly

python scripts/make_cases.py   # rewrites evals/cases.yml
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent.parent / "evals" / "cases.yml"
D = Decimal


def C(cid, name, ctype, first=None, last=None, email="", phone="", **extra):
    return {"id": cid, "name": name, "type": ctype, "first": first, "last": last, "email": email, "phone": phone, "extra": extra}


def M(mid, client_typed, client, desc, opened_raw, opened, status="Open", client_id_typed="", **extra):
    return {
        "id": mid,
        "typed": client_typed,
        "client": client,
        "desc": desc,
        "raw": opened_raw,
        "date": opened,
        "status": status,
        "cid_typed": client_id_typed,
        "extra": extra,
    }


def T(tid, matter, date_raw, date, hours_raw, hours, rate="350.00", note="Drafting"):
    return {
        "id": tid,
        "matter": matter,
        "raw": date_raw,
        "date": date,
        "hraw": hours_raw,
        "hours": D(hours),
        "rate": rate,
        "note": note,
    }


def I(iid, matter, date_raw, date, amount_raw, amount, paid_raw="0.00", paid="0.00"):
    return {
        "id": iid,
        "matter": matter,
        "raw": date_raw,
        "date": date,
        "araw": amount_raw,
        "amount": D(amount),
        "praw": paid_raw,
        "paid": D(paid),
    }


def TR(matter, raw, value):
    return {"matter": matter, "raw": raw, "value": D(value)}


CASES: list[dict] = []


def case(
    cid,
    group,
    title,
    clients,
    matters,
    time=(),
    invoices=(),
    trust=(),
    *,
    report=None,
    decision="load",
    review=(),
    match=None,
    mapping=None,
    breaks=(),
    mangled=(),
):
    owed: dict[str, Decimal] = {}
    for i in invoices:
        owed[i["matter"]] = owed.get(i["matter"], D("0.00")) + i["amount"] - i["paid"]
    hours = sum((t["hours"] for t in time), D("0.00"))
    rep = {
        "clients": len(clients),
        "matters": len(matters),
        "unbilled_hours": f"{hours:.2f}",
        "ar": {m: f"{v:,.2f}" for m, v in owed.items()},
        "trust": {t["matter"]: f"{t['value']:,.2f}" for t in trust},
    }
    for k, v in (report or {}).items():
        if isinstance(v, dict):
            rep[k] = {**rep[k], **v}
        else:
            rep[k] = v

    raw = {
        "clients": [
            {"Client ID": c["id"], "Client Name": c["name"], "Email": c["email"], "Phone": c["phone"], **c["extra"]}
            for c in clients
        ],
        "matters": [
            {
                "Matter No": m["id"],
                "Client": m["typed"],
                "Client ID": m["cid_typed"],
                "Description": m["desc"],
                "Opened": m["raw"],
                "Status": m["status"],
                **m["extra"],
            }
            for m in matters
        ],
        "time": [
            {
                "Entry ID": t["id"],
                "Matter No": t["matter"],
                "Date": t["raw"],
                "Hours": t["hraw"],
                "Rate": t["rate"],
                "Note": t["note"],
            }
            for t in time
        ],
        "invoices": [
            {"Invoice No": i["id"], "Matter No": i["matter"], "Date": i["raw"], "Amount": i["araw"], "Paid": i["praw"]}
            for i in invoices
        ],
        "trust": [{"Matter No": t["matter"], "Balance": t["raw"]} for t in trust],
        "report": rep,
    }
    review = set(review) | set(mangled)
    expected = {
        "decision": decision,
        "breaks": sorted(breaks),
        "matter_client": {m["id"]: ("review" if m["id"] in review else (match or {}).get(m["id"], m["client"])) for m in matters},
        "review": sorted(review),
        "ids": sorted(
            {c["id"] for c in clients}
            | {m["id"] for m in matters}
            | {t["id"] for t in time}
            | {i["id"] for i in invoices} - set(mangled)
        ),
        "dates": {**{m["id"]: m["date"] for m in matters if m["date"]}, **{t["id"]: t["date"] for t in time}},
        "hours": f"{hours:.2f}",
        "owed": {m: f"{v:.2f}" for m, v in owed.items()},
        "trust": {t["matter"]: f"{t['value']:.2f}" for t in trust},
        "types": {c["id"]: c["type"] for c in clients},
        "names": {c["id"]: [c["first"], c["last"]] for c in clients if c["type"] == "Person"},
        "mapping": mapping or {},
    }
    CASES.append({"id": cid, "group": group, "title": title, "input": raw, "expected": expected})


# ---------------------------------------------------------------- routine (10)
case(
    "r01",
    "routine",
    "One person, one matter, clean export",
    [C("C1001", "Ana Ruiz", "Person", "Ana", "Ruiz", "ana.ruiz@example.com", "(312) 555-0141")],
    [M("M2001", "Ana Ruiz", "C1001", "Ruiz - lease dispute", "2025-02-11", "2025-02-11")],
    [
        T("T3001", "M2001", "2025-03-02", "2025-03-02", "1.50", "1.5"),
        T("T3002", "M2001", "2025-03-09", "2025-03-09", "0.75", "0.75"),
    ],
    [I("I4001", "M2001", "2025-02-28", "2025-02-28", "1,200.00", "1200.00", "800.00", "800.00")],
    [TR("M2001", "2,500.00", "2500.00")],
)
case(
    "r02",
    "routine",
    "A company with two matters",
    [C("C1002", "Lakeview Dental Group, P.C.", "Company", email="office@lakeviewdental.example", phone="312-555-0177")],
    [
        M("M2002", "Lakeview Dental Group, P.C.", "C1002", "Employment agreement review", "1/14/2025", "2025-01-14"),
        M("M2003", "Lakeview Dental Group, P.C.", "C1002", "Office lease renewal", "3/3/2025", "2025-03-03"),
    ],
    [
        T("T3003", "M2002", "1/20/2025", "2025-01-20", "2.00", "2.0"),
        T("T3004", "M2003", "3/10/2025", "2025-03-10", "1.25", "1.25"),
    ],
    [I("I4002", "M2002", "1/31/2025", "2025-01-31", "700.00", "700.00", "700.00", "700.00")],
)
case(
    "r03",
    "routine",
    "Last-name-first client name",
    [C("C1003", "Okafor, Chidi", "Person", "Chidi", "Okafor", "chidi.okafor@example.com", "773 555 0102")],
    [M("M2004", "Okafor, Chidi", "C1003", "Okafor - estate plan", "2024-11-05", "2024-11-05")],
    [T("T3005", "M2004", "2024-11-12", "2024-11-12", "3.00", "3.0", "295.00")],
    [I("I4003", "M2004", "2024-11-30", "2024-11-30", "885.00", "885.00")],
)
case(
    "r04",
    "routine",
    "Two people, one matter each",
    [
        C("C1004", "Grace Lin", "Person", "Grace", "Lin", "glin@example.com"),
        C("C1005", "Marcus Bell", "Person", "Marcus", "Bell", "mbell@example.com"),
    ],
    [
        M("M2005", "Grace Lin", "C1004", "Lin - immigration petition", "2025-04-01", "2025-04-01"),
        M("M2006", "Marcus Bell", "C1005", "Bell - traffic matter", "2025-04-03", "2025-04-03"),
    ],
    [
        T("T3006", "M2005", "2025-04-02", "2025-04-02", "1.00", "1.0"),
        T("T3007", "M2006", "2025-04-04", "2025-04-04", "0.50", "0.5"),
    ],
    [],
    [TR("M2005", "1,000.00", "1000.00")],
)
case(
    "r05",
    "routine",
    "Closed matter with a paid-off invoice",
    [C("C1006", "Rivera Family Trust", "Company", email="trustee@riverafamily.example")],
    [M("M2007", "Rivera Family Trust", "C1006", "Trust administration 2024", "2024-06-17", "2024-06-17", status="Closed")],
    [],
    [I("I4004", "M2007", "2024-12-31", "2024-12-31", "4,350.00", "4350.00", "4,350.00", "4350.00")],
)
case(
    "r06",
    "routine",
    "Middle initial in the name",
    [C("C1007", "Ruiz, Ana M.", "Person", "Ana M.", "Ruiz", "amruiz@example.com", "+1 (646) 555-0199")],
    [M("M2008", "Ruiz, Ana M.", "C1007", "Ruiz - contract review", "2025-05-20", "2025-05-20")],
    [T("T3008", "M2008", "2025-05-21", "2025-05-21", "2.25", "2.25", "410.00")],
    [I("I4005", "M2008", "2025-05-31", "2025-05-31", "922.50", "922.50")],
)
case(
    "r07",
    "routine",
    "School district client, three matters",
    [C("C1008", "Westbrook Unified School District", "Company", email="legal@westbrook.example")],
    [
        M("M2009", "Westbrook Unified School District", "C1008", "Special education hearing", "2025-01-06", "2025-01-06"),
        M("M2010", "Westbrook Unified School District", "C1008", "Board policy update", "2025-02-10", "2025-02-10"),
        M("M2011", "Westbrook Unified School District", "C1008", "Facilities contract", "2025-03-17", "2025-03-17"),
    ],
    [
        T("T3009", "M2009", "2025-01-08", "2025-01-08", "4.00", "4.0", "275.00"),
        T("T3010", "M2011", "2025-03-18", "2025-03-18", "1.50", "1.5", "275.00"),
    ],
    [I("I4006", "M2010", "2025-02-28", "2025-02-28", "550.00", "550.00", "275.00", "275.00")],
)
case(
    "r08",
    "routine",
    "Client and spouse as separate clients",
    [
        C("C1009", "David Cho", "Person", "David", "Cho", "dcho@example.com", "917-555-0110"),
        C("C1010", "Hannah Cho", "Person", "Hannah", "Cho", "hcho@example.com", "917-555-0111"),
    ],
    [
        M("M2012", "David Cho", "C1009", "Cho - home purchase", "2025-06-02", "2025-06-02"),
        M("M2013", "Hannah Cho", "C1010", "Cho - business formation", "2025-06-09", "2025-06-09"),
    ],
    [
        T("T3011", "M2012", "2025-06-03", "2025-06-03", "1.00", "1.0"),
        T("T3012", "M2013", "2025-06-10", "2025-06-10", "1.00", "1.0"),
    ],
    [],
    [TR("M2012", "15,000.00", "15000.00")],
)
case(
    "r09",
    "routine",
    "Matter with no time yet",
    [C("C1011", "Northside Bakery LLC", "Company", email="owner@northsidebakery.example")],
    [M("M2014", "Northside Bakery LLC", "C1011", "Trademark filing", "2025-07-01", "2025-07-01")],
)
case(
    "r10",
    "routine",
    "Several time entries and two invoices",
    [C("C1012", "Priya Nair", "Person", "Priya", "Nair", "priya.nair@example.com")],
    [M("M2015", "Priya Nair", "C1012", "Nair - custody", "2025-02-03", "2025-02-03")],
    [
        T("T3013", "M2015", "2025-02-04", "2025-02-04", "1.10", "1.1"),
        T("T3014", "M2015", "2025-02-11", "2025-02-11", "0.40", "0.4"),
        T("T3015", "M2015", "2025-02-18", "2025-02-18", "2.30", "2.3"),
    ],
    [
        I("I4007", "M2015", "2025-01-31", "2025-01-31", "1,050.00", "1050.00", "1,050.00", "1050.00"),
        I("I4008", "M2015", "2025-02-28", "2025-02-28", "1,330.00", "1330.00", "500.00", "500.00"),
    ],
    [TR("M2015", "3,000.00", "3000.00")],
)

# ---------------------------------------------------------------- messy (8)
case(
    "m01",
    "messy",
    "Client and matter numbers with leading zeros",
    [C("00417", "Tomas Weber", "Person", "Tomas", "Weber", "tweber@example.com")],
    [M("000912", "Tomas Weber", "00417", "Weber - landlord claim", "2025-01-09", "2025-01-09", client_id_typed="00417")],
    [T("0031", "000912", "2025-01-10", "2025-01-10", "1.00", "1.0")],
    [I("00077", "000912", "2025-01-31", "2025-01-31", "350.00", "350.00")],
)
case(
    "m02",
    "messy",
    "Sixteen-digit matter reference kept as text",
    [C("C1013", "Bayside Cargo Partners LP", "Company", email="ops@baysidecargo.example")],
    [M("4012888888881881", "Bayside Cargo Partners LP", "C1013", "Cargo claim arbitration", "2025-03-12", "2025-03-12")],
    [T("T3016", "4012888888881881", "2025-03-13", "2025-03-13", "3.50", "3.5", "450.00")],
    [I("I4009", "4012888888881881", "2025-03-31", "2025-03-31", "1,575.00", "1575.00")],
)
case(
    "m03",
    "messy",
    "Four date formats in one export",
    [C("C1014", "Elena Petrova", "Person", "Elena", "Petrova", "epetrova@example.com")],
    [
        M("M2016", "Elena Petrova", "C1014", "Petrova - visa renewal", "04-Mar-25", "2025-03-04"),
        M("M2017", "Elena Petrova", "C1014", "Petrova - name change", "March 17, 2025", "2025-03-17"),
    ],
    [T("T3017", "M2016", "3/5/25", "2025-03-05", "1.00", "1.0"), T("T3018", "M2017", "45740", "2025-03-24", "0.50", "0.5")],
    [I("I4010", "M2016", "2025-03-31", "2025-03-31", "350.00", "350.00")],
)
case(
    "m04",
    "messy",
    "Credit note in accounting brackets",
    [C("C1015", "Brightwater Logistics Inc.", "Company", email="ap@brightwater.example")],
    [M("M2018", "Brightwater Logistics Inc.", "C1015", "Vendor contract dispute", "2025-02-02", "2025-02-02")],
    [],
    [
        I("I4011", "M2018", "2025-02-28", "2025-02-28", "$3,400.00", "3400.00"),
        I("I4012", "M2018", "2025-03-15", "2025-03-15", "(1,250.00)", "-1250.00"),
    ],
)
case(
    "m05",
    "messy",
    "Phone numbers typed five ways",
    [
        C("C1016", "Samuel Osei", "Person", "Samuel", "Osei", "sosei@example.com", "312.555.0123"),
        C("C1017", "Osei Family Holdings LLC", "Company", email="holdings@osei.example", phone="1-312-555-0124"),
    ],
    [
        M("M2019", "Samuel Osei", "C1016", "Osei - will", "2025-05-05", "2025-05-05"),
        M("M2020", "Osei Family Holdings LLC", "C1017", "Holding company setup", "2025-05-06", "2025-05-06"),
    ],
)
case(
    "m06",
    "messy",
    "Hours exported as h:mm",
    [C("C1018", "Fatima Haddad", "Person", "Fatima", "Haddad", "fhaddad@example.com")],
    [M("M2021", "Fatima Haddad", "C1018", "Haddad - employment claim", "2025-04-14", "2025-04-14")],
    [
        T("T3019", "M2021", "2025-04-15", "2025-04-15", "1:30", "1.5"),
        T("T3020", "M2021", "2025-04-16", "2025-04-16", "0:45", "0.75"),
        T("T3021", "M2021", "2025-04-17", "2025-04-17", "2.25", "2.25"),
    ],
)
case(
    "m07",
    "messy",
    "A court case number Excel turned into a date",
    [C("C1019", "Jonah Feld", "Person", "Jonah", "Feld", "jfeld@example.com")],
    [
        M("M2022", "Jonah Feld", "C1019", "Feld - small claims", "2025-06-01", "2025-06-01", **{"Court Case #": "4-Mar"}),
        M("M2023", "Jonah Feld", "C1019", "Feld - deed transfer", "2025-06-02", "2025-06-02", **{"Court Case #": ""}),
    ],
    review=["M2022"],
    mapping={"Court Case #": "matter.custom_field"},
)
case(
    "m08",
    "messy",
    "Unfamiliar columns: attorney, practice area, office",
    [C("C1020", "Greenway Property Management", "Company", email="legal@greenwaypm.example", **{"LEDES Client ID": "GPM-0042"})],
    [
        M(
            "M2024",
            "Greenway Property Management",
            "C1020",
            "Eviction - unit 4B",
            "2025-07-07",
            "2025-07-07",
            **{"Resp Atty": "K. Hollis", "Practice": "Landlord-Tenant", "Office": "Chicago"},
        )
    ],
    [T("T3022", "M2024", "2025-07-08", "2025-07-08", "1.00", "1.0")],
    mapping={
        "Resp Atty": "matter.responsible_attorney",
        "Practice": "matter.practice_area",
        "Office": "matter.location",
        "LEDES Client ID": "contact.ledes_client_id",
    },
)

# ---------------------------------------------------------------- match (6)
case(
    "a01",
    "match",
    "Two clients named Smith, matter typed 'Smith, J.'",
    [
        C("C1021", "John Smith", "Person", "John", "Smith", "john.smith@example.com"),
        C("C1022", "Julia Smith", "Person", "Julia", "Smith", "julia.smith@example.com"),
    ],
    [
        M("M2025", "John Smith", "C1021", "Smith - DUI defense", "2025-02-20", "2025-02-20"),
        M("M2026", "Smith, J.", "?", "Smith - fence dispute", "2025-02-21", "2025-02-21"),
    ],
    review=["M2026"],
)
case(
    "a02",
    "match",
    "Company typed as 'ACME Corp' in the matter",
    [C("C1023", "Acme Corporation", "Company", email="legal@acme.example")],
    [M("M2027", "ACME Corp", "C1023", "Supplier agreement", "2025-03-03", "2025-03-03")],
    [T("T3023", "M2027", "2025-03-04", "2025-03-04", "2.00", "2.0")],
)
case(
    "a03",
    "match",
    "Same client entered twice with a typo",
    [
        C("C1024", "Katherine O'Neil", "Person", "Katherine", "O'Neil", "koneil@example.com", "312-555-0188"),
        C("C1025", "Katharine ONeil", "Person", "Katharine", "ONeil", "koneil@example.com", "312-555-0188"),
    ],
    [M("M2028", "Katherine O'Neil", "C1024", "O'Neil - divorce", "2025-01-15", "2025-01-15")],
    review=["C1024", "C1025", "M2028"],
)
case(
    "a04",
    "match",
    "Client name blank but client ID filled",
    [
        C("C1026", "Victor Alvarez", "Person", "Victor", "Alvarez", "valvarez@example.com"),
        C("C1027", "Alvarez Roofing Co.", "Company", email="office@alvarezroofing.example"),
    ],
    [M("M2029", "", "C1027", "Lien enforcement", "2025-04-22", "2025-04-22", client_id_typed="C1027")],
    [T("T3024", "M2029", "2025-04-23", "2025-04-23", "1.00", "1.0")],
)
case(
    "a05",
    "match",
    "Matter names a client who is not in this batch",
    [C("C1028", "Nora Quinn", "Person", "Nora", "Quinn", "nquinn@example.com")],
    [
        M("M2030", "Nora Quinn", "C1028", "Quinn - probate", "2025-05-12", "2025-05-12"),
        M("M2031", "Desmond Quinn", "?", "Quinn - guardianship", "2025-05-13", "2025-05-13"),
    ],
    review=["M2031"],
)
case(
    "a06",
    "match",
    "Married name on the matter, same email on file",
    [C("C1029", "Jane Doe-Ruiz", "Person", "Jane", "Doe-Ruiz", "jane.doeruiz@example.com")],
    [M("M2032", "Jane Ruiz", "C1029", "Ruiz - adoption", "2025-06-16", "2025-06-16")],
    [T("T3025", "M2032", "2025-06-17", "2025-06-17", "1.50", "1.5")],
)

# ---------------------------------------------------------------- break (6)
case(
    "b01",
    "break",
    "An invoice missing from the export",
    [C("C1030", "Leo Marsh", "Person", "Leo", "Marsh", "lmarsh@example.com")],
    [M("M2033", "Leo Marsh", "C1030", "Marsh - contract claim", "2025-01-20", "2025-01-20")],
    [],
    [I("I4013", "M2033", "2025-01-31", "2025-01-31", "900.00", "900.00")],
    report={"ar": {"M2033": "1,450.00"}},
    decision="hold",
    breaks=["balance owed:M2033"],
)
case(
    "b02",
    "break",
    "Trust balance off by one cent",
    [C("C1031", "Sophie Turner", "Person", "Sophie", "Turner", "sturner@example.com")],
    [M("M2034", "Sophie Turner", "C1031", "Turner - real estate closing", "2025-02-14", "2025-02-14")],
    [],
    [],
    [TR("M2034", "12,000.00", "12000.00")],
    report={"trust": {"M2034": "12,000.01"}},
    decision="hold",
    breaks=["trust balance:M2034"],
)
case(
    "b03",
    "break",
    "A time entry dropped by the export",
    [C("C1032", "Ibrahim Saleh", "Person", "Ibrahim", "Saleh", "isaleh@example.com")],
    [M("M2035", "Ibrahim Saleh", "C1032", "Saleh - asylum case", "2025-03-01", "2025-03-01")],
    [T("T3026", "M2035", "2025-03-02", "2025-03-02", "2.00", "2.0")],
    report={"unbilled_hours": "3.50"},
    decision="hold",
    breaks=["unbilled hours:all"],
)
case(
    "b04",
    "break",
    "Report counts one more matter than the export",
    [C("C1033", "Coastal Clinics PLLC", "Company", email="admin@coastalclinics.example")],
    [M("M2036", "Coastal Clinics PLLC", "C1033", "HIPAA policy review", "2025-04-07", "2025-04-07")],
    report={"matters": 2},
    decision="hold",
    breaks=["matter count:all"],
)
case(
    "b05",
    "break",
    "Thirty small invoices that tie only when read to the cent",
    [C("C1034", "Mei Tanaka", "Person", "Mei", "Tanaka", "mtanaka@example.com")],
    [M("M2037", "Mei Tanaka", "C1034", "Tanaka - small business advice", "2025-01-02", "2025-01-02")],
    [],
    [I(f"I45{n:02d}", "M2037", "2025-02-01", "2025-02-01", "0.10", "0.10") for n in range(1, 31)],
)
case(
    "b06",
    "break",
    "Owed balance ties only if the bracketed credit is negative",
    [C("C1035", "Arturo Vega", "Person", "Arturo", "Vega", "avega@example.com")],
    [M("M2038", "Arturo Vega", "C1035", "Vega - workers' compensation", "2025-05-01", "2025-05-01")],
    [],
    [
        I("I4601", "M2038", "2025-05-31", "2025-05-31", "2,000.00", "2000.00"),
        I("I4602", "M2038", "2025-06-15", "2025-06-15", "(400.00)", "-400.00"),
    ],
)

if __name__ == "__main__":
    header = (
        "# 30 constructed migration batches for a fictional 12-lawyer firm. Generated by scripts/make_cases.py;\n"
        "# edit that file, not this one. All names, emails, phone numbers and amounts are made up.\n"
    )
    OUT.write_text(header + yaml.safe_dump({"cases": CASES}, sort_keys=False, allow_unicode=True, width=200))
    print(f"wrote {len(CASES)} cases to {OUT}")
