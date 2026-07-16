"""A local, accumulating store of the efforts scraped for one Strava segment.

Strava's leaderboard is lossy: for a given window it returns only each athlete's best
effort in that window, so a rider whose window-best falls outside the race dates is lost
once the window moves on. This store keeps every effort we have ever observed for a
segment (deduplicated), so a protocol is built from the accumulated history, not a
single collapsing snapshot -- ``best_in_range`` then picks each athlete's fastest effort
whose date falls inside the collection window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.leaderboard import filter_by_date
from app.models import LeaderboardRow


def _dedup_key(row: LeaderboardRow) -> tuple[str, str]:
    """Identity of one observed effort: athlete plus the activity behind it.

    The effort (activity) link uniquely identifies an attempt; when it is missing we
    fall back to the date and time so two different efforts still count separately.
    """
    activity = row.attempt_url or f"{row.date}|{row.result_seconds}"
    return (row.athlete_id, activity)


def _group_key(row: LeaderboardRow) -> str:
    """Key an effort to its athlete for reduction (id, else a normalised name)."""
    return row.athlete_id or f"name:{row.athlete_name.strip().lower()}"


def _faster(candidate: LeaderboardRow, current: LeaderboardRow) -> bool:
    """True when ``candidate`` is a strictly faster valid effort than ``current``."""
    if candidate.result_seconds is None:
        return False
    if current.result_seconds is None:
        return True
    return candidate.result_seconds < current.result_seconds


@dataclass
class SegmentStore:
    """Every effort observed for one segment, deduplicated by (athlete, activity)."""

    rows: list[LeaderboardRow] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SegmentStore:
        # Tolerate a corrupt or partially written store (null/wrong-typed rows) rather
        # than crashing a whole generation, like the config loaders do.
        raw = (data or {}).get("rows")
        rows = raw if isinstance(raw, list) else []
        return cls(
            rows=[LeaderboardRow.from_dict(r) for r in rows if isinstance(r, dict)]
        )

    def to_dict(self) -> dict[str, Any]:
        return {"rows": [row.to_dict() for row in self.rows]}

    def merge(self, rows: list[LeaderboardRow]) -> int:
        """Add efforts not seen before; return how many were new (keeps first seen)."""
        seen = {_dedup_key(row) for row in self.rows}
        added = 0
        for row in rows:
            key = _dedup_key(row)
            if key not in seen:
                seen.add(key)
                self.rows.append(row)
                added += 1
        return added

    def best_in_range(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        today: date | None = None,
    ) -> list[LeaderboardRow]:
        """Each athlete's fastest observed effort within ``[date_from, date_to]``.

        The date window is applied with the same rules as a live scrape (inclusive, open
        on a ``None`` side, undated efforts kept), then efforts collapse per athlete to
        the fastest one. The result is sorted fastest-first (timeless efforts last).
        """
        in_range = filter_by_date(self.rows, date_from, date_to, today)
        best: dict[str, LeaderboardRow] = {}
        for row in in_range:
            key = _group_key(row)
            current = best.get(key)
            if current is None or _faster(row, current):
                best[key] = row
        return sorted(
            best.values(),
            key=lambda r: (r.result_seconds is None, r.result_seconds or 0.0),
        )
