"""Guard that app-written config never gets committed.

``data/config.json`` keeps the Strava password so it survives a restart, so the whole
``data/`` folder must stay git-ignored. This check pins that rule against regressions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _is_ignored(path: str) -> bool:
    result = subprocess.run(  # noqa: S603 - fixed args, no shell, trusted repo path
        ["git", "check-ignore", path],  # noqa: S607 - git resolved from PATH in CI
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def test_data_dir_is_git_ignored() -> None:
    assert _is_ignored("data/config.json")
    assert _is_ignored("data/rawdata_20260715.json")
