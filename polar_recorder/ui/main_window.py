"""Main application window for PolarRecorder.

Orchestrates the connection panel, recording panel, and live charts.
Bridges async BLE operations with the Qt event loop.
"""

import asyncio
import logging
import time
from datetime import datetime

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
    QTextEdit,
)
from PySide6.QtCore import Qt, QTimer, Slot

from polar_recorder.ble.scanner import PolarScanner
from polar_recorder.ble.device import PolarDeviceManager
from polar_recorder.ble.data_models import DeviceInfo, ECGSample, ACCSample, HRSample
from polar_recorder.recording.session import RecordingSession
from polar_recorder.ui.connection_panel import ConnectionPanel
from polar_recorder.ui.recording_panel import RecordingPanel
from polar_recorder.ui.live_charts import (
    ECGChartWidget,
    ACCChartWidget,
    HRChartWidget,
    setup_pyqtgraph,
)
from polar_recorder.ui.styles import COLORS, STYLESHEET
from polar_recorder.utils.config import AppConfig

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main PolarRecorder application window.

    Layout:
    ┌─────────────────────────────────────────────────────────────┐
    │ Header Bar                                                   │
    ├──────────────┬──────────────────────────────────────────────┤
    │              │  ┌── ECG Chart ────────────────────────────┐ │
    │  Connection  │  │                                         │ │
    │  Panel       │  └─────────────────────────────────────────┘ │
    │              │  ┌── ACC Chart ────────────────────────────┐ │
    │  Recording   │  │                                         │ │
    │  Panel       │  └─────────────────────────────────────────┘ │
    │              │  ┌── HR Chart  ────────────────────────────┐ │
    │  Stats       │  │                                         │ │
    │              │  └─────────────────────────────────────────┘ │
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
        self._recording_start_time: float | None = None

        # Configure pyqtgraph
        setup_pyqtgraph()

        # Setup UI
        self._setup_window()
        self._setup_layout()
        self._setup_status_bar()
        self._setup_timers()
        self._connect_signals()
        self._setup_ble_callbacks()

    def _setup_window(self):
        """Configure main window properties."""
        self.setWindowTitle("PolarRecorder — Polar H10 Data Acquisition")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        self.setStyleSheet(STYLESHEET)

    def _setup_layout(self):
        """Create the main layout with splitter."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        # ─── Header ─────────────────────────────────────────────────
        header = QHBoxLayout()

        # App title
        title_layout = QVBoxLayout()
        title = QLabel("POLAR RECORDER")
        title.setProperty("class", "title")
        title.setStyleSheet(
            f"color: {COLORS['accent']}; font-size: 22px; "
            f"font-weight: 800; letter-spacing: 3px; background: transparent;"
        )
        subtitle = QLabel("Polar H10 ECG Band — Data Acquisition & Live Visualization")
        subtitle.setProperty("class", "subtitle")
        subtitle.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        header.addLayout(title_layout)
        header.addStretch()

        # Recording indicator (pulsing dot when recording)
        self._rec_indicator = QLabel("")
        self._rec_indicator.setStyleSheet("background: transparent;")
        self._rec_indicator.hide()
        header.addWidget(self._rec_indicator)

        main_layout.addLayout(header)

        # ─── Main Splitter (sidebar | charts) ───────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)

        # Left sidebar
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 8, 0)
        sidebar_layout.setSpacing(8)

        self._connection_panel = ConnectionPanel()
        sidebar_layout.addWidget(self._connection_panel)

        self._recording_panel = RecordingPanel(self.config)
        sidebar_layout.addWidget(self._recording_panel)

        splitter.addWidget(sidebar)

        # Right side: charts in tabs
        chart_area = QWidget()
        chart_layout = QVBoxLayout(chart_area)
        chart_layout.setContentsMargins(8, 0, 0, 0)
        chart_layout.setSpacing(8)

        self._tab_widget = QTabWidget()

        # Live Charts tab
        charts_tab = QWidget()
        charts_layout = QVBoxLayout(charts_tab)
        charts_layout.setContentsMargins(8, 8, 8, 8)
        charts_layout.setSpacing(8)

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

        self._tab_widget.addTab(charts_tab, "📊  Live Charts")

        # Log tab
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(
            f"background-color: {COLORS['bg_input']}; "
            f"color: {COLORS['text_secondary']}; "
            f"font-family: 'JetBrains Mono', monospace; font-size: 11px;"
        )
        self._tab_widget.addTab(self._log_text, "📝  Log")

        chart_layout.addWidget(self._tab_widget)
        splitter.addWidget(chart_area)

        # Splitter proportions (30/70)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([350, 850])

        main_layout.addWidget(splitter)

    def _setup_status_bar(self):
        """Create the status bar."""
        status = QStatusBar()
        self.setStatusBar(status)
        self._status_label = QLabel("Ready — Connect a Polar H10 to begin")
        status.addWidget(self._status_label, 1)
        self._fps_label = QLabel("")
        self._fps_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;"
        )
        status.addPermanentWidget(self._fps_label)

    def _setup_timers(self):
        """Setup periodic timers for chart updates and stats."""
        # Chart update timer (~30 FPS)
        self._chart_timer = QTimer()
        self._chart_timer.setInterval(self.config.charts.update_rate_ms)
        self._chart_timer.timeout.connect(self._update_charts)
        self._chart_timer.start()

        # Stats update timer (1 Hz)
        self._stats_timer = QTimer()
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start()

        # Recording indicator blink timer
        self._blink_timer = QTimer()
        self._blink_timer.setInterval(500)
        self._blink_state = False
        self._blink_timer.timeout.connect(self._blink_recording_indicator)

    def _connect_signals(self):
        """Connect UI signals to handler methods."""
        # Connection panel
        self._connection_panel.scan_requested.connect(self._on_scan)
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

    # ─── Log Helper ─────────────────────────────────────────────────────

    def _log(self, message: str, level: str = "info"):
        """Add a timestamped message to the log panel."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = {
            "info": COLORS["text_secondary"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["error"],
        }.get(level, COLORS["text_secondary"])

        self._log_text.append(
            f'<span style="color:{COLORS["text_muted"]}">[{timestamp}]</span> '
            f'<span style="color:{color}">{message}</span>'
        )

    # ─── Scan Handlers ──────────────────────────────────────────────────

    @Slot()
    def _on_scan(self):
        """Handle scan button click — start BLE scanning."""
        self._log("Starting BLE scan for Polar devices...")
        self._connection_panel.set_scanning(True)
        self._status_label.setText("Scanning for Polar devices...")

        # Use asyncio to run the scan
        loop = asyncio.get_event_loop()
        loop.create_task(self._do_scan())

    async def _do_scan(self):
        """Async BLE scan coroutine."""
        try:
            self._scanner.set_callback(self._on_device_found)
            devices = await self._scanner.scan()
            self._log(f"Scan complete. Found {len(devices)} device(s).", "success")
            self._status_label.setText(
                f"Scan complete — {len(devices)} device(s) found"
            )
        except Exception as e:
            self._log(f"Scan failed: {e}", "error")
            self._status_label.setText("Scan failed")
        finally:
            self._connection_panel.set_scanning(False)

    def _on_device_found(self, device: DeviceInfo):
        """Callback when a Polar device is discovered during scanning."""
        self._connection_panel.add_device(device)
        self._log(f"Found: {device.name} ({device.address})")

    # ─── Connection Handlers ────────────────────────────────────────────

    @Slot(object)
    def _on_connect(self, device_info: DeviceInfo):
        """Handle connect request for a specific device."""
        self._log(f"Connecting to {device_info.name}...")
        self._connection_panel.set_connecting()
        self._status_label.setText(f"Connecting to {device_info.name}...")

        loop = asyncio.get_event_loop()
        loop.create_task(self._do_connect(device_info))

    async def _do_connect(self, device_info: DeviceInfo):
        """Async connection coroutine."""
        success = await self._device_manager.connect(device_info)

        if success:
            # Start streams immediately after connecting
            stream_config = self._recording_panel.get_stream_config()
            try:
                await self._device_manager.start_streams(stream_config)
                self._log("All data streams started", "success")
            except Exception as e:
                self._log(f"Stream start failed: {e}", "error")

    @Slot()
    def _on_disconnect(self):
        """Handle disconnect request."""
        self._log("Disconnecting...")

        # Stop recording if active
        if self._session and self._session.is_active:
            self._on_stop_recording()

        loop = asyncio.get_event_loop()
        loop.create_task(self._device_manager.disconnect())

    def _on_ble_connected(self):
        """Callback when BLE connection is established."""
        device = self._device_manager.device_info
        self._connection_panel.set_connected(device)
        self._recording_panel.set_connected(True)
        self._log(f"Connected to {device.name}", "success")
        self._status_label.setText(f"Connected — {device.name}")

    def _on_ble_disconnected(self):
        """Callback when BLE connection is lost."""
        self._connection_panel.set_disconnected()
        self._recording_panel.set_connected(False)
        self._log("Disconnected from device", "warning")
        self._status_label.setText("Disconnected")

    def _on_ble_error(self, error_msg: str):
        """Callback for BLE errors."""
        self._log(f"Error: {error_msg}", "error")
        self._connection_panel.set_disconnected()
        self._status_label.setText(f"Error: {error_msg}")

    # ─── Recording Handlers ─────────────────────────────────────────────

    @Slot()
    def _on_start_recording(self):
        """Start a new recording session."""
        if not self._device_manager.is_connected:
            self._log("Cannot record — no device connected", "error")
            return

        device_info = self._device_manager.device_info
        stream_config = self._recording_panel.get_stream_config()

        self._session = RecordingSession(
            device_info=device_info,
            config=self.config.recording,
            stream_config=stream_config,
        )

        session_dir = self._session.start()
        self._recording_start_time = time.time()

        self._recording_panel.set_recording(True)
        self._rec_indicator.show()
        self._blink_timer.start()

        self._log(f"Recording started → {session_dir}", "success")
        self._status_label.setText(f"⏺ Recording — {device_info.name}")

    @Slot()
    def _on_stop_recording(self):
        """Stop the current recording session."""
        if self._session and self._session.is_active:
            stats = self._session.stop()
            self._recording_panel.update_stats(stats)
            self._log(
                f"Recording stopped. Duration: {stats['duration_sec']:.1f}s, "
                f"ECG: {stats['ecg_samples']:,}, ACC: {stats['acc_samples']:,}, "
                f"HR: {stats['hr_samples']:,}",
                "success",
            )

            session_dir = self._session.session_dir
            self._session = None
            self._recording_start_time = None

            self._recording_panel.set_recording(False)
            self._rec_indicator.hide()
            self._blink_timer.stop()

            self._status_label.setText("Recording saved successfully")

            # Show completion dialog
            QMessageBox.information(
                self,
                "Recording Complete",
                f"Session saved to:\n{session_dir}\n\n"
                f"ECG: {stats['ecg_samples']:,} samples\n"
                f"ACC: {stats['acc_samples']:,} samples\n"
                f"HR:  {stats['hr_samples']:,} samples\n"
                f"RR:  {stats['rr_samples']:,} intervals",
            )

    @Slot(str)
    def _on_add_marker(self, label: str):
        """Add a marker to the current recording."""
        if self._session and self._session.is_active:
            marker_type = "MARKER_EVENT"
            self._session.add_marker(marker_type, label)
            self._log(f"Marker added: {label or '(no label)'}", "info")

    # ─── Data Handlers ──────────────────────────────────────────────────

    def _on_ecg_data(self, sample: ECGSample):
        """Handle incoming ECG data from the BLE device."""
        # Send to chart
        self._ecg_chart.add_samples(sample.samples_uv)

        # Send to recording
        if self._session and self._session.is_active:
            self._session.write_ecg(sample)

    def _on_acc_data(self, sample: ACCSample):
        """Handle incoming accelerometer data from the BLE device."""
        # Send to chart
        self._acc_chart.add_samples(sample.samples_mg)

        # Send to recording
        if self._session and self._session.is_active:
            self._session.write_acc(sample)

    def _on_hr_data(self, sample: HRSample):
        """Handle incoming heart rate data from the BLE device."""
        # Send to chart
        # Use absolute monotonic time so the graph doesn't jump backwards
        self._hr_chart.add_sample(sample.heart_rate_bpm, time.time())

        # Send to recording
        if self._session and self._session.is_active:
            self._session.write_hr(sample)

    # ─── Periodic Updates ───────────────────────────────────────────────

    @Slot()
    def _update_charts(self):
        """Periodic chart refresh (~30 FPS)."""
        self._ecg_chart.update_plot()
        self._acc_chart.update_plot()
        self._hr_chart.update_plot()

    @Slot()
    def _update_stats(self):
        """Periodic stats update (1 Hz)."""
        if self._session and self._session.is_active:
            self._recording_panel.update_stats(self._session.stats)

    @Slot()
    def _blink_recording_indicator(self):
        """Toggle the recording indicator dot."""
        self._blink_state = not self._blink_state
        if self._blink_state:
            self._rec_indicator.setText("⏺ REC")
            self._rec_indicator.setStyleSheet(
                f"color: {COLORS['error']}; font-size: 16px; "
                f"font-weight: 700; background: transparent;"
            )
        else:
            self._rec_indicator.setText("⏺ REC")
            self._rec_indicator.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 16px; "
                f"font-weight: 700; background: transparent;"
            )

    # ─── Window Events ──────────────────────────────────────────────────

    def closeEvent(self, event):
        """Handle window close — ensure proper cleanup."""
        # Stop recording
        if self._session and self._session.is_active:
            self._session.stop()

        # Disconnect device
        if self._device_manager.is_connected:
            loop = asyncio.get_event_loop()
            loop.create_task(self._device_manager.disconnect())

        event.accept()
