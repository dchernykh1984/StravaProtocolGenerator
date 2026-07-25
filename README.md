# StravaProtocolGenerator

A desktop tool that builds competition protocols from Strava segment results and
publishes them to the cycling site, in the same spirit as the offline-referee
Finish Protocol Generator.

It signs in to Strava, reads a competition's registered roster from the site,
scrapes the configured segment leaderboards, matches riders to their registration,
computes per-stage standings and an overall cup, renders the protocols to HTML, and
optionally publishes them back to the site.

## Download a ready-made app

Every release ships portable builds, so there is nothing to install and no
Python, uv or git needed. Pick the file for your platform from the
[latest release](https://github.com/dchernykh1984/StravaProtocolGenerator/releases/latest):

| Platform | File |
| --- | --- |
| Windows (Intel/AMD) | `StravaProtocolGenerator-windows-x64.exe` |
| Windows (ARM) | `StravaProtocolGenerator-windows-arm64.exe` |
| macOS (Apple Silicon) | `StravaProtocolGenerator-macos-arm64.zip` |
| Linux (Intel/AMD) | `StravaProtocolGenerator-linux-x86_64` |
| Linux (ARM64) | `StravaProtocolGenerator-linux-aarch64` |

The builds are not code-signed, so every system needs a one-off nudge before the
first launch. Each step below is done once per download, not on every start.

### macOS

Only Apple Silicon (M1 and newer) is supported - there is no Intel build.

Unpack the archive, then clear the quarantine flag that macOS puts on downloaded
files:

```bash
xattr -dr com.apple.quarantine "/path/to/StravaProtocolGenerator.app"
```

After that the app opens with a normal double-click. Without it macOS refuses to
start the app, because it is unsigned.

The flag stays cleared. Copying or moving the app on the same Mac keeps it clear,
so there is no need to repeat this for every copy. It only comes back when the app
arrives from outside again: a fresh download, AirDrop, or unpacking a
newly downloaded archive.

Rather not use a terminal? Ctrl-click the app, choose **Open**, then **Open**
again in the dialog. macOS 15 Sequoia dropped that shortcut - there, go to System
Settings -> Privacy & Security, scroll down to the notice about the blocked app
and press **Open Anyway**.

### Windows

Run the `.exe` directly. SmartScreen warns that the publisher is unknown: choose
**More info**, then **Run anyway**.

### Linux

Make the file executable and run it:

```bash
chmod +x StravaProtocolGenerator-linux-x86_64
./StravaProtocolGenerator-linux-x86_64
```

This is a GUI application, so it needs a graphical session. If it fails to start
with an error about missing Qt libraries, install them:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0
```

### Where to keep it

The program reads and writes its files (`data/config.json`, `logs/` and `temp/`) **next to itself**, so give
it a folder of its own rather than a shared downloads directory. On macOS the
files land next to the `.app` bundle, in the folder that contains it.

This is also how you run several events side by side: copy the folder per event,
and each copy keeps its own data. A symlink or a Finder alias will not work for
that - it resolves back to the original, so every "copy" would end up sharing one
set of files. Use real copies.


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
