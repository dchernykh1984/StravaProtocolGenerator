"""Entry point: launch the Strava Protocol Generator desktop application.

Coverage-omitted -- it only constructs the Qt application and shows the main window.
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.main_window import ICON_PATH, MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    window = MainWindow()
    window.resize(760, 960)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
