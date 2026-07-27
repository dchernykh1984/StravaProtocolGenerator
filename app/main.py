"""Entry point: launch the Strava Protocol Generator desktop application.

Coverage-omitted -- it only constructs the Qt application and shows the main window.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import (
    APP_DESKTOP_NAME,
    APP_DISPLAY_NAME,
    ICON_PATH,
    MainWindow,
)


def configure_app_identity(app: QApplication) -> None:
    """Tell the OS shell what this app is called.

    Without this the name defaults to the basename of argv[0] - the artifact
    file name, suffixed with the platform - so the Linux taskbar labels the
    window ``StravaProtocolGenerator-linux-x86_64``.
    """
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setDesktopFileName(APP_DESKTOP_NAME)


def main() -> int:
    app = QApplication(sys.argv)
    configure_app_identity(app)
    app.setWindowIcon(QIcon(ICON_PATH))
    window = MainWindow()
    window.resize(760, 960)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
