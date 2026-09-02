# Working in StravaProtocolGenerator

A PySide6 desktop tool in the offline-referee family. It signs in to Strava, reads a
competition's registered roster from the cycling site, scrapes the configured segment
leaderboards with Selenium, matches scraped athletes to registered riders, computes
per-stage standings and an overall cup, renders the protocols to HTML, and optionally
publishes them back to the site. Sibling tools: FinishProtocolGeneratorPython (chip
timing) and StartProtocolMakerPython.

## Conventions

- Python 3.14, everything through uv: `uv run pytest`, `uv run ruff check .`,
  `uv run mypy app tests`.
- Never commit to `main`. Branch off `origin/main`, one logical change per commit.
- Commit messages: one-line Conventional Commits, no body, no `Co-Authored-By` trailer
  and no co-author line. `cz check --rev-range origin/main..HEAD` runs on every PR, and
  release-please builds `CHANGELOG.md` from these subjects, so the type matters (`fix`
  and `feat` are released; `chore`/`docs`/`test`/`style`/`refactor` are not).
- ASCII only in tracked files (`uv.lock` and `CHANGELOG.md` are exempt). A pre-commit
  hook and the `.claude` PostToolUse guard both enforce it. Chat in any language; files
  stay ASCII.
- Before committing run the full gate: `uv run pytest` (coverage gate 90%),
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app tests`.
  `uv run` may rewrite `uv.lock`; keep it out of feature commits with
  `git checkout uv.lock` unless the lock itself is the change.

## What the tests cover

`app/main.py`, `app/main_window.py` and `app/selenium_driver.py` are excluded from
coverage (`pyproject.toml`, `[tool.coverage.run]`), so the coverage number says nothing
about the window or the live scraper. Those are only as good as the Qt-level and
mocked-scraper tests - drive handlers and parsing with tests, never real Strava.

## Skills

- `shipping-a-change` - branch, commit, open the PR, watch CI to green.
- `review-cycle` - review a branch or PR and land the fixes.
- `qt-window-tests` - how to test the PySide6 window here.
- `strava-and-site` - the Strava-scrape-to-site pipeline and its data contract.
