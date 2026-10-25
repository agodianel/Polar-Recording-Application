"""Connection panel widget for device scanning and connection."""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QGroupBox,
    QProgressBar,
)
from PySide6.QtCore import Signal, Qt

from polar_recorder.ble.data_models import DeviceInfo
from polar_recorder.ui.styles import COLORS, chip_style, dot_style, repolish


class ConnectionPanel(QWidget):
    """Panel for BLE device discovery and connection management.

    Emits signals when the user selects a device to connect/disconnect.
    Button availability is derived from a single state so it can't drift.
    """

    IDLE, SCANNING, CONNECTING, CONNECTED = range(4)

    # Signals
    scan_requested = Signal()
    stop_scan_requested = Signal()
    connect_requested = Signal(object)  # DeviceInfo
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: list[DeviceInfo] = []
        self._state = self.IDLE
        self._setup_ui()
        self._apply_state()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        group = QGroupBox("Device")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        # ─── Status row: dot + text + battery ───────────────────────
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._status_dot = QLabel("●")
        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-size: 14px; font-weight: 600; background: transparent;")
        self._battery_chip = QLabel()
        self._battery_chip.setToolTip("Strap battery level")
        self._battery_chip.hide()
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_row.addWidget(self._battery_chip)
        group_layout.addLayout(status_row)

        self._device_label = QLabel()
        self._device_label.setProperty("class", "secondary")
        self._device_label.setWordWrap(True)
        group_layout.addWidget(self._device_label)

        self._contact_label = QLabel()
        self._contact_label.setProperty("class", "muted")
        self._contact_label.setToolTip(
            "Whether the strap's electrodes touch the skin. Moisten the electrodes "
            "and tighten the strap if contact is lost."
        )
        self._contact_label.hide()
        group_layout.addWidget(self._contact_label)

        # ─── Scanner ─────────────────────────────────────────────────
        self._scan_btn = QPushButton()
        self._scan_btn.setProperty("class", "primary")
        self._scan_btn.clicked.connect(self._on_scan_clicked)
        group_layout.addWidget(self._scan_btn)

        self._scan_progress = QProgressBar()
        self._scan_progress.setRange(0, 0)  # Indeterminate
        self._scan_progress.setFixedHeight(3)
        self._scan_progress.setTextVisible(False)
        self._scan_progress.hide()
        group_layout.addWidget(self._scan_progress)

        self._device_list = QListWidget()
        self._device_list.setMinimumHeight(56)
        self._device_list.setMaximumHeight(110)
        self._device_list.setToolTip("Double-click a device to connect")
        self._device_list.itemDoubleClicked.connect(self._on_device_double_clicked)
        self._device_list.currentRowChanged.connect(lambda _row: self._apply_state())
        group_layout.addWidget(self._device_list)

        self._hint_label = QLabel()
        self._hint_label.setProperty("class", "muted")
        self._hint_label.setWordWrap(True)
        group_layout.addWidget(self._hint_label)

        self._action_btn = QPushButton()
        self._action_btn.clicked.connect(self._on_action_clicked)
        group_layout.addWidget(self._action_btn)

        layout.addWidget(group)

    # ─── Public Methods ─────────────────────────────────────────────────

    @property
    def state(self) -> int:
        return self._state

    def set_scanning(self, scanning: bool):
        """Update UI to reflect scanning state."""
        if scanning:
            self._device_list.clear()
            self._devices.clear()
            self._state = self.SCANNING
        elif self._state == self.SCANNING:
            self._state = self.IDLE
        self._apply_state()

    def add_device(self, device: DeviceInfo):
        """Add a discovered device to the list."""
        self._devices.append(device)
        rssi_str = f"{device.rssi} dBm" if device.rssi is not None else "N/A"
        item = QListWidgetItem(f"{device.name}    {rssi_str}")
        item.setData(Qt.UserRole, len(self._devices) - 1)
        item.setToolTip(f"Address: {device.address}\nSignal: {rssi_str}")
        self._device_list.addItem(item)
        if self._device_list.currentRow() < 0:
            self._device_list.setCurrentRow(0)
        self._apply_state()

    def set_connecting(self, device: DeviceInfo):
        """Update UI to connecting state."""
        self._state = self.CONNECTING
        self._device_label.setText(device.name)
        self._apply_state()

    def set_connected(self, device: DeviceInfo, battery_level: Optional[int] = None):
        """Update UI to connected state."""
        self._state = self.CONNECTED
        self._device_label.setText(f"{device.name}  •  {device.address}")
        self.set_battery(battery_level)
        self.set_contact(None, waiting=True)
        self._apply_state()

    def set_disconnected(self):
        """Update UI to disconnected state."""
        self._state = self.IDLE
        self.set_battery(None)
        self._contact_label.hide()
        self._apply_state()

    def set_battery(self, level: Optional[int]):
        if level is None:
            self._battery_chip.hide()
            return
        status = "ok" if level > 30 else "warning" if level > 10 else "error"
        self._battery_chip.setText(f"Battery {level}%")
        self._battery_chip.setStyleSheet(chip_style(status))
        self._battery_chip.show()

    def set_contact(self, contact: Optional[bool], waiting: bool = False):
        """Show skin contact as reported by the strap.

        contact is None either while waiting for the first HR packet
        (waiting=True) or when the strap doesn't report contact.
        """
        if contact is None:
            text = "Skin contact: waiting for data…" if waiting else "Skin contact: not reported"
            color = COLORS["text_muted"]
        elif contact:
            text, color = "Skin contact: good", COLORS["success"]
        else:
            text, color = "Skin contact: NOT detected — moisten electrodes", COLORS["warning"]
        self._contact_label.setText(text)
        self._contact_label.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")
        self._contact_label.show()

    # ─── Private ────────────────────────────────────────────────────────

    def _apply_state(self):
        state = self._state
        has_selection = 0 <= self._device_list.currentRow() < len(self._devices)

        status = {
            self.IDLE: ("Disconnected", "error"),
            self.SCANNING: ("Scanning…", "info"),
            self.CONNECTING: ("Connecting…", "warning"),
            self.CONNECTED: ("Connected", "ok"),
        }[state]
        self._status_label.setText(status[0])
        self._status_dot.setStyleSheet(dot_style(status[1]))
        if state in (self.IDLE, self.SCANNING):
            self._device_label.setText("No device connected")

        # The scanner is only relevant while choosing a device
        choosing = state in (self.IDLE, self.SCANNING)
        self._scan_btn.setText("Stop scanning" if state == self.SCANNING else "Scan for devices")
        self._scan_btn.setVisible(choosing)
        self._scan_progress.setVisible(state == self.SCANNING)
        self._device_list.setVisible(choosing and bool(self._devices))

        if state == self.CONNECTED:
            self._action_btn.setText("Disconnect")
            self._action_btn.setProperty("class", "danger")
            self._action_btn.setEnabled(True)
        elif state == self.CONNECTING:
            self._action_btn.setText("Connecting…")
            self._action_btn.setProperty("class", "success")
            self._action_btn.setEnabled(False)
        else:
            self._action_btn.setText("Connect")
            self._action_btn.setProperty("class", "success")
            self._action_btn.setEnabled(has_selection)
        repolish(self._action_btn)

        if state == self.IDLE and not self._devices:
            hint = "Wear the strap (it sleeps without skin contact), then scan."
        elif state == self.SCANNING and not self._devices:
            hint = "Looking for Polar devices…"
        elif state == self.CONNECTING:
            hint = "Accept any pairing prompt from the operating system."
        else:
            hint = ""
        self._hint_label.setText(hint)
        self._hint_label.setVisible(bool(hint))

    def _on_scan_clicked(self):
        if self._state == self.SCANNING:
            self.stop_scan_requested.emit()
        elif self._state == self.IDLE:
            self.scan_requested.emit()

    def _on_action_clicked(self):
        if self._state == self.CONNECTED:
            self.disconnect_requested.emit()
            return
        row = self._device_list.currentRow()
        if self._state in (self.IDLE, self.SCANNING) and 0 <= row < len(self._devices):
            self.connect_requested.emit(self._devices[row])

    def _on_device_double_clicked(self, item: QListWidgetItem):
        if self._state not in (self.IDLE, self.SCANNING):
            return
        idx = item.data(Qt.UserRole)
        if idx is not None and idx < len(self._devices):
            self.connect_requested.emit(self._devices[idx])
