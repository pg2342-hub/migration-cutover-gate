from decimal import Decimal

import pytest

from cutover import clean


@pytest.mark.parametrize(
    "raw,iso",
    [
        ("2025-03-04", "2025-03-04"),
        ("3/4/2025", "2025-03-04"),
        ("3/4/25", "2025-03-04"),
        ("04-Mar-25", "2025-03-04"),
        ("March 17, 2025", "2025-03-17"),
        ("Mar 17, 2025", "2025-03-17"),
        ("45740", "2025-03-24"),
    ],
)
def test_dates(raw, iso):
    assert clean.iso_date(raw) == iso


@pytest.mark.parametrize("raw", ["", "2025-02-30", "13/40/2025", "soon"])
def test_bad_dates_raise(raw):
    with pytest.raises(clean.CleanError):
        clean.iso_date(raw)


@pytest.mark.parametrize(
    "raw,value",
    [("1,250.00", "1250.00"), ("$3,400.00", "3400.00"), ("(1,250.00)", "-1250.00"), ("-40.10", "-40.10"), ("0.10", "0.10")],
)
def test_money(raw, value):
    assert clean.money(raw) == Decimal(value)


def test_money_rejects_fractions_of_a_cent_and_text():
    for raw in ("1.005", "abc", ""):
        with pytest.raises(clean.CleanError):
            clean.money(raw)


def test_thirty_dimes_are_three_dollars_exactly():
    assert sum((clean.money("0.10") for _ in range(30)), Decimal("0.00")) == Decimal("3.00")


@pytest.mark.parametrize("raw,h", [("1.5", "1.50"), ("1:30", "1.50"), ("0:45", "0.75"), ("2.25", "2.25")])
def test_hours(raw, h):
    assert clean.hours(raw) == Decimal(h)


def test_ids_stay_text():
    assert clean.legacy_id(" 00417 ") == "00417"
    assert clean.legacy_id("4012888888881881") == "4012888888881881"


@pytest.mark.parametrize("raw", ["4.01289E+15", "4-Mar", "Mar-4"])
def test_spreadsheet_damage_is_flagged(raw):
    assert clean.mangled(raw)
    with pytest.raises(clean.CleanError):
        clean.legacy_id(raw)


@pytest.mark.parametrize(
    "raw,out",
    [
        ("(312) 555-0141", "+13125550141"),
        ("312.555.0123", "+13125550123"),
        ("1-312-555-0124", "+13125550124"),
        ("ext 4", "ext 4"),
    ],
)
def test_phone(raw, out):
    assert clean.phone(raw) == out
