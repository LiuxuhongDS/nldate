# nldate

Turn natural-language date expressions into `datetime.date` objects.

```python
from datetime import date
from nldate import parse

parse("5 days before December 1st, 2025")  # date(2025, 11, 26)
parse("1 year and 2 months after yesterday")  # relative to today
parse("next Tuesday", today=date(2025, 12, 3))  # date(2025, 12, 9)
parse("third Thursday of November 2025")  # date(2025, 11, 20)
parse("gibberish")  # raises ValueError
```

`parse(s, today=None)` raises `ValueError` for anything it does not recognise
(including the empty string). `today` is the reference point for relative
expressions and defaults to `date.today()`.

## Supported input

- **Absolute dates**: `December 1st, 2025`, `Dec 1 2025`, `1 December 2025`,
  `the 1st of December`, `Monday, December 1, 2025`, `2025-12-01`, `12/1/2025`,
  `25/12/2025`, `20251201`, `December twenty-fifth, 2025`, `Dec 2025`
  (a missing year means the year of `today`).
- **Anchors**: `today`, `tomorrow`, `yesterday`, `day after tomorrow`,
  `tomorrow at 5pm` (times of day are ignored).
- **Weekdays**: `Friday`, `next Tuesday`, `last Friday`, `Monday of next week`,
  `Tuesday last week`, `this weekend`.
  `next X` / `last X` are the first X strictly after / before `today`.
- **Offsets** from any other expression: `5 days before <date>`,
  `two weeks from tomorrow`, `1 year and 2 months after yesterday`,
  `in 3 days`, `a week ago`, `3 business days after Friday`,
  `the Monday after <date>`. Months/years clamp to the end of short months
  (`1 month after January 31` is February 28).
- **Periods**: `next week/month/year`, `first day of next month`,
  `last day of February 2024`, `end of the year`, `the 5th of next month`,
  `third Thursday of November 2025`, `last Friday of the month`.
- **Holidays**: `Christmas`, `Thanksgiving 2025`, `next Halloween`, `Easter 2025`, ...

## Development

```
uv sync
uv run pytest
uv run mypy src/
uv run ruff check
uv run ruff format --check
```
