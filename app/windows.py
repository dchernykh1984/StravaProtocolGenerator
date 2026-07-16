"""Choose which Strava leaderboard windows to scrape for a stage's date range.

Strava only offers trailing presets (today / this week / month / year, all ending at
"now"), never an arbitrary past day. To cover a stage's ``[date_from, date_to]`` we
pick, in ``DEFAULT`` mode, every preset from the narrowest that still reaches the period
up to the narrowest that fully covers its start. Scraping several widths and merging
them (see ``app.store``) recovers riders whose best effort in a wider window fell
outside the period, because a narrower window may have caught their in-period effort.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.config import DateRange, SegmentConfig

# Narrowest to widest; ``DEFAULT`` is resolved into these and is not itself a window.
_ORDER = (
    DateRange.TODAY,
    DateRange.THIS_WEEK,
    DateRange.THIS_MONTH,
    DateRange.THIS_YEAR,
    DateRange.ALL_TIME,
)


def _window_start(preset: DateRange, today: date) -> date:
    """The first day covered by ``preset``'s trailing window ending at ``today``."""
    if preset is DateRange.TODAY:
        return today
    if preset is DateRange.THIS_WEEK:
        return today - timedelta(days=today.weekday())
    if preset is DateRange.THIS_MONTH:
        return today.replace(day=1)
    if preset is DateRange.THIS_YEAR:
        return today.replace(month=1, day=1)
    return date.min  # ALL_TIME reaches back forever


def window_presets(
    date_from: date | None, date_to: date | None, today: date
) -> list[DateRange]:
    """The presets to scrape today to cover ``[date_from, date_to]`` (may be empty).

    With no bounds at all the whole board is wanted, so only ``ALL_TIME`` is scraped.
    Nothing is scraped before the period starts. Otherwise every preset whose window
    reaches into the period is taken, stopping once one covers the period's start.
    """
    if date_from is None and date_to is None:
        return [DateRange.ALL_TIME]
    lo = date_from or date.min
    hi = date_to or date.max
    if today < lo:
        return []  # the period has not started; nothing to capture yet
    presets: list[DateRange] = []
    for preset in _ORDER:
        start = _window_start(preset, today)
        if start > hi:
            continue  # this window lies entirely after the period
        presets.append(preset)
        if start <= lo:
            break  # covers the period's start; wider windows add nothing
    return presets


def presets_for_segment(
    segment: SegmentConfig,
    date_from: date | None,
    date_to: date | None,
    today: date,
) -> list[DateRange]:
    """Windows to scrape: auto-chosen in ``DEFAULT`` mode, else the one preset set."""
    if segment.date_range is DateRange.DEFAULT:
        return window_presets(date_from, date_to, today)
    return [segment.date_range]
