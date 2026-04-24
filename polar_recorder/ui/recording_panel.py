"""Recording control panel with stream configuration and session stats."""

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
)
from PySide6.QtCore import Signal, Qt, QTimer
from pathlib import Path

from polar_recorder.utils.config import StreamConfig, AppConfig
from polar_recorder.ui.styles import COLORS


class RecordingPanel(QWidget):
    """Panel for recording controls, stream configuration, and live stats.

    Provides:
    - Stream enable/disable toggles with configuration
    - Record/Stop controls
    - Live session statistics
    - Marker/annotation controls
    - Output directory selection
    """

    # Signals
    record_requested = Signal()
    stop_requested = Signal()
    marker_requested = Signal(str)  # marker label

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._recording = False
        self._elapsed_seconds = 0
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ─── Stream Configuration ────────────────────────────────────
        stream_group = QGroupBox("Data Streams")
        stream_layout = QVBoxLayout(stream_group)
        stream_layout.setContentsMargins(16, 16, 16, 16)
        stream_layout.setSpacing(12)

        # ECG
        ecg_row = QHBoxLayout()
        self._ecg_check = QCheckBox("ECG")
        self._ecg_check.setChecked(self.config.streams.ecg.enabled)
        self._ecg_check.setProperty("class", "ecg")
        ecg_info = QLabel("130 Hz  •  14-bit")
        ecg_info.setFixedWidth(160)
        ecg_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ecg_info.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        ecg_row.addWidget(self._ecg_check)
        ecg_row.addStretch()
        ecg_row.addWidget(ecg_info)
        stream_layout.addLayout(ecg_row)

        # ACC
        acc_row = QHBoxLayout()
        self._acc_check = QCheckBox("Accelerometer")
        self._acc_check.setChecked(self.config.streams.acc.enabled)
        self._acc_check.setProperty("class", "acc")

        acc_controls = QHBoxLayout()
        acc_controls.setSpacing(8)
        self._acc_rate_combo = QComboBox()
        self._acc_rate_combo.addItems(["25 Hz", "50 Hz", "100 Hz", "200 Hz"])
        self._acc_rate_combo.setCurrentText(f"{self.config.streams.acc.sample_rate} Hz")
        self._acc_rate_combo.setFixedWidth(80)

        self._acc_range_combo = QComboBox()
        self._acc_range_combo.addItems(["2G", "4G", "8G"])
        self._acc_range_combo.setCurrentText(f"{self.config.streams.acc.range_g}G")
        self._acc_range_combo.setFixedWidth(60)
        
        acc_controls.addWidget(self._acc_rate_combo)
        acc_controls.addWidget(self._acc_range_combo)
        
        acc_wrapper = QWidget()
        acc_wrapper.setFixedWidth(160)
        acc_wrapper.setLayout(acc_controls)
        acc_controls.setContentsMargins(0, 0, 0, 0)

        acc_row.addWidget(self._acc_check)
        acc_row.addStretch()
        acc_row.addWidget(acc_wrapper)
        stream_layout.addLayout(acc_row)

        # HR
        hr_row = QHBoxLayout()
        self._hr_check = QCheckBox("Heart Rate + RR")
        self._hr_check.setChecked(self.config.streams.hr.enabled)
        self._hr_check.setProperty("class", "hr")
        hr_info = QLabel("~1 Hz  •  BPM + intervals")
        hr_info.setFixedWidth(160)
        hr_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hr_info.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; background: transparent;"
        )
        hr_row.addWidget(self._hr_check)
        hr_row.addStretch()
        hr_row.addWidget(hr_info)
        stream_layout.addLayout(hr_row)

        layout.addWidget(stream_group)

        # ─── Recording Controls ──────────────────────────────────────
        rec_group = QGroupBox("Recording")
        rec_layout = QVBoxLayout(rec_group)
        rec_layout.setContentsMargins(16, 16, 16, 16)

        # Output directory
        dir_row = QHBoxLayout()
        dir_label = QLabel("Output:")
        dir_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; background: transparent;"
        )
        self._dir_display = QLabel(str(self.config.recording.output_dir))
        self._dir_display.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            f"background: transparent;"
        )
        self._dir_display.setWordWrap(True)
        dir_btn = QPushButton("📂")
        dir_btn.setFixedWidth(36)
        dir_btn.setToolTip("Choose output directory")
        dir_btn.clicked.connect(self._choose_directory)

        dir_row.addWidget(dir_label)
        dir_row.addWidget(self._dir_display, 1)
        dir_row.addWidget(dir_btn)
        rec_layout.addLayout(dir_row)

        # Record / Stop buttons
        btn_row = QHBoxLayout()
        self._record_btn = QPushButton("⏺  Start Recording")
        self._record_btn.setProperty("class", "success")
        self._record_btn.setEnabled(False)
        self._record_btn.clicked.connect(self._on_record_clicked)
        btn_row.addWidget(self._record_btn)

        rec_layout.addLayout(btn_row)
        layout.addWidget(rec_group)

        # ─── Markers ────────────────────────────────────────────────
        marker_group = QGroupBox("Markers / Annotations")
        marker_layout = QVBoxLayout(marker_group)
        marker_layout.setContentsMargins(16, 16, 16, 16)

        marker_row = QHBoxLayout()
        self._marker_input = QLineEdit()
        self._marker_input.setPlaceholderText("Optional marker label...")
        self._marker_input.setEnabled(False)
        marker_row.addWidget(self._marker_input)

        self._marker_btn = QPushButton("🏷️  Add Marker")
        self._marker_btn.setEnabled(False)
        self._marker_btn.clicked.connect(self._on_marker_clicked)
        marker_row.addWidget(self._marker_btn)

        marker_layout.addLayout(marker_row)
        layout.addWidget(marker_group)

        # ─── Session Stats ───────────────────────────────────────────
        stats_group = QGroupBox("Session Statistics")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setContentsMargins(16, 16, 16, 16)
        stats_layout.setSpacing(12)

        self._stat_labels = {}
        stats = [
            ("duration", "Duration", "00:00:00"),
            ("ecg", "ECG Samples", "0"),
            ("acc", "ACC Samples", "0"),
            ("hr", "HR Samples", "0"),
            ("rr", "RR Intervals", "0"),
            ("markers", "Markers", "0"),
        ]

        for i, (key, label_text, default) in enumerate(stats):
            row = i // 3
            col = (i % 3) * 2

            value = QLabel(default)
            value.setStyleSheet(
                f"color: {COLORS['accent']}; font-weight: 700; "
                f"font-family: 'JetBrains Mono', monospace; font-size: 16px; "
                f"background: transparent;"
            )
            value.setAlignment(Qt.AlignCenter)

            label = QLabel(label_text)
            label.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 10px; "
                f"background: transparent;"
            )
            label.setAlignment(Qt.AlignCenter)

            stats_layout.addWidget(value, row * 2, col, 1, 2)
            stats_layout.addWidget(label, row * 2 + 1, col, 1, 2)
            self._stat_labels[key] = value

        layout.addWidget(stats_group)
        layout.addStretch()

    # ─── Public Methods ─────────────────────────────────────────────────

    def get_stream_config(self) -> StreamConfig:
        """Build StreamConfig from current UI selections."""
        config = StreamConfig()
        config.ecg.enabled = self._ecg_check.isChecked()
        config.acc.enabled = self._acc_check.isChecked()
        config.acc.sample_rate = int(self._acc_rate_combo.currentText().replace(" Hz", ""))
        config.acc.range_g = int(self._acc_range_combo.currentText().replace("G", ""))
        config.hr.enabled = self._hr_check.isChecked()
        return config

    def set_connected(self, connected: bool):
        """Enable/disable recording controls based on connection state."""
        self._record_btn.setEnabled(connected and not self._recording)

    def set_recording(self, recording: bool):
        """Update UI to reflect recording state."""
        self._recording = recording
        if recording:
            self._record_btn.setText("⏹  Stop Recording")
            self._record_btn.setProperty("class", "danger")
            self._marker_btn.setEnabled(True)
            self._marker_input.setEnabled(True)
            # Disable stream config during recording
            self._ecg_check.setEnabled(False)
            self._acc_check.setEnabled(False)
            self._hr_check.setEnabled(False)
            self._acc_rate_combo.setEnabled(False)
            self._acc_range_combo.setEnabled(False)
        else:
            self._record_btn.setText("⏺  Start Recording")
            self._record_btn.setProperty("class", "success")
            self._marker_btn.setEnabled(False)
            self._marker_input.setEnabled(False)
            self._ecg_check.setEnabled(True)
            self._acc_check.setEnabled(True)
            self._hr_check.setEnabled(True)
            self._acc_rate_combo.setEnabled(True)
            self._acc_range_combo.setEnabled(True)

        # Force style refresh
        self._record_btn.style().unpolish(self._record_btn)
        self._record_btn.style().polish(self._record_btn)

    def update_stats(self, stats: dict):
        """Update the statistics display."""
        if "duration_sec" in stats:
            secs = int(stats["duration_sec"])
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self._stat_labels["duration"].setText(f"{h:02d}:{m:02d}:{s:02d}")

        if "ecg_samples" in stats:
            self._stat_labels["ecg"].setText(f"{stats['ecg_samples']:,}")
        if "acc_samples" in stats:
            self._stat_labels["acc"].setText(f"{stats['acc_samples']:,}")
        if "hr_samples" in stats:
            self._stat_labels["hr"].setText(f"{stats['hr_samples']:,}")
        if "rr_samples" in stats:
            self._stat_labels["rr"].setText(f"{stats['rr_samples']:,}")
        if "markers" in stats:
            self._stat_labels["markers"].setText(f"{stats['markers']:,}")

    # ─── Private ────────────────────────────────────────────────────────

    def _on_record_clicked(self):
        if self._recording:
            self.stop_requested.emit()
        else:
            self.record_requested.emit()

    def _on_marker_clicked(self):
        label = self._marker_input.text().strip()
        self.marker_requested.emit(label)
        self._marker_input.clear()

    def _choose_directory(self):
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            str(self.config.recording.output_dir),
        )
        if dir_path:
            self.config.recording.output_dir = Path(dir_path)
            self._dir_display.setText(dir_path)
