"""TrussCalc – Traversen-Berechnungsprogramm."""
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import QLockFile, Qt

from trusscalc.core.windows_integration import (
    ensure_windows_shortcuts,
    set_app_user_model_id,
)
from trusscalc.database.db_manager import init_db, _resources_path
from trusscalc.ui.main_window import MainWindow
from trusscalc.version import APP_VERSION


def main() -> None:
    set_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName("TrussCalc")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("TrussCalc")

    app_data_path = Path.home() / "TrussCalc"
    app_data_path.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(app_data_path / "trusscalc.lock"))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(0):
        sys.exit(0)
    app._trusscalc_lock = lock

    logo_path = _resources_path() / "TrussCalcLogo.png"
    icon_path = _resources_path() / "TrussCalcLogo.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    ensure_windows_shortcuts(icon_path)

    splash = None
    if logo_path.exists():
        pixmap = QPixmap(str(logo_path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                420, 420,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            splash = QSplashScreen(pixmap)
            splash.show()
            app.processEvents()

    db_path = app_data_path / "trusscalc.db"
    init_db(db_path)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    if splash is not None:
        splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
