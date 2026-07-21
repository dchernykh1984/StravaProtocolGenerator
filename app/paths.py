"""Resolve where the app keeps its data.

A downloaded portable build keeps its config/data next to the executable the
user ran. In development the behaviour is unchanged: data is resolved against
the current working directory, exactly as the original relative paths were.
"""

from __future__ import annotations

import sys
from pathlib import Path


def base_dir() -> Path:
    """Directory the app reads and writes its data in.

    Frozen (PyInstaller): the folder that contains the runnable, so data sits
    next to the downloaded program. On macOS the runnable lives inside
    ``<name>.app/Contents/MacOS/``, so the bundle's parent folder is used. In
    development: the current working directory (preserving the original
    relative-path behaviour).
    """
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if (
            exe.parent.name == "MacOS"
            and exe.parents[1].name == "Contents"
            and exe.parents[2].suffix == ".app"
        ):
            return exe.parents[3]
        return exe.parent
    return Path.cwd()


def app_path(*parts: str) -> Path:
    """Path to a data file/folder resolved against :func:`base_dir`."""
    return base_dir().joinpath(*parts)
