"""Tie the pieces together: roster -> scrape -> match -> score -> render -> publish.

Everything external is injected (browser, site client, file writer), so a whole
generation runs under test without a network or a disk. ``generate`` scrapes live and
archives the raw rows; ``generate_from_snapshot`` replays an archived snapshot so a
protocol can be rebuilt after Strava stops serving that day's efforts. Both share the
build/render/publish core, so live and replayed runs produce identical protocols.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from app.config import (
    AppConfig,
    CupConfig,
    FilterType,
    Gender,
    HttpAction,
    SegmentConfig,
    StageConfig,
)
from app.html_render import (
    CupColumns,
    HtmlStyles,
    StageColumns,
    load_template,
    render_cup_protocol,
    render_stage_protocol,
)
from app.matching import match_rows_to_participants
from app.models import LeaderboardRow, Participant
from app.scoring import (
    CupEntry,
    Ranked,
    StageEntry,
    build_cup_entries,
    build_stage_entries,
    rank_entries,
)
from app.scraper import Leaderboard, scrape_windows
from app.site_api import ParticipantsResponse, SiteApiError
from app.store import SegmentStore
from app.windows import presets_for_segment

Writer = Callable[[str, str], None]


class SiteClient(Protocol):
    """The subset of ``SiteApiClient`` the pipeline uses (lets tests pass a fake)."""

    def fetch_participants(self, token: str) -> ParticipantsResponse: ...

    def upload_protocol(
        self,
        token: str,
        protocol_type: str,
        html_path: str,
        is_live: bool = ...,
        stage_label: str = ...,
    ) -> None: ...

    def delete_protocol(self, token: str, protocol_type: str) -> None: ...


class SegmentStorage(Protocol):
    """Persists each segment's accumulating store (the filesystem impl is in backup)."""

    def load(self, segment_id: str) -> SegmentStore: ...

    def commit(
        self, segment_id: str, store: SegmentStore, scraped: list[LeaderboardRow]
    ) -> None: ...


class _MemoryStorage:
    """A non-persistent storage, used when ``generate`` is called without one."""

    def __init__(self) -> None:
        self._stores: dict[str, SegmentStore] = {}

    def load(self, segment_id: str) -> SegmentStore:
        return self._stores.get(segment_id) or SegmentStore()

    def commit(
        self, segment_id: str, store: SegmentStore, scraped: list[LeaderboardRow]
    ) -> None:
        self._stores[segment_id] = store


def _default_writer(path: str, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


@dataclass
class ProtocolOutput:
    """One rendered protocol: where it was written and whether it was published."""

    kind: str  # "stage" or "cup"
    scope: str  # "absolute" or "group"
    label: str
    path: str
    published: bool = False
    error: str = ""


@dataclass
class GenerationResult:
    """The outcome of a run: written protocols, the raw snapshot, and any errors."""

    outputs: list[ProtocolOutput] = field(default_factory=list)
    raw_snapshot: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _parse_iso_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def _safe_filename(name: str) -> str:
    keep = [c if c.isalnum() or c in "-_" else "_" for c in name.strip()]
    return "".join(keep) or "protocol"


def _kept(
    entries: list[StageEntry | CupEntry], show_unregistered: bool
) -> list[StageEntry | CupEntry]:
    """Entries for a protocol: unregistered riders are dropped when hidden."""
    return [e for e in entries if e.competitor.is_registered or show_unregistered]


def _group_and_rank(
    entries: list[StageEntry | CupEntry],
    categories: list[str],
    unregistered_name: str,
    show_unregistered: bool,
) -> list[tuple[str, list[Ranked]]]:
    """Split entries into groups (categories, then the named unregistered group), rank.

    Unregistered riders are placed under ``unregistered_name`` (or dropped when
    ``show_unregistered`` is off); groups follow ``categories`` order, with the
    unregistered group last.
    """
    groups: dict[str, list[StageEntry | CupEntry]] = {}
    seen: list[str] = []
    for entry in _kept(entries, show_unregistered):
        if entry.competitor.is_registered:
            name = entry.competitor.group_name
        else:
            name = unregistered_name
        if name not in groups:
            groups[name] = []
            seen.append(name)
        groups[name].append(entry)
    order = [*categories, unregistered_name]
    ordered = [g for g in order if g in groups]
    ordered += [g for g in seen if g not in order]
    return [(name, rank_entries(groups[name])) for name in ordered]


def _rank_all(
    entries: list[StageEntry | CupEntry], show_unregistered: bool
) -> list[tuple[str, list[Ranked]]]:
    return [("", rank_entries(_kept(entries, show_unregistered)))]


def _styles(config: AppConfig) -> HtmlStyles:
    if config.template_file:
        loaded = load_template(config.template_file)
        if loaded is not None:
            return loaded
    return HtmlStyles()


def _stage_paths(config: AppConfig, stage: StageConfig) -> tuple[str, str]:
    base = Path(config.output_dir)
    abs_file = stage.absolute_file or f"{_safe_filename(stage.name)}_absolute.html"
    grp_file = stage.group_file or f"{_safe_filename(stage.name)}_group.html"
    return str(base / abs_file), str(base / grp_file)


def _cup_paths(config: AppConfig) -> tuple[str, str]:
    base = Path(config.output_dir)
    cup = config.cup
    abs_file = cup.absolute_file or f"{_safe_filename(cup.name)}_absolute.html"
    grp_file = cup.group_file or f"{_safe_filename(cup.name)}_group.html"
    return str(base / abs_file), str(base / grp_file)


def _publish(
    client: SiteClient,
    token: str,
    protocol_type: str,
    path: str,
    action: HttpAction,
    is_live: bool,
    stage_label: str,
    output: ProtocolOutput,
) -> None:
    """Apply a protocol's publish action, recording any failure on ``output``."""
    if action is HttpAction.NOTHING or not token:
        return
    try:
        if action is HttpAction.UPLOAD:
            client.upload_protocol(token, protocol_type, path, is_live, stage_label)
        else:
            client.delete_protocol(token, protocol_type)
        output.published = action is HttpAction.UPLOAD
    except SiteApiError as exc:
        output.error = str(exc)


def _emit(
    writer: Writer,
    kind: str,
    scope: str,
    label: str,
    path: str,
    html: str,
    client: SiteClient | None,
    token: str,
    action: HttpAction,
    is_live: bool,
    stage_label: str,
) -> ProtocolOutput:
    """Write one protocol locally and, when publishing, push it to the site."""
    protocol_type = "absolute" if scope == "absolute" else "group"
    writer(path, html)
    output = ProtocolOutput(kind=kind, scope=scope, label=label, path=path)
    if client is not None:
        _publish(
            client, token, protocol_type, path, action, is_live, stage_label, output
        )
    return output


def _render_stage_outputs(
    config: AppConfig,
    stage: StageConfig,
    entries: list[StageEntry],
    categories: list[str],
    styles: HtmlStyles,
    writer: Writer,
    client: SiteClient | None,
) -> list[ProtocolOutput]:
    columns = StageColumns(
        place_label=stage.place_label,
        name_label=stage.name_label,
        result_label=stage.result_label,
        show_place=stage.show_place,
        show_name=stage.show_name,
        show_gap=stage.show_gap,
        gap_label=stage.gap_label,
        show_links=config.show_strava_links,
    )
    generic: list[StageEntry | CupEntry] = list(entries)
    abs_html = render_stage_protocol(
        stage.name,
        _rank_all(generic, stage.show_unregistered),
        styles,
        columns,
        config.decimals,
        stage.race_info,
    )
    grp_html = render_stage_protocol(
        stage.name,
        _group_and_rank(
            generic, categories, stage.unregistered_group_name, stage.show_unregistered
        ),
        styles,
        columns,
        config.decimals,
        stage.race_info,
    )
    abs_path, grp_path = _stage_paths(config, stage)
    return [
        _emit(
            writer,
            "stage",
            "absolute",
            stage.name,
            abs_path,
            abs_html,
            client,
            stage.token,
            stage.absolute_action,
            stage.is_live,
            stage.stage_label,
        ),
        _emit(
            writer,
            "stage",
            "group",
            stage.name,
            grp_path,
            grp_html,
            client,
            stage.token,
            stage.group_action,
            stage.is_live,
            stage.stage_label,
        ),
    ]


def _render_cup_outputs(
    config: AppConfig,
    cup_entries: list[CupEntry],
    stage_labels: list[str],
    categories: list[str],
    styles: HtmlStyles,
    writer: Writer,
    client: SiteClient | None,
) -> list[ProtocolOutput]:
    cup: CupConfig = config.cup
    columns = CupColumns(
        place_label=cup.place_label,
        name_label=cup.name_label,
        total_label=cup.total_label,
        show_place=cup.show_place,
        show_name=cup.show_name,
        show_gap=cup.show_gap,
        gap_label=cup.gap_label,
        show_stage_gap=cup.show_stage_gap,
        stage_gap_label=cup.stage_gap_label,
        show_stage_count=cup.show_stage_count,
        stage_count_label=cup.stage_count_label,
        show_links=config.show_strava_links,
    )
    generic: list[StageEntry | CupEntry] = list(cup_entries)
    abs_html = render_cup_protocol(
        cup.name,
        _rank_all(generic, cup.show_unregistered),
        stage_labels,
        styles,
        columns,
        config.decimals,
        cup.race_info,
    )
    grp_html = render_cup_protocol(
        cup.name,
        _group_and_rank(
            generic, categories, cup.unregistered_group_name, cup.show_unregistered
        ),
        stage_labels,
        styles,
        columns,
        config.decimals,
        cup.race_info,
    )
    abs_path, grp_path = _cup_paths(config)
    return [
        _emit(
            writer,
            "cup",
            "absolute",
            cup.name,
            abs_path,
            abs_html,
            client,
            cup.token,
            cup.absolute_action,
            cup.is_live,
            cup.stage_label,
        ),
        _emit(
            writer,
            "cup",
            "group",
            cup.name,
            grp_path,
            grp_html,
            client,
            cup.token,
            cup.group_action,
            cup.is_live,
            cup.stage_label,
        ),
    ]


def _build_entries(
    config: AppConfig,
    participants: list[Participant],
    stages_rows: list[list[list[LeaderboardRow]]],
) -> tuple[list[list[StageEntry]], list[CupEntry]]:
    """Match and score already-fetched rows into per-stage entries and the cup."""
    per_stage: list[list[StageEntry]] = []
    for seg_rows in stages_rows:
        matches = [match_rows_to_participants(rows, participants) for rows in seg_rows]
        per_stage.append(build_stage_entries(matches, participants))
    cup = build_cup_entries(
        per_stage, [s.rule for s in config.stages], config.cup.cup_rule
    )
    return per_stage, cup


def _render_all(
    config: AppConfig,
    participants: list[Participant],
    categories: list[str],
    stages_rows: list[list[list[LeaderboardRow]]],
    writer: Writer,
    client: SiteClient | None,
) -> list[ProtocolOutput]:
    styles = _styles(config)
    per_stage, cup_entries = _build_entries(config, participants, stages_rows)
    outputs: list[ProtocolOutput] = []
    for stage, entries in zip(config.stages, per_stage, strict=False):
        outputs.extend(
            _render_stage_outputs(
                config, stage, entries, categories, styles, writer, client
            )
        )
    stage_labels = [s.column_label() for s in config.stages]
    outputs.extend(
        _render_cup_outputs(
            config, cup_entries, stage_labels, categories, styles, writer, client
        )
    )
    return outputs


def _snapshot(
    participants: list[Participant],
    categories: list[str],
    stages_rows: list[list[list[LeaderboardRow]]],
) -> dict[str, Any]:
    return {
        "participants": [p.__dict__ for p in participants],
        "categories": categories,
        "stages": [
            [[row.to_dict() for row in seg] for seg in stage] for stage in stages_rows
        ],
    }


def _store_key(segment: SegmentConfig) -> str:
    """The storage key for a segment: its id, suffixed by any non-default cohort.

    A different Strava cohort (gender/filter) returns different riders, so it must not
    share a store with the overall board -- otherwise a men-only stage would inherit the
    women scraped for another stage on the same segment id. The common overall/all case
    keeps the bare id, so existing stores and file names are unchanged.
    """
    if segment.gender is Gender.OVERALL and segment.filter_type is FilterType.ALL:
        return segment.segment_id
    return f"{segment.segment_id}_{segment.gender.value}_{segment.filter_type.value}"


def _segment_rows(
    segment: SegmentConfig,
    stage: StageConfig,
    leaderboard: Leaderboard,
    storage: SegmentStorage,
    today: date,
) -> list[LeaderboardRow]:
    """Scrape a segment's due windows into its store, then read the best in the range.

    A frozen stage does not scrape at all -- it just reads whatever the store already
    holds -- so a later day's run cannot overwrite captured results. Otherwise the
    windows chosen by ``app.windows`` are scraped, merged into the store (deduplicated),
    archived, and the store then yields each athlete's fastest effort within the window.
    """
    date_from = _parse_iso_date(stage.date_from)
    date_to = _parse_iso_date(stage.date_to)
    key = _store_key(segment)
    store = storage.load(key)
    if not stage.freeze_strava_data:
        presets = presets_for_segment(segment, date_from, date_to, today)
        scraped = scrape_windows(leaderboard, segment, presets) if presets else []
        if scraped:  # nothing to persist (or archive) when the board was empty
            store.merge(scraped)
            storage.commit(key, store, scraped)
    return store.best_in_range(date_from, date_to, today)


def _stage_rows(
    stage: StageConfig,
    leaderboard: Leaderboard,
    storage: SegmentStorage,
    today: date,
) -> list[list[LeaderboardRow]]:
    """The best-in-range rows for each of a stage's segments."""
    return [
        _segment_rows(segment, stage, leaderboard, storage, today)
        for segment in stage.segments
    ]


def generate(
    config: AppConfig,
    leaderboard: Leaderboard,
    client: SiteClient,
    writer: Writer = _default_writer,
    publish: bool = True,
    storage: SegmentStorage | None = None,
    today: date | None = None,
) -> GenerationResult:
    """Run a live generation: roster, scrape stages, render, publish, and snapshot.

    The roster is always fetched fresh, so late registrations (and riders who never
    registered but rode) still surface. Each segment's efforts accumulate in ``storage``
    (see ``app.store``), so results captured earlier survive Strava collapsing its
    leaderboard; without a ``storage`` the run is stateless (nothing persists).
    """
    result = GenerationResult()
    participants: list[Participant] = []
    categories: list[str] = []
    try:
        roster = client.fetch_participants(config.roster_token_effective())
        participants = roster.participants
        categories = [c.name for c in roster.categories]
    except SiteApiError as exc:
        result.errors.append(f"roster fetch failed: {exc}")

    storage = storage or _MemoryStorage()
    when = today or date.today()
    stages_rows: list[list[list[LeaderboardRow]]] = [
        _stage_rows(stage, leaderboard, storage, when) for stage in config.stages
    ]

    result.outputs = _render_all(
        config,
        participants,
        categories,
        stages_rows,
        writer,
        client if publish else None,
    )
    result.raw_snapshot = _snapshot(participants, categories, stages_rows)
    return result


def generate_from_snapshot(
    config: AppConfig,
    snapshot: dict[str, Any],
    client: SiteClient | None = None,
    writer: Writer = _default_writer,
    publish: bool = False,
) -> GenerationResult:
    """Rebuild protocols from an archived snapshot -- no scraping or roster fetch."""
    participants = [Participant.from_api(p) for p in snapshot.get("participants", [])]
    categories = list(snapshot.get("categories", []))
    stages_rows = [
        [[LeaderboardRow.from_dict(r) for r in seg] for seg in stage]
        for stage in snapshot.get("stages", [])
    ]
    result = GenerationResult(raw_snapshot=snapshot)
    result.outputs = _render_all(
        config,
        participants,
        categories,
        stages_rows,
        writer,
        client if publish else None,
    )
    return result
