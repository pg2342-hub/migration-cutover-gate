"""Rule-based cleaning of a legacy export. Every value here is parsed by a rule, never by the model.

The export arrives as text, the way a CSV does. Rules keep IDs as text (so leading zeros and
long numbers survive), parse dates, money and hours exactly, and flag values that a spreadsheet
has already damaged so a person looks at them instead of anyone guessing.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
EXCEL_EPOCH = date(1899, 12, 30)

_SCI = re.compile(r"^\d(\.\d+)?[eE]\+\d+$")
_DAY_MON = re.compile(r"^\d{1,2}-(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)$", re.I)
_MON_DAY = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)-\d{1,2}$", re.I)
_ID_COLUMN = re.compile(r"(\bno\b|\bid\b|#|code|ref|number)", re.I)


class CleanError(ValueError):
    """A value no rule can read. The record goes to review with this message."""


def text(value) -> str:
    return "" if value is None else str(value).strip()


def legacy_id(value) -> str:
    """IDs stay exactly as exported: text, leading zeros kept, never cast to a number."""
    v = text(value)
    if not v:
        raise CleanError("blank ID")
    if mangled(v):
        raise CleanError(f"ID {v!r} looks rewritten by a spreadsheet; the original cannot be recovered from this file")
    return v


def mangled(value: str) -> bool:
    """True for the two forms Excel turns codes into: 4.01289E+15 and 4-Mar."""
    v = text(value)
    return bool(_SCI.match(v) or _DAY_MON.match(v) or _MON_DAY.match(v))


def is_id_column(name: str) -> bool:
    return bool(_ID_COLUMN.search(name))


def iso_date(value) -> str:
    """Read the date forms the old system and Excel produce. US month-first for slashes."""
    v = text(value)
    if not v:
        raise CleanError("blank date")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", v)
    if m:
        return _iso(int(m[1]), int(m[2]), int(m[3]), v)
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$", v)
    if m:
        return _iso(_year(m[3]), int(m[1]), int(m[2]), v)
    m = re.match(r"^(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})$", v)
    if m and m[2].lower() in MONTHS:
        return _iso(_year(m[3]), MONTHS[m[2].lower()], int(m[1]), v)
    m = re.match(r"^([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})$", v)
    if m and m[1].lower() in MONTHS:
        return _iso(int(m[3]), MONTHS[m[1].lower()], int(m[2]), v)
    if re.match(r"^\d{5}$", v) and 20000 <= int(v) <= 80000:  # Excel serial day number
        return (EXCEL_EPOCH + timedelta(days=int(v))).isoformat()
    raise CleanError(f"unreadable date {v!r}")


def _year(y: str) -> int:
    n = int(y)
    return 2000 + n if n < 100 else n


def _iso(y: int, mo: int, d: int, raw: str) -> str:
    try:
        return date(y, mo, d).isoformat()
    except ValueError as exc:
        raise CleanError(f"impossible date {raw!r}") from exc


def money(value) -> Decimal:
    """$1,250.00, 1250, (1,250.00) and -1250 all read exactly, to the cent."""
    v = text(value)
    if not v:
        raise CleanError("blank amount")
    negative = v.startswith("(") and v.endswith(")")
    v = v.strip("()").replace("$", "").replace(",", "").strip()
    if v.startswith("-"):
        negative, v = not negative, v[1:]
    try:
        amount = Decimal(v)
    except InvalidOperation as exc:
        raise CleanError(f"unreadable amount {value!r}") from exc
    if amount != amount.quantize(Decimal("0.01")):
        raise CleanError(f"amount {value!r} has fractions of a cent")
    return -amount if negative else amount


def hours(value) -> Decimal:
    """1.5, 1.50 and 1:30 are all one and a half hours."""
    v = text(value)
    m = re.match(r"^(\d+):([0-5]\d)$", v)
    if m:
        return (Decimal(m[1]) + Decimal(m[2]) / 60).quantize(Decimal("0.01"))
    try:
        h = Decimal(v)
    except InvalidOperation as exc:
        raise CleanError(f"unreadable hours {value!r}") from exc
    return h.quantize(Decimal("0.01"))


def phone(value) -> str:
    """US numbers to +1XXXXXXXXXX; anything else is kept as typed."""
    v = text(value)
    digits = re.sub(r"\D", "", v)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return v


def email(value) -> str:
    return text(value).lower()
