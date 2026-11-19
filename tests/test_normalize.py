import pytest

from docai.normalize import find_auto_renewal, find_dates, find_days, find_money, find_months, normalize_value
from docai.schema import FieldType


@pytest.mark.parametrize(
    "text, expected",
    [
        ("entered into as of March 4, 2025 (the", [{"2025-03-04"}]),
        ("as of 4 March 2025", [{"2025-03-04"}]),
        ("as of 2025-03-04", [{"2025-03-04"}]),
        ("as of 03/04/2025", [{"2025-03-04", "2025-04-03"}]),
        ("as of 03/25/2025", [{"2025-03-25"}]),
    ],
)
def test_find_dates(text, expected):
    assert [set(g) for g in find_dates(text)] == expected


def test_months_from_words_digits_and_years():
    assert find_months("is twenty-four (24) months, beginning") == [frozenset({"24"})]
    assert find_months("is three (3) years, beginning") == [frozenset({"36"})]
    assert find_months("for 18 months") == [frozenset({"18"})]
    assert find_months("twenty-four months") == [frozenset({"24"})]


def test_renewal_period_is_not_a_term_candidate():
    assert find_months("renew for successive twelve (12) month periods") == []


def test_days():
    assert find_days("upon thirty (30) days' prior written notice") == [frozenset({"30"})]
    assert find_days("within ninety days") == [frozenset({"90"})]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("is $240,000.00 (the", "USD 240000.00"),
        ("is USD 240,000 (the", "USD 240000.00"),
        ("is EUR 95,000.00", "EUR 95000.00"),
        ("is GBP 120,500.00", "GBP 120500.00"),
        ("is 75,000 USD", "USD 75000.00"),
    ],
)
def test_find_money(text, expected):
    assert find_money(text) == [frozenset({expected})]


def test_auto_renewal_polarity():
    assert find_auto_renewal("This Agreement shall automatically renew for successive periods.") == [frozenset({"true"})]
    assert find_auto_renewal("This Agreement shall not renew automatically.") == [frozenset({"false"})]
    assert find_auto_renewal("Any extension requires a written amendment.") == []


@pytest.mark.parametrize(
    "field_type, raw, expected",
    [
        (FieldType.DATE, "2025-03-04", "2025-03-04"),
        (FieldType.DATE, "March 4, 2025", "2025-03-04"),
        (FieldType.MONTHS, "24", "24"),
        (FieldType.MONTHS, "two (2) years", "24"),
        (FieldType.DAYS, 30, "30"),
        (FieldType.MONEY, "USD 240000.00", "USD 240000.00"),
        (FieldType.MONEY, "240000", "USD 240000.00"),
        (FieldType.BOOL, "True", "true"),
        (FieldType.TEXT, "Cedar Ridge Software, Inc.", "cedar ridge software inc"),
        (FieldType.DATE, "not found", None),
        (FieldType.MONEY, "a lot", None),
    ],
)
def test_normalize_value(field_type, raw, expected):
    assert normalize_value(field_type, raw) == expected
