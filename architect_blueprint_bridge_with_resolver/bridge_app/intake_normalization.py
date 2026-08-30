from __future__ import annotations

from datetime import date


def normalize_birth_date(value: str, *, today: date | None = None) -> str:
    """Return a validated ISO date, expanding zero-padded/two-digit years."""
    raw = str(value or "").strip()
    parts = raw.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("Birth Date must use YYYY-MM-DD")

    year_text, month_text, day_text = parts
    if not (1 <= len(year_text) <= 4 and len(month_text) == 2 and len(day_text) == 2):
        raise ValueError("Birth Date must use YYYY-MM-DD")

    reference = today or date.today()
    year = int(year_text)
    month = int(month_text)
    day = int(day_text)

    if year < 100:
        # Choose the most recent occurrence of the two-digit year that is not
        # in the future. Examples in 2026: 99 -> 1999 and 04 -> 2004.
        year = (reference.year // 100) * 100 + year
        try:
            candidate = date(year, month, day)
        except ValueError as exc:
            raise ValueError("Birth Date is not a valid calendar date") from exc
        if candidate > reference:
            year -= 100

    if year < 1700:
        raise ValueError("Birth Date year must be 1700 or later")

    try:
        normalized = date(year, month, day)
    except ValueError as exc:
        raise ValueError("Birth Date is not a valid calendar date") from exc

    if normalized > reference:
        raise ValueError("Birth Date cannot be in the future")
    return normalized.isoformat()
