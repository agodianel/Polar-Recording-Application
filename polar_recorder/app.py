"""QApplication setup with qasync event loop integration."""

import sys
import asyncio
import logging

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
import qasync

from polar_recorder.ui.main_window import MainWindow
from polar_recorder.utils.config import AppConfig

logger = logging.getLogger(__name__)


def create_app(config: AppConfig | None = None) -> tuple[QApplication, MainWindow]:
    """Create and configure the Qt application.

    Args:
        config: Optional AppConfig. Uses defaults if not provided.

    Returns:
        Tuple of (QApplication, MainWindow).
    """
    if config is None:
        config = AppConfig()

    app = QApplication(sys.argv)

    # Set application metadata
    app.setApplicationName("PolarRecorder")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("PolarRecorder")

    # Set default font
    font = QFont("Inter", 11)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)

    # Create main window
    window = MainWindow(config)

    return app, window


def run(config: AppConfig | None = None) -> int:
    """Run the PolarRecorder application.

    Sets up the qasync event loop to bridge Qt and asyncio,
    which is required for async BLE operations within the Qt GUI.

    Args:
        config: Optional AppConfig.

    Returns:
        Application exit code.
    """
    app, window = create_app(config)
    window.show()

    # Use qasync to integrate asyncio with the Qt event loop
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    with loop:
        logger.info("PolarRecorder started")
        return loop.run_forever()
