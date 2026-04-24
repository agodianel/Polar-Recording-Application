"""Real-time chart widgets using pyqtgraph.

GPU-accelerated plotting for ECG (130 Hz), ACC (200 Hz), and HR data
with smooth scrolling, grid lines, and research-grade appearance.
"""

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from polar_recorder.ui.styles import COLORS


def setup_pyqtgraph():
    """Configure pyqtgraph global settings for our dark theme."""
    pg.setConfigOptions(
        antialias=True,
        background=COLORS["chart_bg"],
        foreground=COLORS["text_secondary"],
    )


class ECGChartWidget(QWidget):
    """Real-time ECG waveform display.

    Shows a continuous scrolling ECG trace at 130 Hz with a configurable
    time window. Optimized for smooth rendering with ring-buffer data.
    """

    def __init__(self, window_seconds: float = 5.0, parent=None):
        super().__init__(parent)
        self.window_seconds = window_seconds
        self.sample_rate = 130
        self.buffer_size = int(self.sample_rate * self.window_seconds)

        # Ring buffer for ECG data
        self._data = np.zeros(self.buffer_size, dtype=np.float32)
        self._time = np.linspace(
            -self.window_seconds, 0, self.buffer_size, dtype=np.float32
        )
        self._write_idx = 0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("⚡ ECG")
        title.setStyleSheet(
            f"color: {COLORS['chart_ecg']}; font-weight: 700; "
            f"font-size: 14px; background: transparent;"
        )
        self._value_label = QLabel("-- µV")
        self._value_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 12px; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._value_label)
        layout.addLayout(header)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setMinimumHeight(200)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._plot_widget.setLabel("bottom", "Time (← Past | 0 = Now)", units="s")
        self._plot_widget.setLabel("left", "ECG", units="µV")
        self._plot_widget.setXRange(-self.window_seconds, 0)
        self._plot_widget.setMouseEnabled(x=False, y=True)
        self._plot_widget.hideButtons()

        # Style the axes
        for axis_name in ["bottom", "left"]:
            axis = self._plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(COLORS["border"], width=1))
            axis.setTextPen(COLORS["text_muted"])
            axis.setStyle(tickFont=pg.QtGui.QFont("JetBrains Mono", 9))

        # ECG trace
        self._curve = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_ecg"], width=1.5),
        )

        layout.addWidget(self._plot_widget)

    def add_samples(self, samples_uv: list):
        """Add new ECG samples to the ring buffer."""
        for val in samples_uv:
            self._data[self._write_idx % self.buffer_size] = val
            self._write_idx += 1

    def update_plot(self):
        """Refresh the plot with current buffer contents."""
        if self._write_idx == 0:
            return

        # Build the display buffer from the ring buffer
        n = min(self._write_idx, self.buffer_size)
        if self._write_idx >= self.buffer_size:
            start = self._write_idx % self.buffer_size
            display_data = np.concatenate([
                self._data[start:],
                self._data[:start],
            ])
        else:
            display_data = self._data[:n]

        # Create time axis
        t = np.linspace(-n / self.sample_rate, 0, n, dtype=np.float32)

        self._curve.setData(t, display_data)

        # Update the value label
        if n > 0:
            latest = display_data[-1]
            self._value_label.setText(f"{latest:.0f} µV")


class ACCChartWidget(QWidget):
    """Real-time 3-axis accelerometer display.

    Shows X, Y, Z acceleration traces in different colors with
    a scrolling time window.
    """

    def __init__(self, window_seconds: float = 10.0, sample_rate: int = 200, parent=None):
        super().__init__(parent)
        self.window_seconds = window_seconds
        self.sample_rate = sample_rate
        self.buffer_size = int(self.sample_rate * self.window_seconds)

        # Ring buffers for X, Y, Z
        self._data_x = np.zeros(self.buffer_size, dtype=np.float32)
        self._data_y = np.zeros(self.buffer_size, dtype=np.float32)
        self._data_z = np.zeros(self.buffer_size, dtype=np.float32)
        self._write_idx = 0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("📐 Accelerometer")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-weight: 700; "
            f"font-size: 14px; background: transparent;"
        )
        self._value_label = QLabel("X: -- Y: -- Z: --")
        self._value_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-family: 'JetBrains Mono', monospace; "
            f"font-size: 11px; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._value_label)
        layout.addLayout(header)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setMinimumHeight(180)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._plot_widget.setLabel("bottom", "Time (← Past | 0 = Now)", units="s")
        self._plot_widget.setLabel("left", "Acceleration", units="mG")
        self._plot_widget.setXRange(-self.window_seconds, 0)
        self._plot_widget.setMouseEnabled(x=False, y=True)
        self._plot_widget.hideButtons()
        self._plot_widget.addLegend(
            offset=(10, 10),
            labelTextColor=COLORS["text_secondary"],
            labelTextSize="10pt",
        )

        # Style axes
        for axis_name in ["bottom", "left"]:
            axis = self._plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(COLORS["border"], width=1))
            axis.setTextPen(COLORS["text_muted"])
            axis.setStyle(tickFont=pg.QtGui.QFont("JetBrains Mono", 9))

        # Three traces
        self._curve_x = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_x"], width=1.5), name="X"
        )
        self._curve_y = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_y"], width=1.5), name="Y"
        )
        self._curve_z = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_z"], width=1.5), name="Z"
        )

        layout.addWidget(self._plot_widget)

    def add_samples(self, samples_mg: list):
        """Add new accelerometer samples (list of (x, y, z) tuples)."""
        for x, y, z in samples_mg:
            idx = self._write_idx % self.buffer_size
            self._data_x[idx] = x
            self._data_y[idx] = y
            self._data_z[idx] = z
            self._write_idx += 1

    def update_plot(self):
        """Refresh the plot with current buffer contents."""
        if self._write_idx == 0:
            return

        n = min(self._write_idx, self.buffer_size)

        if self._write_idx >= self.buffer_size:
            start = self._write_idx % self.buffer_size
            dx = np.concatenate([self._data_x[start:], self._data_x[:start]])
            dy = np.concatenate([self._data_y[start:], self._data_y[:start]])
            dz = np.concatenate([self._data_z[start:], self._data_z[:start]])
        else:
            dx = self._data_x[:n]
            dy = self._data_y[:n]
            dz = self._data_z[:n]

        t = np.linspace(-n / self.sample_rate, 0, n, dtype=np.float32)

        self._curve_x.setData(t, dx)
        self._curve_y.setData(t, dy)
        self._curve_z.setData(t, dz)

        if n > 0:
            self._value_label.setText(
                f"X: {dx[-1]:.0f}  Y: {dy[-1]:.0f}  Z: {dz[-1]:.0f}"
            )


class HRChartWidget(QWidget):
    """Real-time heart rate and RR interval display.

    Shows HR trend over time and current BPM in a large readout.
    """

    def __init__(self, window_seconds: float = 120.0, parent=None):
        super().__init__(parent)
        self.window_seconds = window_seconds
        self.max_samples = int(window_seconds)  # ~1 sample per second

        self._hr_data = np.zeros(self.max_samples, dtype=np.float32)
        self._hr_time = np.zeros(self.max_samples, dtype=np.float32)
        self._write_idx = 0
        self._current_hr = 0
        self._start_time = None

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # BPM Header
        header = QHBoxLayout()

        title = QLabel("❤️  Heart Rate")
        title.setStyleSheet(
            f"color: {COLORS['chart_hr']}; font-weight: 700; "
            f"font-size: 14px; background: transparent;"
        )

        self._bpm_label = QLabel("-- BPM")
        self._bpm_label.setStyleSheet(
            f"color: {COLORS['chart_hr']}; font-weight: 700; "
            f"font-family: 'JetBrains Mono', monospace; font-size: 24px; "
            f"background: transparent;"
        )

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._bpm_label)
        layout.addLayout(header)

        # Plot widget
        self._plot_widget = pg.PlotWidget()
        self._plot_widget.setMinimumHeight(150)
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._plot_widget.setLabel("bottom", "Time (Relative)", units="s")
        self._plot_widget.setLabel("left", "HR", units="BPM")
        self._plot_widget.setYRange(40, 200)
        self._plot_widget.setMouseEnabled(x=False, y=True)
        self._plot_widget.hideButtons()

        for axis_name in ["bottom", "left"]:
            axis = self._plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(COLORS["border"], width=1))
            axis.setTextPen(COLORS["text_muted"])
            axis.setStyle(tickFont=pg.QtGui.QFont("JetBrains Mono", 9))

        # HR trend line
        self._curve = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_hr"], width=2.5),
            symbol="o",
            symbolSize=4,
            symbolBrush=COLORS["chart_hr"],
            symbolPen=None,
        )

        layout.addWidget(self._plot_widget)

    def add_sample(self, hr_bpm: int, timestamp_offset: float):
        """Add a new HR sample."""
        self._current_hr = hr_bpm

        idx = self._write_idx % self.max_samples
        self._hr_data[idx] = hr_bpm
        self._hr_time[idx] = timestamp_offset
        self._write_idx += 1

    def update_plot(self):
        """Refresh the plot."""
        if self._write_idx == 0:
            return

        n = min(self._write_idx, self.max_samples)

        if self._write_idx >= self.max_samples:
            start = self._write_idx % self.max_samples
            data = np.concatenate([self._hr_data[start:], self._hr_data[:start]])
            time = np.concatenate([self._hr_time[start:], self._hr_time[:start]])
        else:
            data = self._hr_data[:n]
            time = self._hr_time[:n]

        # Normalize time to relative seconds
        if n > 0:
            time_rel = time - time[-1]
            self._curve.setData(time_rel, data)

        self._bpm_label.setText(f"{self._current_hr} BPM")
