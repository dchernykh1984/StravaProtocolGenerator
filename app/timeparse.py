"""Parse Strava result-time strings to seconds and format seconds to protocol times.

Strava leaderboards render a time as ``H:MM:SS``, ``M:SS`` or a bare ``SS`` seconds
count, optionally with a decimal fraction (``M:SS.s``). Parsing normalises all of these
to float seconds; formatting mirrors FinishProtocolGenerator output (``H:MM:SS`` past an
hour, otherwise ``M:SS``), with a configurable number of decimal places.
"""

from __future__ import annotations

_MAX_DECIMALS = 4


def parse_time(text: str) -> float | None:
    """Parse a Strava time string to float seconds, or ``None`` when it is not a time.

    Accepts ``H:MM:SS``, ``M:SS`` and bare ``SS`` forms, each with an optional ``.frac``
    tail. Surrounding whitespace is ignored. Returns ``None`` for empty or unparsable
    input (e.g. a placeholder dash) rather than raising, so a stray cell does not abort
    the whole scrape.
    """
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    parts = cleaned.split(":")
    if len(parts) > 3:
        return None
    total = 0.0
    try:
        for part in parts[:-1]:
            total = total * 60 + int(part)
        total = total * 60 + float(parts[-1])
    except ValueError:
        return None
    return total


def format_time(
    seconds: float | None, decimals: int = 0, force_hours: bool = False
) -> str:
    """Format seconds as ``H:MM:SS`` / ``M:SS`` with ``decimals`` fractional digits.

    ``None`` and negative values render as an empty string (a missing or invalid time).
    ``decimals`` is clamped to ``[0, 4]`` to match the generator's cap. The hour field
    is shown once the time reaches an hour; ``force_hours`` shows it even below an hour
    (``0:53:39``), so a result column stays uniform when some riders pass the hour while
    others do not. Gaps leave it off, so a small gap stays compact.
    """
    if seconds is None or seconds < 0:
        return ""
    decimals = min(max(decimals, 0), _MAX_DECIMALS)
    factor = 10**decimals
    total = round(seconds * factor)
    frac = total % factor
    whole = total // factor
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours or force_hours:
        body = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        body = f"{minutes}:{secs:02d}"
    if decimals > 0:
        body += "." + str(frac).zfill(decimals)
    return body
