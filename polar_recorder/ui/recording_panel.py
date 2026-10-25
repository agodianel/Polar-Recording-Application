"""Recording control panel with stream configuration and session stats."""

from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGroupBox,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLineEdit,
    QFileDialog,
    QListWidget,
)
from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices

from polar_recorder.utils.config import StreamConfig, AppConfig
from polar_recorder.ui.styles import COLORS, mono_font_family, repolish

MARKER_EVENT = "MARKER_EVENT"
MARKER_START = "MARKER_START"
MARKER_STOP = "MARKER_STOP"


def format_duration(seconds: float) -> str:
    secs = int(seconds)
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


class RecordingPanel(QWidget):
    """Panel for recording controls, stream configuration, and live stats.

    Provides:
    - Stream enable/disable toggles with configuration
    - Record/Stop controls with session label and output folder
    - Marker/annotation controls (events and start/end segments)
    - Live session statistics
    """

    # Signals
    record_requested = Signal()
    stop_requested = Signal()
    marker_requested = Signal(str, str)  # marker type, label

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._recording = False
        self._can_record = False
        self._segment_open = False
        self._last_session_dir: Optional[Path] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ─── Stream Configuration ────────────────────────────────────
        stream_group = QGroupBox("Data streams")
        stream_layout = QGridLayout(stream_group)
        stream_layout.setHorizontalSpacing(8)
        stream_layout.setVerticalSpacing(10)
        stream_layout.setColumnStretch(0, 1)

        self._ecg_check = QCheckBox("ECG")
        self._ecg_check.setChecked(self.config.streams.ecg.enabled)
        self._ecg_check.setProperty("class", "ecg")
        stream_layout.addWidget(self._ecg_check, 0, 0)
        stream_layout.addWidget(self._info_label("130 Hz · 14-bit"), 0, 1, 1, 2, Qt.AlignRight)

        self._acc_check = QCheckBox("Accelerometer")
        self._acc_check.setChecked(self.config.streams.acc.enabled)
        self._acc_check.setProperty("class", "acc")
        self._acc_rate_combo = QComboBox()
        self._acc_rate_combo.addItems(["25 Hz", "50 Hz", "100 Hz", "200 Hz"])
        self._acc_rate_combo.setCurrentText(f"{self.config.streams.acc.sample_rate} Hz")
        self._acc_rate_combo.setToolTip("Accelerometer sample rate")
        self._acc_range_combo = QComboBox()
        self._acc_range_combo.addItems(["±2 G", "±4 G", "±8 G"])
        self._acc_range_combo.setCurrentText(f"±{self.config.streams.acc.range_g} G")
        self._acc_range_combo.setToolTip("Accelerometer measurement range")
        self._acc_check.toggled.connect(self._acc_rate_combo.setEnabled)
        self._acc_check.toggled.connect(self._acc_range_combo.setEnabled)
        stream_layout.addWidget(self._acc_check, 1, 0)
        stream_layout.addWidget(self._acc_rate_combo, 1, 1)
        stream_layout.addWidget(self._acc_range_combo, 1, 2)

        self._hr_check = QCheckBox("Heart rate + RR")
        self._hr_check.setChecked(self.config.streams.hr.enabled)
        self._hr_check.setProperty("class", "hr")
        stream_layout.addWidget(self._hr_check, 2, 0)
        stream_layout.addWidget(self._info_label("~1 Hz · BPM + intervals"), 2, 1, 1, 2, Qt.AlignRight)

        self._streams_hint = QLabel(
            "Stream settings apply when connecting. Disconnect to change them."
        )
        self._streams_hint.setProperty("class", "muted")
        self._streams_hint.setWordWrap(True)
        self._streams_hint.hide()
        stream_layout.addWidget(self._streams_hint, 3, 0, 1, 3)

        layout.addWidget(stream_group)

        # ─── Recording Controls ──────────────────────────────────────
        rec_group = QGroupBox("Recording")
        rec_layout = QVBoxLayout(rec_group)
        rec_layout.setSpacing(8)

        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("Session label, e.g. P01 - Seat Rest (optional)")
        self._label_input.setToolTip(
            "Used as the session folder name. Leave empty for the default "
            "<device>_<id>_<timestamp> name."
        )
        rec_layout.addWidget(self._label_input)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self._dir_display = QLabel()
        self._dir_display.setProperty("class", "muted")
        self._dir_display.setMinimumWidth(80)
        self._update_dir_display()
        change_btn = QPushButton("Change…")
        change_btn.setProperty("class", "small")
        change_btn.setToolTip("Choose output directory")
        change_btn.clicked.connect(self._choose_directory)
        self._dir_btn = change_btn
        self._open_btn = QPushButton("Open")
        self._open_btn.setProperty("class", "small")
        self._open_btn.setToolTip("Open the last session folder (or the output folder)")
        self._open_btn.clicked.connect(self._open_folder)
        dir_row.addWidget(self._dir_display, 1)
        dir_row.addWidget(change_btn)
        dir_row.addWidget(self._open_btn)
        rec_layout.addLayout(dir_row)

        self._timer_label = QLabel("00:00:00")
        self._timer_label.setAlignment(Qt.AlignCenter)
        self._timer_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-family: '{mono_font_family()}'; "
            f"font-size: 30px; font-weight: 700; background: transparent;"
        )
        rec_layout.addWidget(self._timer_label)

        self._rec_status = QLabel("Connect a device to start recording")
        self._rec_status.setProperty("class", "muted")
        self._rec_status.setAlignment(Qt.AlignCenter)
        self._rec_status.setWordWrap(True)
        rec_layout.addWidget(self._rec_status)

        self._record_btn = QPushButton()
        self._record_btn.clicked.connect(self._on_record_clicked)
        rec_layout.addWidget(self._record_btn)
        layout.addWidget(rec_group)

        # ─── Markers ────────────────────────────────────────────────
        marker_group = QGroupBox("Markers")
        marker_layout = QVBoxLayout(marker_group)
        marker_layout.setSpacing(8)

        self._marker_input = QLineEdit()
        self._marker_input.setPlaceholderText("Marker label (optional) — Enter to add")
        self._marker_input.returnPressed.connect(self.add_event_marker)
        marker_layout.addWidget(self._marker_input)

        marker_btns = QHBoxLayout()
        marker_btns.setSpacing(6)
        self._marker_btn = QPushButton("Add marker")
        self._marker_btn.setToolTip("Mark a single event (Ctrl+M)")
        self._marker_btn.clicked.connect(self.add_event_marker)
        self._segment_btn = QPushButton()
        self._segment_btn.setToolTip(
            "Mark the start/end of a segment, like the Android app's "
            "MARKER_START / MARKER_STOP (Ctrl+Shift+M)"
        )
        self._segment_btn.clicked.connect(self.toggle_segment)
        marker_btns.addWidget(self._marker_btn)
        marker_btns.addWidget(self._segment_btn)
        marker_layout.addLayout(marker_btns)

        self._marker_list = QListWidget()
        self._marker_list.setProperty("class", "markers")
        self._marker_list.setMaximumHeight(96)
        self._marker_list.setSelectionMode(QListWidget.NoSelection)
        self._marker_list.hide()
        marker_layout.addWidget(self._marker_list)
        layout.addWidget(marker_group)

        # ─── Session Stats ───────────────────────────────────────────
        stats_group = QGroupBox("Session statistics")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setHorizontalSpacing(6)
        stats_layout.setVerticalSpacing(2)

        self._stat_labels = {}
        stats = [
            ("ecg", "ECG samples"),
            ("acc", "ACC samples"),
            ("hr", "HR samples"),
            ("rr", "RR intervals"),
            ("markers", "Markers"),
            ("size", "Data size"),
        ]
        for i, (key, label_text) in enumerate(stats):
            row, col = (i // 3) * 2, i % 3
            value = QLabel("0")
            value.setProperty("class", "stat-value")
            value.setAlignment(Qt.AlignCenter)
            label = QLabel(label_text)
            label.setProperty("class", "stat-label")
            label.setAlignment(Qt.AlignCenter)
            stats_layout.addWidget(value, row, col)
            stats_layout.addWidget(label, row + 1, col)
            self._stat_labels[key] = value
        stats_layout.setRowMinimumHeight(2, 32)
        self._stat_labels["size"].setText("—")

        layout.addWidget(stats_group)
        layout.addStretch()

        self._refresh_controls()

    @staticmethod
    def _info_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("class", "muted")
        return label

    # ─── Public Methods ─────────────────────────────────────────────────

    def get_stream_config(self) -> StreamConfig:
        """Build StreamConfig from current UI selections."""
        config = StreamConfig()
        config.ecg.enabled = self._ecg_check.isChecked()
        config.acc.enabled = self._acc_check.isChecked()
        config.acc.sample_rate = int(self._acc_rate_combo.currentText().split()[0])
        config.acc.range_g = int(self._acc_range_combo.currentText().strip("±G "))
        config.hr.enabled = self._hr_check.isChecked()
        return config

    def session_label(self) -> str:
        return self._label_input.text().strip()

    def set_streams_locked(self, locked: bool):
        """Lock stream settings while connected — they only apply when connecting."""
        self._ecg_check.setEnabled(not locked)
        self._acc_check.setEnabled(not locked)
        self._hr_check.setEnabled(not locked)
        acc_on = self._acc_check.isChecked()
        self._acc_rate_combo.setEnabled(not locked and acc_on)
        self._acc_range_combo.setEnabled(not locked and acc_on)
        self._streams_hint.setVisible(locked)

    def set_can_record(self, can_record: bool, reason: str = ""):
        """Enable recording once streams are running on a connected device."""
        self._can_record = can_record
        if not self._recording:
            self._rec_status.setText(reason or ("Ready to record" if can_record else ""))
        self._refresh_controls()

    def set_recording(self, recording: bool, session_dir: Optional[Path] = None):
        """Update UI to reflect recording state."""
        self._recording = recording
        if recording:
            self._segment_open = False
            self._marker_list.clear()
            self._marker_list.hide()
            for key in self._stat_labels:
                self._stat_labels[key].setText("0")
            if session_dir:
                self._last_session_dir = session_dir
                self._rec_status.setText(f"Recording to {session_dir.name}")
        elif session_dir:
            self._last_session_dir = session_dir
            self._rec_status.setText(f"Saved to {session_dir.name}")
        self._timer_label.setStyleSheet(
            f"color: {COLORS['error'] if recording else COLORS['text_muted']}; "
            f"font-family: '{mono_font_family()}'; font-size: 30px; font-weight: 700; "
            f"background: transparent;"
        )
        self._refresh_controls()

    def update_stats(self, stats: dict):
        """Update the statistics display."""
        if "duration_sec" in stats:
            self._timer_label.setText(format_duration(stats["duration_sec"]))
        for key, stat_key in [("ecg", "ecg_samples"), ("acc", "acc_samples"),
                              ("hr", "hr_samples"), ("rr", "rr_samples"),
                              ("markers", "markers")]:
            if stat_key in stats:
                self._stat_labels[key].setText(f"{stats[stat_key]:,}")
        if "size_bytes" in stats:
            size = stats["size_bytes"]
            text = f"{size / 1e6:.1f} MB" if size >= 1e6 else f"{size / 1e3:.0f} kB"
            self._stat_labels["size"].setText(text)

    def add_marker_entry(self, elapsed_sec: float, marker_type: str, label: str):
        """Show a placed marker in the list."""
        kind = {MARKER_START: "START", MARKER_STOP: "END", MARKER_EVENT: "EVENT"}.get(
            marker_type, marker_type
        )
        self._marker_list.insertItem(0, f"{format_duration(elapsed_sec)}  {kind:<5}  {label}")
        self._marker_list.show()

    def add_event_marker(self):
        """Emit an event marker with the current label (no-op when not recording)."""
        if not self._recording:
            return
        self.marker_requested.emit(MARKER_EVENT, self._take_marker_label())

    def toggle_segment(self):
        """Emit MARKER_START / MARKER_STOP alternately (no-op when not recording)."""
        if not self._recording:
            return
        marker_type = MARKER_STOP if self._segment_open else MARKER_START
        self._segment_open = not self._segment_open
        self.marker_requested.emit(marker_type, self._take_marker_label())
        self._refresh_controls()

    # ─── Private ────────────────────────────────────────────────────────

    def _on_record_clicked(self):
        if self._recording:
            self.stop_requested.emit()
        else:
            self.record_requested.emit()

    def _take_marker_label(self) -> str:
        label = self._marker_input.text().strip()
        self._marker_input.clear()
        return label

    def _refresh_controls(self):
        recording = self._recording
        if recording:
            self._record_btn.setText("■  Stop recording")
            self._record_btn.setProperty("class", "stop")
            self._record_btn.setEnabled(True)
        else:
            self._record_btn.setText("●  Start recording")
            self._record_btn.setProperty("class", "record")
            self._record_btn.setEnabled(self._can_record)
        repolish(self._record_btn)

        self._label_input.setEnabled(not recording)
        self._dir_btn.setEnabled(not recording)
        self._marker_input.setEnabled(recording)
        self._marker_btn.setEnabled(recording)
        self._segment_btn.setEnabled(recording)
        self._segment_btn.setText("End segment" if self._segment_open else "Start segment")

    def _update_dir_display(self):
        path = str(self.config.recording.output_dir)
        self._dir_display.setToolTip(path)
        metrics = self._dir_display.fontMetrics()
        self._dir_display.setText(metrics.elidedText(path, Qt.ElideMiddle, 200))

    def _choose_directory(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            str(self.config.recording.output_dir),
        )
        if dir_path:
            self.config.recording.output_dir = Path(dir_path)
            self._update_dir_display()

    def _open_folder(self):
        target = self._last_session_dir
        if target is None or not target.exists():
            target = self.config.recording.output_dir
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
