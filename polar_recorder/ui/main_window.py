"""Main application window for PolarRecorder.

Orchestrates the connection panel, recording panel, and live charts.
Bridges async BLE operations with the Qt event loop.
"""

import asyncio
import html
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QStatusBar,
    QMessageBox,
    QTabWidget,
    QPlainTextEdit,
    QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Slot, QObject, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from polar_recorder.ble.scanner import PolarScanner
from polar_recorder.ble.device import PolarDeviceManager
from polar_recorder.ble.data_models import DeviceInfo, ECGSample, ACCSample, HRSample
from polar_recorder.recording.session import RecordingSession
from polar_recorder.ui.connection_panel import ConnectionPanel
from polar_recorder.ui.recording_panel import RecordingPanel, MARKER_EVENT, format_duration
from polar_recorder.ui.live_charts import (
    ECGChartWidget,
    ACCChartWidget,
    HRChartWidget,
    setup_pyqtgraph,
)
from polar_recorder.ui.styles import COLORS, build_stylesheet
from polar_recorder.utils.config import APP_VERSION, AppConfig
from polar_recorder.utils.rate_meter import RateMeter

logger = logging.getLogger(__name__)

# A stream that delivers nothing for this long is flagged as "no data"
STALE_DATA_SEC = 3.0


class _LogBridge(QObject):
    message = Signal(int, str, str)  # levelno, UI level, text


class QtLogHandler(logging.Handler):
    """Forwards app log records to the Log tab via a (thread-safe) Qt signal."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.bridge = _LogBridge()
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(
                record.levelno, getattr(record, "ui_level", ""), self.format(record)
            )
        except Exception:
            self.handleError(record)


def _dir_size(path: Optional[Path]) -> int:
    if path is None or not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.iterdir() if f.is_file())


class MainWindow(QMainWindow):
    """Main PolarRecorder application window.

    Layout:
    ┌─────────────────────────────────────────────────────────────┐
    │ Header Bar                                        ● REC 0:00 │
    ├──────────────┬──────────────────────────────────────────────┤
    │  Device      │  ┌── ECG Chart ────────────────────────────┐ │
    │              │  └─────────────────────────────────────────┘ │
    │  Streams     │  ┌── ACC Chart ────────────────────────────┐ │
    │  Recording   │  └─────────────────────────────────────────┘ │
    │  Markers     │  ┌── HR Chart  ────────────────────────────┐ │
    │  Stats       │  └─────────────────────────────────────────┘ │
    ├──────────────┴──────────────────────────────────────────────┤
    │ Status Bar                                                   │
    └─────────────────────────────────────────────────────────────┘
    """

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.config.ensure_dirs()

        # Core components
        self._scanner = PolarScanner()
        self._device_manager = PolarDeviceManager()
        self._session: RecordingSession | None = None
        self._scan_task: asyncio.Future | None = None
        self._tasks: set[asyncio.Future] = set()
        self._closing = False
        self._shutdown_complete = False

        # Live stream health
        self._rates = {"ecg": RateMeter(), "acc": RateMeter(), "hr": RateMeter()}
        self._stream_stale = {key: False for key in self._rates}
        self._streams_started_at: float | None = None
        self._first_hr_seen = False
        self._last_contact: bool | None = None

        # Configure pyqtgraph
        setup_pyqtgraph()

        # Setup UI
        self._setup_window()
        self._setup_layout()
        self._setup_status_bar()
        self._setup_logging()
        self._setup_timers()
        self._setup_shortcuts()
        self._connect_signals()
        self._setup_ble_callbacks()

    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle("PolarRecorder — Polar H10 Data Acquisition")
        self.setMinimumSize(1100, 720)
        self.resize(1440, 900)
        self.setStyleSheet(build_stylesheet())

    def _setup_layout(self):
        """Create the main layout with splitter."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(8)

        # ─── Header ─────────────────────────────────────────────────
        header = QHBoxLayout()

        title_layout = QVBoxLayout()
        title_layout.setSpacing(0)
        title = QLabel("POLAR RECORDER")
        title.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 20px; "
            f"font-weight: 800; letter-spacing: 3px; background: transparent;"
        )
        subtitle = QLabel(f"Polar H10 ECG band — data acquisition & live visualization  ·  v{APP_VERSION}")
        subtitle.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        header.addLayout(title_layout)
        header.addStretch()

        # Recording indicator with elapsed time (blinks while recording)
        self._rec_pill = QLabel()
        self._rec_pill.hide()
        self._blink_state = False
        header.addWidget(self._rec_pill, 0, Qt.AlignVCenter)

        main_layout.addLayout(header)

        # ─── Main Splitter (sidebar | charts) ───────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setChildrenCollapsible(False)

        # Left sidebar, scrollable so it works on small screens
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 10, 0)
        sidebar_layout.setSpacing(4)

        self._connection_panel = ConnectionPanel()
        sidebar_layout.addWidget(self._connection_panel)

        self._recording_panel = RecordingPanel(self.config)
        sidebar_layout.addWidget(self._recording_panel)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidget(sidebar)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setMinimumWidth(370)
        sidebar_scroll.setMaximumWidth(480)
        splitter.addWidget(sidebar_scroll)

        # Right side: charts in tabs
        self._tab_widget = QTabWidget()

        charts_tab = QWidget()
        charts_layout = QVBoxLayout(charts_tab)
        charts_layout.setContentsMargins(10, 10, 10, 10)
        charts_layout.setSpacing(10)

        self._ecg_chart = ECGChartWidget(
            window_seconds=self.config.charts.ecg_window_seconds
        )
        charts_layout.addWidget(self._ecg_chart, 3)

        self._acc_chart = ACCChartWidget(
            window_seconds=self.config.charts.acc_window_seconds,
            sample_rate=self.config.streams.acc.sample_rate,
        )
        charts_layout.addWidget(self._acc_chart, 2)

        self._hr_chart = HRChartWidget(
            window_seconds=self.config.charts.hr_window_seconds
        )
        charts_layout.addWidget(self._hr_chart, 2)

        self._tab_widget.addTab(charts_tab, "Live charts")

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(5000)
        self._tab_widget.addTab(self._log_text, "Log")

        splitter.addWidget(self._tab_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 1050])

        main_layout.addWidget(splitter, 1)

    def _setup_status_bar(self):
        """Create the status bar."""
        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.setStatusBar(status)
        self._status_label = QLabel("Ready — scan for a Polar H10 to begin")
        status.addWidget(self._status_label, 1)

    def _setup_logging(self):
        """Mirror the app's log output into the Log tab."""
        self._log_handler = QtLogHandler()
        self._log_handler.bridge.message.connect(self._append_log)
        app_logger = logging.getLogger("polar_recorder")
        if app_logger.getEffectiveLevel() > logging.INFO:
            app_logger.setLevel(logging.INFO)
        app_logger.addHandler(self._log_handler)

    def _setup_timers(self):
        """Setup periodic timers for chart updates and stats."""
        # Chart update timer (~30 FPS)
        self._chart_timer = QTimer(self)
        self._chart_timer.setInterval(self.config.charts.update_rate_ms)
        self._chart_timer.timeout.connect(self._update_charts)
        self._chart_timer.start()

        # Stats / stream health update timer (1 Hz)
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

        # Recording indicator blink timer
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink_recording_indicator)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self._recording_panel.add_event_marker)
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, activated=self._recording_panel.toggle_segment)

    def _connect_signals(self):
        """Connect UI signals to handler methods."""
        # Connection panel
        self._connection_panel.scan_requested.connect(self._on_scan)
        self._connection_panel.stop_scan_requested.connect(self._scanner.stop)
        self._connection_panel.connect_requested.connect(self._on_connect)
        self._connection_panel.disconnect_requested.connect(self._on_disconnect)

        # Recording panel
        self._recording_panel.record_requested.connect(self._on_start_recording)
        self._recording_panel.stop_requested.connect(self._on_stop_recording)
        self._recording_panel.marker_requested.connect(self._on_add_marker)

    def _setup_ble_callbacks(self):
        """Configure BLE device manager callbacks."""
        self._device_manager.set_data_callbacks(
            ecg_callback=self._on_ecg_data,
            acc_callback=self._on_acc_data,
            hr_callback=self._on_hr_data,
        )

        self._device_manager.set_connection_callbacks(
            on_connected=self._on_ble_connected,
            on_disconnected=self._on_ble_disconnected,
            on_error=self._on_ble_error,
        )

    # ─── Helpers ────────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "info"):
        """Log a message; it also appears in the Log tab. level: info/success/warning/error."""
        levelno = {"warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO)
        logger.log(levelno, message, extra={"ui_level": level})

    @Slot(int, str, str)
    def _append_log(self, levelno: int, ui_level: str, text: str):
        """Add a timestamped message to the log panel."""
        if ui_level == "success":
            color = COLORS["success"]
        elif levelno >= logging.ERROR:
            color = COLORS["error"]
        elif levelno >= logging.WARNING:
            color = COLORS["warning"]
        else:
            color = COLORS["text_secondary"]
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        body = html.escape(text).replace("\n", "<br>")
        self._log_text.appendHtml(
            f'<span style="color:{COLORS["text_muted"]}">[{timestamp}]</span> '
            f'<span style="color:{color}">{body}</span>'
        )

    def _set_status(self, text: str):
        self._status_label.setText(text)

    def _show_message(self, icon: QMessageBox.Icon, title: str, text: str):
        """Show a dialog without blocking the event loop (BLE data keeps flowing)."""
        box = QMessageBox(icon, title, text, QMessageBox.Ok, self)
        box.setAttribute(Qt.WA_DeleteOnClose)
        box.open()

    def _spawn(self, coro) -> asyncio.Future:
        """Run a coroutine on the event loop, keeping a reference so it isn't GC'd."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return task

    def _on_task_done(self, task: asyncio.Future):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background task failed", exc_info=task.exception())

    # ─── Scan Handlers ──────────────────────────────────────────────────

    @Slot()
    def _on_scan(self):
        """Handle scan button click — start BLE scanning."""
        if self._scan_task and not self._scan_task.done():
            return
        self._connection_panel.set_scanning(True)
        self._set_status("Scanning for Polar devices…")
        self._scan_task = self._spawn(self._do_scan())

    async def _do_scan(self):
        """Async BLE scan coroutine."""
        try:
            self._scanner.set_callback(self._on_device_found)
            devices = await self._scanner.scan()
            if self._connection_panel.state == ConnectionPanel.SCANNING:
                self._set_status(
                    f"Scan complete — {len(devices)} device(s) found"
                    if devices else
                    "No Polar devices found — is the strap worn and not connected to another device?"
                )
        except Exception as e:
            self._set_status(f"Scan failed — is Bluetooth enabled? ({e})")
        finally:
            self._connection_panel.set_scanning(False)

    def _on_device_found(self, device: DeviceInfo):
        """Callback when a Polar device is discovered during scanning."""
        self._connection_panel.add_device(device)

    # ─── Connection Handlers ────────────────────────────────────────────

    @Slot(object)
    def _on_connect(self, device_info: DeviceInfo):
        """Handle connect request for a specific device."""
        if self._device_manager.is_busy:
            return
        self._connection_panel.set_connecting(device_info)
        self._recording_panel.set_streams_locked(True)
        self._set_status(f"Connecting to {device_info.name}…")
        self._spawn(self._do_connect(device_info))

    async def _do_connect(self, device_info: DeviceInfo):
        """Async connection coroutine."""
        # BLE backends don't reliably connect while a scan is running
        if self._scan_task and not self._scan_task.done():
            self._scanner.stop()
            await asyncio.wait([self._scan_task])

        if not await self._device_manager.connect(device_info):
            return

        # Start streams immediately after connecting
        stream_config = self._recording_panel.get_stream_config()
        try:
            errors = await self._device_manager.start_streams(stream_config)
        except Exception as e:
            errors = [str(e)]
        if not self._device_manager.is_connected:
            return  # Link dropped while starting; _on_ble_disconnected updated the UI

        active = self._device_manager.active_stream_config
        self._streams_started_at = time.monotonic()
        for meter in self._rates.values():
            meter.reset()
        if active and active.acc.enabled:
            self._acc_chart.set_sample_rate(active.acc.sample_rate)

        if self._device_manager.is_streaming:
            self._recording_panel.set_can_record(True)
            if errors:
                self._log("Some streams failed to start: " + "; ".join(errors), "warning")
                self._set_status(f"Connected — {device_info.name} (some streams failed, see Log)")
            else:
                self._log("All data streams started", "success")
                self._set_status(f"Connected — streaming from {device_info.name}")
        else:
            self._recording_panel.set_can_record(False, "No data streams are running")
            self._set_status("Connected, but no data streams could be started")
            self._show_message(
                QMessageBox.Warning,
                "Streams not started",
                "The strap is connected but no data streams could be started:\n\n"
                + "\n".join(errors)
                + "\n\nTry disconnecting and connecting again.",
            )

    @Slot()
    def _on_disconnect(self):
        """Handle disconnect request."""
        self._stop_recording("disconnected")
        self._set_status("Disconnecting…")
        self._spawn(self._device_manager.disconnect())

    def _on_ble_connected(self):
        """Callback when BLE connection is established."""
        device = self._device_manager.device_info
        self._connection_panel.set_connected(device, self._device_manager.battery_level)
        self._recording_panel.set_can_record(False, "Starting data streams…")
        self._ecg_chart.reset()
        self._acc_chart.reset()
        self._hr_chart.reset()
        self._first_hr_seen = False
        self._last_contact = None
        self._stream_stale = {key: False for key in self._rates}
        self._set_status(f"Connected — {device.name}, starting streams…")

    def _on_ble_disconnected(self, unexpected: bool):
        """Callback when the BLE connection ends (user-initiated or lost)."""
        session_dir = None
        if self._session and self._session.is_active:
            self._on_add_marker(MARKER_EVENT, "connection lost")
            session_dir = self._stop_recording("connection_lost")

        self._connection_panel.set_disconnected()
        self._recording_panel.set_streams_locked(False)
        self._recording_panel.set_can_record(False, "Connect a device to start recording")
        self._streams_started_at = None
        # Don't leave the last values on screen looking live
        self._ecg_chart.reset()
        self._acc_chart.reset()
        self._hr_chart.reset()

        if unexpected:
            self._set_status("Connection lost")
            text = (
                "The connection to the Polar H10 was lost "
                "(out of range, battery, or the strap lost skin contact)."
            )
            if session_dir:
                text += f"\n\nThe recording was stopped and saved to:\n{session_dir}"
            if not self._closing:
                self._show_message(QMessageBox.Warning, "Connection lost", text)
        else:
            self._set_status("Disconnected")

    def _on_ble_error(self, error_msg: str):
        """Callback for connection errors (already logged by the device manager)."""
        self._connection_panel.set_disconnected()
        self._recording_panel.set_streams_locked(False)
        self._set_status("Connection failed — see Log for details")
        if not self._closing:
            self._show_message(QMessageBox.Warning, "Connection failed", error_msg)

    # ─── Recording Handlers ─────────────────────────────────────────────

    @Slot()
    def _on_start_recording(self):
        """Start a new recording session."""
        if self._session and self._session.is_active:
            return
        active = self._device_manager.active_stream_config
        if not self._device_manager.is_connected or active is None:
            self._log("Cannot record — no device streaming", "error")
            return

        device_info = self._device_manager.device_info
        self._session = RecordingSession(
            device_info=device_info,
            config=self.config.recording,
            stream_config=active,
            label=self._recording_panel.session_label(),
            battery_level=self._device_manager.battery_level,
        )

        try:
            session_dir = self._session.start()
        except OSError as e:
            self._session = None
            self._log(f"Could not start recording: {e}", "error")
            self._show_message(
                QMessageBox.Critical, "Cannot start recording",
                f"Could not create the session files:\n{e}",
            )
            return

        self._recording_panel.set_recording(True, session_dir)
        self._update_rec_pill(0)
        self._rec_pill.show()
        self._blink_timer.start()

        self._log(f"Recording started → {session_dir}", "success")
        self._set_status(f"Recording — {device_info.name} → {session_dir.name}")

    @Slot()
    def _on_stop_recording(self):
        self._stop_recording("user")

    def _stop_recording(self, reason: str) -> Optional[Path]:
        """Stop the current recording session. Returns its folder, or None if none was active."""
        if not (self._session and self._session.is_active):
            return None

        stats = self._session.stop(reason)
        session_dir = self._session.session_dir
        self._session = None

        stats["size_bytes"] = _dir_size(session_dir)
        self._recording_panel.update_stats(stats)
        self._recording_panel.set_recording(False, session_dir)
        self._rec_pill.hide()
        self._blink_timer.stop()

        self._log(
            f"Recording saved → {session_dir} ({format_duration(stats['duration_sec'])})",
            "success",
        )
        self._set_status(f"Recording saved to {session_dir}")
        return session_dir

    @Slot(str, str)
    def _on_add_marker(self, marker_type: str, label: str):
        """Add a marker to the current recording."""
        if not (self._session and self._session.is_active):
            return
        try:
            marker = self._session.add_marker(marker_type, label)
        except OSError as e:
            self._handle_write_error(e)
            return
        if marker:
            self._recording_panel.add_marker_entry(
                self._session.duration_seconds, marker_type, marker.label
            )

    def _record(self, write: Callable, sample) -> None:
        """Pass a sample to the active session, stopping it cleanly if the disk fails."""
        session = self._session
        if session is None or not session.is_active:
            return
        try:
            write(session, sample)
        except OSError as e:
            self._handle_write_error(e)

    def _handle_write_error(self, error: OSError):
        session_dir = self._stop_recording("write_error")
        self._log(f"Writing recording data failed: {error}", "error")
        self._show_message(
            QMessageBox.Critical,
            "Recording stopped",
            f"Writing to disk failed:\n{error}\n\n"
            f"The data recorded so far was kept in:\n{session_dir}",
        )

    # ─── Data Handlers ──────────────────────────────────────────────────

    def _on_ecg_data(self, sample: ECGSample):
        """Handle incoming ECG data from the BLE device."""
        self._ecg_chart.add_samples(sample.samples_uv)
        self._rates["ecg"].add(len(sample.samples_uv))
        self._record(RecordingSession.write_ecg, sample)

    def _on_acc_data(self, sample: ACCSample):
        """Handle incoming accelerometer data from the BLE device."""
        self._acc_chart.add_samples(sample.samples_mg)
        self._rates["acc"].add(len(sample.samples_mg))
        self._record(RecordingSession.write_acc, sample)

    def _on_hr_data(self, sample: HRSample):
        """Handle incoming heart rate data from the BLE device."""
        self._hr_chart.add_sample(sample.heart_rate_bpm, sample.rr_intervals_ms)
        self._rates["hr"].add(1)

        if not self._first_hr_seen or sample.sensor_contact != self._last_contact:
            if self._first_hr_seen and sample.sensor_contact is False:
                self._log("Strap reports no skin contact", "warning")
            self._first_hr_seen = True
            self._last_contact = sample.sensor_contact
            self._connection_panel.set_contact(sample.sensor_contact)

        self._record(RecordingSession.write_hr, sample)

    # ─── Periodic Updates ───────────────────────────────────────────────

    @Slot()
    def _update_charts(self):
        """Periodic chart refresh (~30 FPS)."""
        self._ecg_chart.update_plot()
        self._acc_chart.update_plot()
        self._hr_chart.update_plot()

    @Slot()
    def _update_stats(self):
        """Periodic stats and stream health update (1 Hz)."""
        if self._session and self._session.is_active:
            stats = self._session.stats
            stats["size_bytes"] = _dir_size(self._session.session_dir)
            self._recording_panel.update_stats(stats)
            self._update_rec_pill(stats["duration_sec"])
        self._update_stream_status()

    def _update_stream_status(self):
        """Show each stream's live rate, or flag it when data stops arriving."""
        active = self._device_manager.active_stream_config if self._device_manager.is_connected else None
        streams = {
            "ecg": (self._ecg_chart, active.ecg if active else None),
            "acc": (self._acc_chart, active.acc if active else None),
            "hr": (self._hr_chart, active.hr if active else None),
        }
        for key, (chart, stream) in streams.items():
            if stream is None:
                chart.set_status("—", "muted")
                continue
            if not stream.enabled:
                chart.set_status("off", "muted")
                continue

            meter = self._rates[key]
            since_last = meter.seconds_since_last()
            if since_last is None:
                since_last_or_start = time.monotonic() - (self._streams_started_at or time.monotonic())
            else:
                since_last_or_start = since_last

            stale = since_last_or_start > STALE_DATA_SEC
            if stale != self._stream_stale[key]:
                self._stream_stale[key] = stale
                if stale:
                    self._log(f"No {key.upper()} data received for {STALE_DATA_SEC:.0f}s", "warning")
                elif since_last is not None:
                    self._log(f"{key.upper()} data resumed")

            if stale:
                chart.set_status("no data", "error")
            elif since_last is None:
                chart.set_status("starting…", "muted")
            elif key == "hr":
                chart.set_status("live", "ok")
            else:
                rate = meter.rate()
                if rate is None:
                    chart.set_status("starting…", "muted")
                else:
                    level = "ok" if rate >= 0.9 * stream.sample_rate else "warning"
                    chart.set_status(f"{rate:.0f} Hz", level)

    def _update_rec_pill(self, duration_sec: float):
        self._rec_pill.setText(f"●  REC  {format_duration(duration_sec)}")
        self._style_rec_pill()

    @Slot()
    def _blink_recording_indicator(self):
        """Toggle the recording indicator dot."""
        self._blink_state = not self._blink_state
        self._style_rec_pill()

    def _style_rec_pill(self):
        dot = COLORS["error"] if self._blink_state else COLORS["text_muted"]
        self._rec_pill.setStyleSheet(
            f"color: {dot}; border: 1px solid {COLORS['error']}; border-radius: 14px; "
            f"padding: 4px 14px; font-size: 15px; font-weight: 700; background: transparent;"
        )

    # ─── Window Events ──────────────────────────────────────────────────

    def closeEvent(self, event):
        """Handle window close — stop recording and disconnect the strap cleanly."""
        if self._shutdown_complete:
            logging.getLogger("polar_recorder").removeHandler(self._log_handler)
            event.accept()
            return

        if self._session and self._session.is_active:
            reply = QMessageBox.question(
                self,
                "Recording in progress",
                "A recording is in progress.\n\nStop the recording and quit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_recording("app_closed")

        self._scanner.stop()

        if self._device_manager.is_busy:
            # Disconnect first, then close for real once it's done
            event.ignore()
            if not self._closing:
                self._closing = True
                self.setEnabled(False)
                self._set_status("Disconnecting from the strap…")
                self._spawn(self._shutdown())
            return

        self._shutdown_complete = True
        self.closeEvent(event)

    async def _shutdown(self):
        try:
            await asyncio.wait_for(self._device_manager.disconnect(), timeout=8)
        except Exception as e:
            logger.warning(f"Disconnect on exit failed: {e}")
        self._shutdown_complete = True
        self.close()
