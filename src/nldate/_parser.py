"""Implementation of :func:`nldate.parse`.

The parser is a small recursive pattern matcher.  A string is normalised
(lower-cased, punctuation and times of day stripped) and then handed to
``_eval``, which tries, in order:

1. relative expressions built around a keyword (``"5 days before <date>"``,
   ``"2 weeks from tomorrow"``, ``"3 days ago"``, ``"in 2 months"``,
   ``"the Friday after <date>"``) -- the part after the keyword is parsed
   recursively, so expressions nest arbitrarily;
2. anchors (``today``, ``tomorrow``, ``yesterday`` ...);
3. weekday phrases (``next Tuesday``, ``Monday of last week``);
4. period phrases (``next month``, ``first day of next year``,
   ``end of the month``);
5. ``third Thursday of November 2025`` and ``the 5th of next month``;
6. named holidays (``Christmas 2025``, ``next Thanksgiving``);
7. absolute dates in many written forms.

Anything that is not understood raises ``ValueError``.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta


class _NoParse(ValueError):
    """Raised internally when a fragment of text is not understood."""


# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

_MONTH_NAMES = [
    ("january", "jan"),
    ("february", "feb"),
    ("march", "mar"),
    ("april", "apr"),
    ("may",),
    ("june", "jun"),
    ("july", "jul"),
    ("august", "aug"),
    ("september", "sep", "sept"),
    ("october", "oct"),
    ("november", "nov"),
    ("december", "dec"),
]
MONTHS: dict[str, int] = {
    name: number for number, names in enumerate(_MONTH_NAMES, 1) for name in names
}

_WEEKDAY_NAMES = [
    ("monday", "mon"),
    ("tuesday", "tue", "tues"),
    ("wednesday", "wed"),
    ("thursday", "thu", "thur", "thurs"),
    ("friday", "fri"),
    ("saturday", "sat"),
    ("sunday", "sun"),
]
WEEKDAYS: dict[str, int] = {
    name: number for number, names in enumerate(_WEEKDAY_NAMES) for name in names
}
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_ORDINAL_ONES = [
    "zeroth",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ORDINAL_TENS = [
    "twentieth",
    "thirtieth",
    "fortieth",
    "fiftieth",
    "sixtieth",
    "seventieth",
    "eightieth",
    "ninetieth",
]

WORD_VALUES: dict[str, int] = {}
for _value, _word in enumerate(_ONES):
    WORD_VALUES[_word] = _value
for _value, _word in enumerate(_ORDINAL_ONES):
    WORD_VALUES[_word] = _value
for _index, (_word, _ord_word) in enumerate(zip(_TENS, _ORDINAL_TENS)):
    WORD_VALUES[_word] = (_index + 2) * 10
    WORD_VALUES[_ord_word] = (_index + 2) * 10
_MULTIPLIERS = {"hundred": 100, "hundredth": 100, "thousand": 1000}

# unit -> (kind, multiplier); kind says which field of an _Offset it feeds.
_UNITS: dict[str, tuple[str, int]] = {}
for _names, _kind, _mult in [
    (("day", "days"), "days", 1),
    (("week", "weeks", "wk", "wks"), "days", 7),
    (("fortnight", "fortnights"), "days", 14),
    (("month", "months", "mo", "mos"), "months", 1),
    (("quarter", "quarters"), "months", 3),
    (("year", "years", "yr", "yrs"), "months", 12),
    (("decade", "decades"), "months", 120),
    (("century", "centuries"), "months", 1200),
    (("bday", "bdays"), "bdays", 1),
]:
    for _name in _names:
        _UNITS[_name] = (_kind, _mult)

_PERIOD_SHIFT = {
    "this": 0,
    "next": 1,
    "coming": 1,
    "upcoming": 1,
    "last": -1,
    "previous": -1,
}
_MOD = "|".join(_PERIOD_SHIFT)

# (keyword, sign, relative-to-today-when-no-base)
_RELATIVE_KEYWORDS: dict[str, tuple[int, bool]] = {
    "from now": (1, True),
    "prior to": (-1, False),
    "before": (-1, False),
    "preceding": (-1, False),
    "after": (1, False),
    "from": (1, False),
    "past": (1, False),
    "since": (1, False),
    "following": (1, False),
    "ago": (-1, True),
    "earlier": (-1, True),
    "hence": (1, True),
    "later": (1, True),
}
_RELATIVE_RE = re.compile(
    r"\b("
    + "|".join(sorted(map(re.escape, _RELATIVE_KEYWORDS), key=len, reverse=True))
    + r")\b"
)


# --------------------------------------------------------------------------
# Small date helpers
# --------------------------------------------------------------------------


def _add_months(d: date, months: int) -> date:
    """Add calendar months, clamping the day (Jan 31 + 1 month = Feb 28/29)."""
    index = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(index, 12)
    if not 1 <= year <= 9999:
        raise ValueError("date out of range")
    month = month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _add_business_days(d: date, count: int) -> date:
    step = 1 if count > 0 else -1
    remaining = abs(count)
    while remaining:
        d += timedelta(days=step)
        if d.weekday() < 5:
            remaining -= 1
    return d


def _on_or_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _strictly_after(d: date, weekday: int) -> date:
    return d + timedelta(days=(weekday - d.weekday() - 1) % 7 + 1)


def _strictly_before(d: date, weekday: int) -> date:
    return d - timedelta(days=(d.weekday() - weekday - 1) % 7 + 1)


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


def _words_to_int(words: list[str]) -> int | None:
    """Convert ``["twenty", "five"]`` (cardinal or ordinal words) to 25."""
    if not words:
        return None
    total = 0
    current = 0
    for word in words:
        if word in _MULTIPLIERS:
            if word == "thousand":
                total += max(current, 1) * 1000
                current = 0
            else:
                current = max(current, 1) * 100
        elif word in WORD_VALUES:
            current += WORD_VALUES[word]
        else:
            return None
    return total + current


def _number_from(tokens: list[str]) -> int | None:
    """Parse ``["12"]``, ``["12th"]``, ``["twenty", "fifth"]`` ... as an int."""
    if len(tokens) == 1:
        match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", tokens[0])
        if match:
            return int(match.group(1))
    return _words_to_int(tokens)


# --------------------------------------------------------------------------
# Offsets ("1 year and 2 months", "a fortnight", "three business days")
# --------------------------------------------------------------------------


@dataclass
class _Offset:
    months: int = 0
    days: int = 0
    bdays: int = 0


def _count(words: list[str]) -> int | None:
    if not words:
        return 1  # "day after tomorrow", "week before christmas"
    if words in (["a"], ["an"], ["the"]):
        return 1
    if words in (["a", "couple", "of"], ["a", "couple"], ["couple", "of"], ["couple"]):
        return 2
    return _number_from(words)


def _parse_offset(text: str) -> _Offset | None:
    text = re.sub(
        r"\b(?:(?:business|working|work)\s+days?|weekdays?)\b",
        lambda m: "bdays" if m.group(0).endswith("s") else "bday",
        text,
    )
    offset = _Offset()
    words: list[str] = []
    found = False
    for token in text.replace("-", " ").split():
        if token in {"and", "plus", "&"}:
            continue
        unit = _UNITS.get(token)
        if unit is None:
            words.append(token)
            continue
        count = _count(words)
        if count is None:
            return None
        kind, multiplier = unit
        if kind == "months":
            offset.months += count * multiplier
        elif kind == "days":
            offset.days += count * multiplier
        else:
            offset.bdays += count * multiplier
        words = []
        found = True
    if words or not found:
        return None
    return offset


def _shift(base: date, offset: _Offset, sign: int) -> date:
    result = base
    if offset.months:
        result = _add_months(result, sign * offset.months)
    if offset.days:
        result = result + timedelta(days=sign * offset.days)
    if offset.bdays:
        result = _add_business_days(result, sign * offset.bdays)
    return result


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------


def _eval(text: str, today: date) -> date:
    text = re.sub(r"^the\s+", "", text.strip())
    if not text:
        raise _NoParse("empty")
    for handler in _HANDLERS:
        result = handler(text, today)
        if result is not None:
            return result
    raise _NoParse(text)


def _relative(text: str, today: date) -> date | None:
    for match in _RELATIVE_RE.finditer(text):
        keyword = match.group(1)
        sign, defaults_to_today = _RELATIVE_KEYWORDS[keyword]
        left = re.sub(r"^in\s+", "", text[: match.start()].strip())
        right = text[match.end() :].strip()
        if not left:
            continue

        if defaults_to_today and right:
            continue
        try:
            base = today if defaults_to_today else _eval(right, today)
        except ValueError:
            continue

        offset = _parse_offset(left)
        if offset is not None:
            return _shift(base, offset, sign)

        weekday = re.fullmatch(rf"(?:the\s+)?(?:first\s+)?({_WD})", left)
        if weekday and not defaults_to_today:
            number = WEEKDAYS[weekday.group(1)]
            if sign > 0:
                return _strictly_after(base, number)
            return _strictly_before(base, number)

    in_match = re.fullmatch(r"in\s+(.+)", text)
    if in_match:
        in_offset = _parse_offset(in_match.group(1))
        if in_offset is not None:
            return _shift(today, in_offset, 1)
    return None


_ANCHOR_OFFSETS = {
    "today": 0,
    "tonight": 0,
    "now": 0,
    "tomorrow": 1,
    "tmrw": 1,
    "yesterday": -1,
}


def _anchor(text: str, today: date) -> date | None:
    match = re.fullmatch(
        r"(?:right\s+|just\s+)?(today|tonight|now|tomorrow|tmrw|yesterday)"
        r"(?:\s+(?:morning|afternoon|evening|night))?",
        text,
    )
    if match:
        return today + timedelta(days=_ANCHOR_OFFSETS[match.group(1)])
    if re.fullmatch(
        r"this\s+(?:morning|afternoon|evening|day)|eod|end of (?:the )?day", text
    ):
        return today
    if text == "last night":
        return today - timedelta(days=1)
    return None


def _weekday_phrase(text: str, today: date) -> date | None:
    match = re.fullmatch(rf"(?:({_MOD}|past)\s+)?({_WD})", text)
    if match:
        modifier, name = match.groups()
        weekday = WEEKDAYS[name]
        if modifier in (None, "this"):
            return _on_or_after(today, weekday)
        if modifier in ("last", "previous", "past"):
            return _strictly_before(today, weekday)
        return _strictly_after(today, weekday)

    match = re.fullmatch(rf"({_WD})\s+(?:(?:of|in|on)\s+)?({_MOD})\s+week", text)
    if match is None:
        match = re.fullmatch(rf"({_MOD})\s+week\s+(?:on\s+)?({_WD})", text)
        if match:
            modifier, name = match.groups()
        else:
            return None
    else:
        name, modifier = match.groups()
    monday = (
        today
        - timedelta(days=today.weekday())
        + timedelta(weeks=_PERIOD_SHIFT[modifier])
    )
    return monday + timedelta(days=WEEKDAYS[name])


def _clean_tokens(text: str) -> list[str]:
    text = text.replace(".", " ").replace("-", " ")
    return [t for t in text.split() if t not in {"of", "the", "on"}]


def _group_numbers(tokens: list[str]) -> list[str | int]:
    """Replace runs of number words by a single int; digits become ints."""
    result: list[str | int] = []
    run: list[str] = []

    def flush() -> None:
        if run:
            number = _words_to_int(run)
            if number is None:
                raise _NoParse(" ".join(run))
            result.append(number)
            run.clear()

    for token in tokens:
        if token in WORD_VALUES or token in _MULTIPLIERS:
            run.append(token)
            continue
        flush()
        digits = re.fullmatch(r"(\d+)(?:st|nd|rd|th)?", token)
        result.append(int(digits.group(1)) if digits else token)
    flush()
    return result


def _as_month(item: str | int) -> int | None:
    return MONTHS.get(item) if isinstance(item, str) else None


def _as_year(item: str | int) -> int | None:
    return item if isinstance(item, int) and 1000 <= item <= 9999 else None


def _as_day(item: str | int) -> int | None:
    return item if isinstance(item, int) and 1 <= item <= 31 else None


def _period(text: str, today: date) -> tuple[date, date] | None:
    """Return the (first day, last day) of a week/month/year expression."""
    text = re.sub(r"^the\s+", "", text)
    match = re.fullmatch(rf"(?:({_MOD})\s+)?(week|month|year|quarter)", text)
    if match:
        shift = _PERIOD_SHIFT[match.group(1) or "this"]
        unit = match.group(2)
        if unit == "week":
            start = today - timedelta(days=today.weekday()) + timedelta(weeks=shift)
            return start, start + timedelta(days=6)
        if unit == "month":
            first = _add_months(today.replace(day=1), shift)
            return _month_range(first.year, first.month)
        if unit == "year":
            year = today.year + shift
            return date(year, 1, 1), date(year, 12, 31)
        quarter_start = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        first = _add_months(quarter_start, 3 * shift)
        last_month = _add_months(first, 2)
        return _month_range(first.year, first.month)[0], _month_range(
            last_month.year, last_month.month
        )[1]

    try:
        items = _group_numbers(_clean_tokens(text))
    except _NoParse:
        return None
    if len(items) == 1:
        month_no = _as_month(items[0])
        if month_no:
            return _month_range(today.year, month_no)
        year_no = _as_year(items[0])
        if year_no:
            return date(year_no, 1, 1), date(year_no, 12, 31)
    if len(items) == 2:
        month_no, year_no = _as_month(items[0]), _as_year(items[1])
        if month_no and year_no:
            return _month_range(year_no, month_no)
    return None


def _period_phrase(text: str, today: date) -> date | None:
    match = re.fullmatch(
        rf"({_MOD})\s+(week|month|year|fortnight|quarter|decade)", text
    )
    if match:
        shift = _PERIOD_SHIFT[match.group(1)]
        unit = match.group(2)
        offset = _parse_offset(f"{abs(shift)} {unit}")
        if offset is None:  # pragma: no cover - unit is always valid
            return None
        return _shift(today, offset, 1 if shift >= 0 else -1) if shift else today

    match = re.fullmatch(rf"(?:({_MOD})\s+)?weekend", text)
    if match:
        shift = _PERIOD_SHIFT[match.group(1) or "this"]
        monday = today - timedelta(days=today.weekday())
        if shift == 0:
            return today if today.weekday() == 6 else monday + timedelta(days=5)
        return monday + timedelta(weeks=shift, days=5)

    match = re.fullmatch(
        r"(?:(first|last)\s+day|(beginning|start|end|close))\s+of\s+(.+)", text
    )
    if match:
        period = _period(match.group(3), today)
        if period is None:
            return None
        wants_last = match.group(1) == "last" or match.group(2) in ("end", "close")
        return period[1] if wants_last else period[0]
    return None


def _nth_weekday(text: str, today: date) -> date | None:
    match = re.fullmatch(
        rf"([a-z0-9]+(?:[ -][a-z]+)*?)\s+({_WD})\s+(?:of|in)\s+(.+)", text
    )
    if match is None:
        return None
    ordinal, name, rest = match.groups()
    period = _period(rest, today)
    if period is None:
        return None
    weekday = WEEKDAYS[name]
    start, end = period
    days = [
        start + timedelta(days=i)
        for i in range((end - start).days + 1)
        if (start + timedelta(days=i)).weekday() == weekday
    ]
    if ordinal == "last":
        return days[-1]
    number = _number_from(ordinal.replace("-", " ").split())
    if number is None or not 1 <= number <= len(days):
        raise _NoParse(text)
    return days[number - 1]


def _day_of_period(text: str, today: date) -> date | None:
    match = re.fullmatch(
        r"([a-z0-9]+(?:[ -][a-z0-9]+)*?)(?:\s+day)?\s+(?:of|in)\s+(.+)", text
    )
    if match is None:
        return None
    first, rest = match.groups()
    period = _period(rest, today)
    if period is None:
        return None
    start, end = period
    if first == "last":
        return end
    number = _number_from(first.replace("-", " ").split())
    if number is None or not 1 <= number <= (end - start).days + 1:
        raise _NoParse(text)
    return start + timedelta(days=number - 1)


# --------------------------------------------------------------------------
# Holidays
# --------------------------------------------------------------------------


def _nth_weekday_of(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th ``weekday`` of a month; ``n == -1`` means the last one."""
    start, end = _month_range(year, month)
    if n > 0:
        return _on_or_after(start, weekday) + timedelta(weeks=n - 1)
    return end - timedelta(days=(end.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day0 = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day0 + 1)


def _fixed(month: int, day: int) -> Callable[[int], date]:
    return lambda year: date(year, month, day)


def _floating(month: int, weekday: int, n: int) -> Callable[[int], date]:
    return lambda year: _nth_weekday_of(year, month, weekday, n)


_HOLIDAYS: dict[str, Callable[[int], date]] = {
    "new years day": _fixed(1, 1),
    "new years": _fixed(1, 1),
    "new year": _fixed(1, 1),
    "new years eve": _fixed(12, 31),
    "groundhog day": _fixed(2, 2),
    "valentines day": _fixed(2, 14),
    "valentines": _fixed(2, 14),
    "st patricks day": _fixed(3, 17),
    "saint patricks day": _fixed(3, 17),
    "april fools day": _fixed(4, 1),
    "earth day": _fixed(4, 22),
    "cinco de mayo": _fixed(5, 5),
    "juneteenth": _fixed(6, 19),
    "independence day": _fixed(7, 4),
    "halloween": _fixed(10, 31),
    "veterans day": _fixed(11, 11),
    "christmas eve": _fixed(12, 24),
    "christmas day": _fixed(12, 25),
    "christmas": _fixed(12, 25),
    "xmas": _fixed(12, 25),
    "boxing day": _fixed(12, 26),
    "mlk day": _floating(1, 0, 3),
    "martin luther king day": _floating(1, 0, 3),
    "martin luther king jr day": _floating(1, 0, 3),
    "presidents day": _floating(2, 0, 3),
    "mothers day": _floating(5, 6, 2),
    "memorial day": _floating(5, 0, -1),
    "fathers day": _floating(6, 6, 3),
    "labor day": _floating(9, 0, 1),
    "columbus day": _floating(10, 0, 2),
    "thanksgiving day": _floating(11, 3, 4),
    "thanksgiving": _floating(11, 3, 4),
    "black friday": lambda year: _nth_weekday_of(year, 11, 3, 4) + timedelta(days=1),
    "easter sunday": _easter,
    "easter": _easter,
    "good friday": lambda year: _easter(year) - timedelta(days=2),
}
_HOLIDAY_RE = re.compile(
    rf"(?:({_MOD})\s+)?({'|'.join(sorted(map(re.escape, _HOLIDAYS), key=len, reverse=True))})"
    r"(?:\s+(?:of\s+)?(\d{4}))?"
)


def _holiday(text: str, today: date) -> date | None:
    match = _HOLIDAY_RE.fullmatch(text)
    if match is None:
        return None
    modifier, name, year_text = match.groups()
    compute = _HOLIDAYS[name]
    if year_text:
        return compute(int(year_text))
    if modifier in (None, "this"):
        return compute(today.year)
    candidates = [compute(today.year + k) for k in (-1, 0, 1)]
    if _PERIOD_SHIFT[modifier] > 0:
        return min(d for d in candidates if d > today)
    return max(d for d in candidates if d < today)


# --------------------------------------------------------------------------
# Absolute dates
# --------------------------------------------------------------------------


def _two_digit_year(year: int, digits: int) -> int:
    if digits <= 2:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _month_phrase(text: str, today: date) -> date | None:
    """``next December`` / ``last march`` / ``this june``: first of that month."""
    names = "|".join(sorted(MONTHS, key=len, reverse=True))
    match = re.fullmatch(rf"({_MOD})\s+({names})", text)
    if match is None:
        return None
    shift = _PERIOD_SHIFT[match.group(1)]
    month = MONTHS[match.group(2)]
    if shift == 0:
        year = today.year
    elif shift > 0:
        year = today.year if month > today.month else today.year + 1
    else:
        year = today.year if month < today.month else today.year - 1
    return date(year, month, 1)


def _absolute(text: str, today: date) -> date | None:
    match = re.fullmatch(r"(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)", text)
    if match:
        return date(today.year, today.month, int(match.group(1)))
    match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", text)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1)
    match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return date(year, month, day)
    match = re.fullmatch(r"(\d{1,2})([/.-])(\d{1,2})(?:\2(\d{2}|\d{4}))?", text)
    if match:
        first, separator, second, year_text = match.groups()
        a, b = int(first), int(second)
        year = (
            _two_digit_year(int(year_text), len(year_text)) if year_text else today.year
        )
        if separator == "." or (a > 12 >= b):
            return date(year, b, a)  # day first
        return date(year, a, b)  # month first (US)

    tokens = _clean_tokens(text)
    if len(tokens) > 1 and tokens[0] in WEEKDAYS:
        tokens = tokens[1:]
    items = _group_numbers(tokens)

    if len(items) == 1 and (month_no := _as_month(items[0])):
        return date(today.year, month_no, 1)
    if len(items) == 2:
        first_item, second_item = items
        if (month_no := _as_month(first_item)) and (year_no := _as_year(second_item)):
            return date(year_no, month_no, 1)
        if (month_no := _as_month(first_item)) and (day_no := _as_day(second_item)):
            return date(today.year, month_no, day_no)
        if (day_no := _as_day(first_item)) and (month_no := _as_month(second_item)):
            return date(today.year, month_no, day_no)
    if len(items) == 3:
        first_item, second_item, third_item = items
        if (
            (month_no := _as_month(first_item))
            and (day_no := _as_day(second_item))
            and (year_no := _as_year(third_item))
        ):
            return date(year_no, month_no, day_no)
        if (
            (day_no := _as_day(first_item))
            and (month_no := _as_month(second_item))
            and (year_no := _as_year(third_item))
        ):
            return date(year_no, month_no, day_no)
        if (
            (year_no := _as_year(first_item))
            and (month_no := _as_month(second_item))
            and (day_no := _as_day(third_item))
        ):
            return date(year_no, month_no, day_no)
    return None


_HANDLERS: list[Callable[[str, date], date | None]] = [
    _relative,
    _anchor,
    _weekday_phrase,
    _period_phrase,
    _nth_weekday,
    _day_of_period,
    _holiday,
    _month_phrase,
    _absolute,
]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def _normalise(s: str) -> str:
    text = s.strip().lower()
    text = text.replace("’", "'").replace("'", "")
    text = re.sub(r"[‐-―]", "-", text)
    # Times of day are irrelevant to a date: "tomorrow at 5pm", "...T10:30:00Z".
    text = re.sub(
        r"\b(?:at|@)\s*(?:noon|midnight|\d{1,2}(?::\d{2}){0,2}\s*(?:a\.?m\.?|p\.?m\.?)?)",
        " ",
        text,
    )
    text = re.sub(
        r"(?<=\d)t\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?$", "", text
    )
    text = re.sub(
        r"\s+\d{1,2}(?::\d{2}){1,2}\s*(?:a\.?m\.?|p\.?m\.?)?$", "", text.strip()
    )
    text = re.sub(r"\s+\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)$", "", text.strip())
    text = text.replace(",", " ").replace(";", " ")
    text = re.sub(r"\bthis\s+(?:coming|upcoming)\b", "next", text)
    text = re.sub(r"\b(?:exactly|precisely|approximately|roughly)\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .!?")
    return re.sub(r"^(?:on|by|for)\s+", "", text)


def parse(s: str, today: date | None = None) -> date:
    """Parse a natural-language date expression into a :class:`datetime.date`.

    ``today`` is the reference point for relative expressions such as
    ``"next Tuesday"`` or ``"in 3 days"``; it defaults to the current date.

    Supported input includes absolute dates (``"December 1st, 2025"``,
    ``"2025-12-01"``, ``"12/1/2025"``), anchors (``"tomorrow"``), weekdays
    (``"next Tuesday"``, ``"Monday of last week"``), offsets from any other
    expression (``"5 days before December 1st, 2025"``, ``"1 year and 2 months
    after yesterday"``, ``"3 business days after Friday"``, ``"2 weeks ago"``),
    periods (``"first day of next month"``), ``"third Thursday of November
    2025"`` and common holidays (``"Christmas 2025"``).

    Raises:
        ValueError: if ``s`` is empty or is not recognised as a date.
        TypeError: if ``s`` is not a string.
    """
    if not isinstance(s, str):
        raise TypeError(f"expected a string, got {type(s).__name__}")
    reference = today if today is not None else date.today()
    text = _normalise(s)
    if not text:
        raise ValueError(f"not a recognised date: {s!r}")
    try:
        return _eval(text, reference)
    except _NoParse:
        raise ValueError(f"not a recognised date: {s!r}") from None
    except (OverflowError, ValueError) as error:
        raise ValueError(f"invalid date {s!r}: {error}") from None
