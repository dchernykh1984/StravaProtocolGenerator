# StravaProtocolGenerator

A desktop tool that builds competition protocols from Strava segment results and
publishes them to the cycling site, in the same spirit as the offline-referee
Finish Protocol Generator.

The planned flow: sign in to Strava, read a competition's segments and scoring
rules, scrape the relevant segment leaderboards, match them against the riders
registered on the site, compute per-stage and overall (cup) standings, and push
the finished protocol back to the site.

> Status: project scaffolding only. This repository currently contains the
> tooling (uv, pre-commit, CI, tests) and an empty `app` package. The generator
> itself is not implemented yet.

## Requirements

- Python 3.14
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

Install uv (see the uv docs for your platform), then sync the environment:

```bash
uv sync
```

This creates a local `.venv` with the runtime and development dependencies.

## Running the tests

```bash
uv run pytest
```

Tests run in parallel (pytest-xdist) and enforce a 90% coverage gate.

## Pre-commit

Install the git hooks once, then let them run on every commit:

```bash
uv run pre-commit install
```

To run all hooks against the whole tree on demand:

```bash
uv run pre-commit run --all-files
```

The hooks cover ruff (lint + format), mypy, file hygiene, a non-ASCII guard, and
conventional-commit validation (commitizen).

## Contributing

- Commit messages follow the [Conventional Commits](https://www.conventionalcommits.org/)
  specification and are validated by commitizen.
- Keep each commit atomic and self-contained.
- Cover new functionality with automated tests.
- Rebase your branch on `main` before merging and keep CI green.
