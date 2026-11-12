"""Tests for nldate.parse.

Unless stated otherwise the reference date ("today") is Wednesday,
2025-12-03.
"""

from datetime import date

import pytest

from nldate import parse

TODAY = date(2025, 12, 3)  # a Wednesday


def d(year: int, month: int, day: int) -> date:
    return date(year, month, day)


ANCHORS = [
    ("today", d(2025, 12, 3)),
    ("now", d(2025, 12, 3)),
    ("tomorrow", d(2025, 12, 4)),
    ("yesterday", d(2025, 12, 2)),
    ("day after tomorrow", d(2025, 12, 5)),
    ("the day after tomorrow", d(2025, 12, 5)),
    ("the day before yesterday", d(2025, 12, 1)),
    ("  TOMORROW  ", d(2025, 12, 4)),
    ("Tomorrow at 5pm", d(2025, 12, 4)),
]

ABSOLUTE = [
    ("December 1st, 2025", d(2025, 12, 1)),
    ("Dec 1 2025", d(2025, 12, 1)),
    ("Dec. 1, 2025", d(2025, 12, 1)),
    ("1 December 2025", d(2025, 12, 1)),
    ("1st of December, 2025", d(2025, 12, 1)),
    ("the 1st of December 2025", d(2025, 12, 1)),
    ("December twenty-fifth, 2025", d(2025, 12, 25)),
    ("the twenty fifth of December 2025", d(2025, 12, 25)),
    ("Monday, December 1, 2025", d(2025, 12, 1)),
    ("2025-12-01", d(2025, 12, 1)),
    ("2025/12/01", d(2025, 12, 1)),
    ("2025-12-01T10:30:00Z", d(2025, 12, 1)),
    ("20251201", d(2025, 12, 1)),
    ("12/1/2025", d(2025, 12, 1)),
    ("12/25/2025", d(2025, 12, 25)),
    ("25/12/2025", d(2025, 12, 25)),
    ("12/25/25", d(2025, 12, 25)),
    ("1.12.2025", d(2025, 12, 1)),
    ("Dec 25", d(2025, 12, 25)),
    ("25 december", d(2025, 12, 25)),
    ("December 2025", d(2025, 12, 1)),
    ("February 29, 2024", d(2024, 2, 29)),
]

WEEKDAYS = [
    ("next Tuesday", d(2025, 12, 9)),
    ("last Tuesday", d(2025, 12, 2)),
    ("Friday", d(2025, 12, 5)),
    ("this Wednesday", d(2025, 12, 3)),
    ("next Wednesday", d(2025, 12, 10)),
    ("last Wednesday", d(2025, 11, 26)),
    ("next mon", d(2025, 12, 8)),
    ("Monday of next week", d(2025, 12, 8)),
    ("Friday of this week", d(2025, 12, 5)),
    ("Tuesday last week", d(2025, 11, 25)),
    ("next week Sunday", d(2025, 12, 14)),
    ("this coming Friday", d(2025, 12, 5)),
    ("this weekend", d(2025, 12, 6)),
    ("next weekend", d(2025, 12, 13)),
    ("the 3rd", d(2025, 12, 3)),
    ("next December", d(2026, 12, 1)),
    ("this December", d(2025, 12, 1)),
    ("last March", d(2025, 3, 1)),
    ("12/2025", d(2025, 12, 1)),
    ("exactly 5 days after December 1st 2025", d(2025, 12, 6)),
]

OFFSETS = [
    ("5 days before December 1st, 2025", d(2025, 11, 26)),
    ("1 year and 2 months after yesterday", d(2027, 2, 2)),
    ("two weeks from tomorrow", d(2025, 12, 18)),
    ("in 3 days", d(2025, 12, 6)),
    ("3 days ago", d(2025, 11, 30)),
    ("a week from today", d(2025, 12, 10)),
    ("10 days from now", d(2025, 12, 13)),
    ("in a fortnight", d(2025, 12, 17)),
    ("a year and a day after 2024-02-28", d(2025, 3, 1)),
    ("1 month after January 31, 2025", d(2025, 2, 28)),
    ("1 year after February 29, 2024", d(2025, 2, 28)),
    ("3 business days after Friday, December 5, 2025", d(2025, 12, 10)),
    ("2 business days before Monday, December 8, 2025", d(2025, 12, 4)),
    ("Friday before December 25, 2025", d(2025, 12, 19)),
    ("the Monday after December 25, 2025", d(2025, 12, 29)),
    ("2 weeks after next Tuesday", d(2025, 12, 23)),
    ("the day after the day after tomorrow", d(2025, 12, 6)),
]

PERIODS = [
    ("next week", d(2025, 12, 10)),
    ("last month", d(2025, 11, 3)),
    ("next month", d(2026, 1, 3)),
    ("next year", d(2026, 12, 3)),
    ("first day of next month", d(2026, 1, 1)),
    ("last day of this month", d(2025, 12, 31)),
    ("last day of February 2024", d(2024, 2, 29)),
    ("end of the year", d(2025, 12, 31)),
    ("beginning of next year", d(2026, 1, 1)),
    ("the 5th of next month", d(2026, 1, 5)),
    ("third Thursday of November 2025", d(2025, 11, 20)),
    ("last Friday of December 2025", d(2025, 12, 26)),
]

HOLIDAYS = [
    ("Christmas", d(2025, 12, 25)),
    ("Christmas 2026", d(2026, 12, 25)),
    ("Thanksgiving 2025", d(2025, 11, 27)),
    ("next Thanksgiving", d(2026, 11, 26)),
    ("last Halloween", d(2025, 10, 31)),
    ("3 days before Christmas 2025", d(2025, 12, 22)),
    ("the day after Thanksgiving 2025", d(2025, 11, 28)),
    ("Easter 2025", d(2025, 4, 20)),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    ANCHORS + ABSOLUTE + WEEKDAYS + OFFSETS + PERIODS + HOLIDAYS,
)
def test_parse(text: str, expected: date) -> None:
    assert parse(text, today=TODAY) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "hello",
        "not a date at all",
        "February 30, 2025",
        "13/45/2025",
        "5 days",
        "5 days after",
        "blah after tomorrow",
        "fifth Monday of February 2025",
        "next",
    ],
)
def test_unrecognised_input_raises_value_error(text: str) -> None:
    with pytest.raises(ValueError):
        parse(text, today=TODAY)


def test_returns_date_not_datetime() -> None:
    result = parse("tomorrow", today=TODAY)
    assert type(result) is date


def test_today_defaults_to_current_date() -> None:
    before = date.today()
    result = parse("today")
    after = date.today()
    assert before <= result <= after


def test_relative_expressions_use_the_given_reference_date() -> None:
    assert parse("tomorrow", today=date(2024, 2, 28)) == date(2024, 2, 29)
    assert parse("tomorrow", today=date(2023, 2, 28)) == date(2023, 3, 1)
    assert parse("next Tuesday", today=date(2025, 12, 9)) == date(2025, 12, 16)


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(TypeError):
        parse(None)  # type: ignore[arg-type]
