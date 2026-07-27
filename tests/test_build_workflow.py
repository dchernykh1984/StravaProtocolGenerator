"""The build workflow and the app must agree on what the app is called.

Nothing else ties the two together: the workflow stamps the name into the
macOS bundle, the app sets the same name on the Qt application, and a rename
on one side alone is exactly how the dock ended up showing the file name.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main_window import APP_DISPLAY_NAME

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"


def _workflow_env(name: str) -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(rf"^  {re.escape(name)}: *(\S.*?) *$", text, re.MULTILINE)
    assert match is not None, f"{name} is not set in {WORKFLOW.name}"
    return match.group(1)


def test_workflow_display_name_matches_the_app() -> None:
    assert _workflow_env("APP_DISPLAY_NAME") == APP_DISPLAY_NAME
