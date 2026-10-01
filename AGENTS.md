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
  hook and the `.codex` PostToolUse guard both enforce it. Chat in any language; files
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

## Coding agent context

Codex reads this `AGENTS.md` at startup and discovers skills in `.agents/skills/`.
Read the relevant skill before using its workflow. Claude keeps `CLAUDE.md`,
`.claude/skills/` and its own settings; update both guides and skill copies when a
shared convention changes.

`.codex/hooks.json` checks edited files after `apply_patch`, including multi-file
patches and moves, using the pre-commit ASCII patterns and exclusions.
Run `python3 .codex/hooks/test_post_edit.py` to verify the handler; pre-commit
runs these tests too. Post-edit hooks report completed edits; they do not undo
them. Shell writes still require the pre-commit gate.

Project hooks require a trusted project and review of the current hook definition
in `/hooks`. Changed definitions require renewed review, and hooks must remain
enabled in local Codex configuration. Repository files do not grant trust or
change user-level settings. Existing Claude hooks remain in place.

Claude permission allowlists and attribution settings are not Codex settings.
Codex uses its own native permissions and approvals. An explicit user request to
push and open a pull request authorizes those actions for that task; never merge,
tag or release unless the user asks for it.
