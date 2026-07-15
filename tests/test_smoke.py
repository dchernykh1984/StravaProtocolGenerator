"""Smoke test proving the toolchain and package import are wired up."""

import app


def test_version_is_exposed() -> None:
    assert app.__version__ == "0.1.0"
