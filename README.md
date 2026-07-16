# StravaProtocolGenerator

A desktop tool that builds competition protocols from Strava segment results and
publishes them to the cycling site, in the same spirit as the offline-referee
Finish Protocol Generator.

It signs in to Strava, reads a competition's registered roster from the site,
scrapes the configured segment leaderboards, matches riders to their registration,
computes per-stage standings and an overall cup, renders the protocols to HTML, and
optionally publishes them back to the site.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/) for dependency management
- Google Chrome (Selenium drives it only for the assisted Strava sign-in; the driver
  is resolved automatically by Selenium Manager). Leaderboards themselves are then read
  over HTTP with the saved session, no browser required.

## Setup

```bash
uv sync
```

## Running

```bash
uv run python -m app.main
```

The window loads its saved config from `data/config.json`. Fill in the Strava
credentials, the site URL, the roster token (the multi-day competition's upload
token), and configure the stages and the cup, then generate.

## How it works

- **Roster** -- fetched from the site's `/api/v1/participants/` endpoint by token,
  giving the registered riders and their categories.
- **Scraping** -- each segment's leaderboard is read over Strava's JSON endpoint, page
  by page, for the chosen date-range window(s), gender, and filter cohort. In the
  `default` date-range mode the app picks the window(s) itself from the stage's date
  range and today (see `app/windows.py`), scraping wider windows to backfill a finished
  period. Every observed effort accumulates in a per-segment store (`data/segments/`),
  so results captured earlier survive Strava collapsing its leaderboard; the protocol
  then uses each rider's fastest effort whose date falls inside the stage's range.
- **Matching** -- a leaderboard row is matched to a registration by the Strava link
  in its `additional_info` first, then by a swap-tolerant name key. Riders who match
  no registration go into a configurable "not registered" group.
- **Scoring** -- a stage value is the sum of its segment times; the cup total is the
  sum of stage values. The rule controls are designed to be extended (place, other
  algorithms) without changing callers.
- **Protocols** -- for every stage and for the cup, both an absolute and a by-group
  protocol are rendered, using the same 11-line `template.html` style format as the
  Finish Protocol Generator, so its templates apply here. All column labels are
  configurable, and the cup shows one "lap" column per stage plus a total.
- **Publishing** -- each protocol has its own action (Nothing / Upload / Delete) to
  the relevant token (per-stage broadcast token, or the overall token for the cup).
  There is no FTP; a local HTML copy is always written.

## Stages, config, and backups

- Add a stage with **Add stage**: a new tab is inserted to the right of the current
  one, copying its settings. **Delete stage** removes the current tab.
- The config is saved on **Save config** and on close. Each save also writes a
  timestamped version to `temp/` with the Strava password redacted.
- Each segment's accumulated efforts live in `data/segments/<id>.json`, and every
  scrape is snapshotted under a per-segment backup tree in `temp/segments/<id>/`, so a
  rider missing at generation time can be traced back to exactly what Strava served and
  when. A frozen stage reads its store without scraping at all.

## Tests and pre-commit

```bash
uv run pytest
uv run pre-commit install
uv run pre-commit run --all-files
```

The pure core (parsing, matching, scoring, rendering, config, backups, pipeline) is
fully covered by tests; the Selenium driver and the Qt UI are excluded from coverage.

## Contributing

- Commit messages follow the [Conventional Commits](https://www.conventionalcommits.org/)
  specification and are validated by commitizen.
- Keep each commit atomic and self-contained.
- Cover new functionality with automated tests.
- Rebase your branch on `main` before merging and keep CI green.
