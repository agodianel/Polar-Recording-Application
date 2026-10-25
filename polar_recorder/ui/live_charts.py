"""Real-time chart widgets using pyqtgraph.

GPU-accelerated plotting for ECG (130 Hz), ACC (25-200 Hz), and HR data
with smooth scrolling, grid lines, and research-grade appearance.
"""

import time
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from polar_recorder.ui.styles import COLORS, chip_style, mono_font, mono_font_family


def setup_pyqtgraph():
    """Configure pyqtgraph global settings for our dark theme."""
    pg.setConfigOptions(
        antialias=True,
        background=COLORS["chart_bg"],
        foreground=COLORS["text_secondary"],
    )


class _ChartBase(QWidget):
    """Common header (title, stream status chip, live value) and plot styling."""

    def __init__(self, title: str, color: str, x_label: str, y_label: str, y_units: str, parent=None):
        super().__init__(parent)
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = self._header = QHBoxLayout()
        header.setSpacing(8)
        title_label = QLabel(f"●  {title}")
        title_label.setStyleSheet(
            f"color: {color}; font-weight: 700; font-size: 14px; background: transparent;"
        )
        self._status_chip = QLabel("—")
        self._status_chip.setToolTip("Live data rate received from the strap")
        self.set_status("—", "muted")
        self._value_label = QLabel("")
        self._value_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-family: '{mono_font_family()}'; "
            f"font-size: 12px; background: transparent;"
        )
        header.addWidget(title_label)
        header.addWidget(self._status_chip)
        header.addStretch()
        header.addWidget(self._value_label)
        layout.addLayout(header)

        self._plot_widget = pg.PlotWidget()
        self._plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self._plot_widget.setLabel("bottom", x_label, units="s")
        self._plot_widget.setLabel("left", y_label, units=y_units)
        self._plot_widget.setMouseEnabled(x=False, y=False)
        self._plot_widget.setMenuEnabled(False)
        self._plot_widget.hideButtons()
        self._plot_widget.getPlotItem().getViewBox().disableAutoRange()

        for axis_name in ["bottom", "left"]:
            axis = self._plot_widget.getAxis(axis_name)
            axis.setPen(pg.mkPen(COLORS["border"], width=1))
            axis.setTextPen(COLORS["text_muted"])
            axis.setStyle(tickFont=mono_font(9))
        # Keep the left axis a fixed width so the three charts line up
        self._plot_widget.getAxis("left").setWidth(60)
        # SI prefixes only make sense for SI units (ECG in V → mV), not "kmG"
        self._plot_widget.getAxis("left").enableAutoSIPrefix(y_units == "V")

        layout.addWidget(self._plot_widget, 1)

    def set_status(self, text: str, level: str) -> None:
        """Update the stream status chip (e.g. "130 Hz" / "no data" / "off")."""
        self._status_chip.setText(text)
        self._status_chip.setStyleSheet(chip_style(level))

    def _auto_y(self, lo: float, hi: float, min_span: float) -> None:
        """Rescale Y only when the data leaves the view or fills a small part of it.

        Rescaling on every frame makes the trace jump around; this hysteresis
        keeps the axis steady while the signal stays in a similar range.
        """
        span = max(hi - lo, min_span)
        mid = (lo + hi) / 2
        target_lo, target_hi = mid - span * 0.6, mid + span * 0.6
        (cur_lo, cur_hi) = self._plot_widget.getPlotItem().getViewBox().viewRange()[1]
        cur_span = cur_hi - cur_lo
        if lo < cur_lo or hi > cur_hi or cur_span > 2.5 * (target_hi - target_lo):
            self._plot_widget.setYRange(target_lo, target_hi, padding=0)


class ECGChartWidget(_ChartBase):
    """Real-time ECG waveform display.

    Shows a continuous scrolling ECG trace at 130 Hz with a configurable
    time window. Optimized for smooth rendering with ring-buffer data.
    """

    def __init__(self, window_seconds: float = 5.0, parent=None):
        super().__init__("ECG", COLORS["chart_ecg"], "Time", "ECG", "V", parent)
        self.window_seconds = window_seconds
        self.sample_rate = 130
        self.buffer_size = int(self.sample_rate * self.window_seconds)
        self._data = np.zeros(self.buffer_size, dtype=np.float32)
        self._write_idx = 0

        self._plot_widget.setXRange(-self.window_seconds, 0, padding=0)
        self._plot_widget.setYRange(-1e-3, 1.5e-3, padding=0)
        self._curve = self._plot_widget.plot(pen=pg.mkPen(COLORS["chart_ecg"], width=1.5))
        self.reset()

    def reset(self):
        self._data[:] = 0
        self._write_idx = 0
        self._curve.setData([], [])
        self._value_label.setText("-- µV")
        self._dirty = False

    def add_samples(self, samples_uv: list):
        """Add new ECG samples to the ring buffer."""
        for val in samples_uv:
            self._data[self._write_idx % self.buffer_size] = val
            self._write_idx += 1
        self._dirty = True

    def update_plot(self):
        """Refresh the plot with current buffer contents."""
        if not self._dirty:
            return
        self._dirty = False

        n = min(self._write_idx, self.buffer_size)
        if self._write_idx >= self.buffer_size:
            start = self._write_idx % self.buffer_size
            display_data = np.concatenate([self._data[start:], self._data[:start]])
        else:
            display_data = self._data[:n]

        # Plot in volts so pyqtgraph's SI prefixes label the axis (µV / mV)
        volts = display_data * 1e-6
        t = np.linspace(-n / self.sample_rate, 0, n, dtype=np.float32)
        self._curve.setData(t, volts)
        self._auto_y(float(volts.min()), float(volts.max()), min_span=0.5e-3)
        self._value_label.setText(f"{display_data[-1]:.0f} µV")


class ACCChartWidget(_ChartBase):
    """Real-time 3-axis accelerometer display.

    Shows X, Y, Z acceleration traces in different colors with
    a scrolling time window.
    """

    def __init__(self, window_seconds: float = 10.0, sample_rate: int = 200, parent=None):
        super().__init__("Accelerometer", COLORS["chart_acc_x"], "Time", "Acceleration", "mG", parent)
        self.window_seconds = window_seconds

        self._plot_widget.setXRange(-self.window_seconds, 0, padding=0)
        self._plot_widget.setYRange(-1200, 1200, padding=0)
        self._plot_widget.addLegend(
            offset=(10, 10),
            labelTextColor=COLORS["text_secondary"],
            labelTextSize="9pt",
        )
        self._curve_x = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_x"], width=1.5), name="X"
        )
        self._curve_y = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_y"], width=1.5), name="Y"
        )
        self._curve_z = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_acc_z"], width=1.5), name="Z"
        )
        self.set_sample_rate(sample_rate)

    def set_sample_rate(self, sample_rate: int):
        """Resize the ring buffers for a new stream rate (clears the chart)."""
        self.sample_rate = sample_rate
        self.buffer_size = int(self.sample_rate * self.window_seconds)
        self._data_x = np.zeros(self.buffer_size, dtype=np.float32)
        self._data_y = np.zeros(self.buffer_size, dtype=np.float32)
        self._data_z = np.zeros(self.buffer_size, dtype=np.float32)
        self.reset()

    def reset(self):
        self._data_x[:] = 0
        self._data_y[:] = 0
        self._data_z[:] = 0
        self._write_idx = 0
        for curve in (self._curve_x, self._curve_y, self._curve_z):
            curve.setData([], [])
        self._value_label.setText("X --  Y --  Z --")
        self._dirty = False

    def add_samples(self, samples_mg: list):
        """Add new accelerometer samples (list of (x, y, z) tuples)."""
        for x, y, z in samples_mg:
            idx = self._write_idx % self.buffer_size
            self._data_x[idx] = x
            self._data_y[idx] = y
            self._data_z[idx] = z
            self._write_idx += 1
        self._dirty = True

    def update_plot(self):
        """Refresh the plot with current buffer contents."""
        if not self._dirty:
            return
        self._dirty = False

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

        lo = float(min(dx.min(), dy.min(), dz.min()))
        hi = float(max(dx.max(), dy.max(), dz.max()))
        self._auto_y(lo, hi, min_span=500)
        self._value_label.setText(f"X {dx[-1]:.0f}  Y {dy[-1]:.0f}  Z {dz[-1]:.0f}")


class HRChartWidget(_ChartBase):
    """Real-time heart rate display.

    Shows the HR trend over a scrolling time window, the current BPM
    in a large readout, and the latest RR interval.
    """

    def __init__(self, window_seconds: float = 120.0, parent=None):
        super().__init__("Heart rate", COLORS["chart_hr"], "Time", "HR", "BPM", parent)
        self.window_seconds = window_seconds
        self.max_samples = int(window_seconds) * 2  # HR arrives ~1/s; leave headroom

        # Times are float64: float32 can't resolve seconds at monotonic/epoch magnitudes
        self._hr_data = np.zeros(self.max_samples, dtype=np.float64)
        self._hr_time = np.zeros(self.max_samples, dtype=np.float64)

        self._bpm_label = QLabel()
        self._bpm_label.setStyleSheet(
            f"color: {COLORS['chart_hr']}; font-weight: 700; "
            f"font-family: '{mono_font_family()}'; font-size: 22px; background: transparent;"
        )
        self._header.addWidget(self._bpm_label)

        self._plot_widget.setXRange(-self.window_seconds, 0, padding=0)
        self._plot_widget.setYRange(40, 120, padding=0)
        self._curve = self._plot_widget.plot(
            pen=pg.mkPen(COLORS["chart_hr"], width=2),
            symbol="o",
            symbolSize=4,
            symbolBrush=COLORS["chart_hr"],
            symbolPen=None,
        )
        self.reset()

    def reset(self):
        self._write_idx = 0
        self._curve.setData([], [])
        self._bpm_label.setText("-- BPM")
        self._value_label.setText("")

    def add_sample(self, hr_bpm: int, rr_intervals_ms: Optional[list] = None,
                   timestamp: Optional[float] = None):
        """Add a new HR sample. `timestamp` is a time.monotonic() value."""
        idx = self._write_idx % self.max_samples
        self._hr_data[idx] = hr_bpm
        self._hr_time[idx] = time.monotonic() if timestamp is None else timestamp
        self._write_idx += 1

        self._bpm_label.setText(f"{hr_bpm} BPM")
        if rr_intervals_ms:
            self._value_label.setText(f"RR {rr_intervals_ms[-1]:.0f} ms")

    def update_plot(self):
        """Refresh the plot. Runs every frame so the trace scrolls even between samples."""
        if self._write_idx == 0:
            return

        n = min(self._write_idx, self.max_samples)
        if self._write_idx >= self.max_samples:
            start = self._write_idx % self.max_samples
            data = np.concatenate([self._hr_data[start:], self._hr_data[:start]])
            times = np.concatenate([self._hr_time[start:], self._hr_time[:start]])
        else:
            data = self._hr_data[:n]
            times = self._hr_time[:n]

        time_rel = times - time.monotonic()
        visible = time_rel >= -self.window_seconds
        self._curve.setData(time_rel[visible], data[visible])
        if visible.any():
            self._auto_y(float(data[visible].min()), float(data[visible].max()), min_span=30)
