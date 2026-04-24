"""Connection panel widget for device scanning and connection."""

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
from polar_recorder.ui.styles import COLORS


class ConnectionPanel(QWidget):
    """Panel for BLE device discovery and connection management.

    Emits signals when the user selects a device to connect/disconnect.
    """

    # Signals
    scan_requested = Signal()
    connect_requested = Signal(object)  # DeviceInfo
    disconnect_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: list[DeviceInfo] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # ─── Status Indicator ────────────────────────────────────────
        self._status_group = QGroupBox("Connection")
        status_layout = QVBoxLayout(self._status_group)

        # Status dot + text
        status_row = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color: {COLORS['error']}; font-size: 18px; background: transparent;"
        )
        self._status_label = QLabel("Disconnected")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13px; background: transparent;"
        )
        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_label)
        status_row.addStretch()
        status_layout.addLayout(status_row)

        # Device name
        self._device_label = QLabel("No device connected")
        self._device_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        status_layout.addWidget(self._device_label)

        layout.addWidget(self._status_group)

        # ─── Scan Section ────────────────────────────────────────────
        scan_group = QGroupBox("Device Scanner")
        scan_layout = QVBoxLayout(scan_group)

        # Scan button
        self._scan_btn = QPushButton("🔍  Scan for Devices")
        self._scan_btn.setProperty("class", "primary")
        self._scan_btn.clicked.connect(self.scan_requested.emit)
        scan_layout.addWidget(self._scan_btn)

        # Scan progress
        self._scan_progress = QProgressBar()
        self._scan_progress.setRange(0, 0)  # Indeterminate
        self._scan_progress.setFixedHeight(4)
        self._scan_progress.hide()
        scan_layout.addWidget(self._scan_progress)

        # Device list
        self._device_list = QListWidget()
        self._device_list.setMinimumHeight(60)
        self._device_list.setMaximumHeight(120)
        self._device_list.itemDoubleClicked.connect(self._on_device_double_clicked)
        scan_layout.addWidget(self._device_list)

        # Connect/Disconnect buttons
        btn_row = QHBoxLayout()
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setProperty("class", "success")
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        btn_row.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setProperty("class", "danger")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        btn_row.addWidget(self._disconnect_btn)

        scan_layout.addLayout(btn_row)
        layout.addWidget(scan_group)

        # Enable connect on selection
        self._device_list.currentRowChanged.connect(
            lambda row: self._connect_btn.setEnabled(row >= 0)
        )

    # ─── Public Methods ─────────────────────────────────────────────────

    def set_scanning(self, scanning: bool):
        """Update UI to reflect scanning state."""
        self._scan_btn.setEnabled(not scanning)
        self._scan_progress.setVisible(scanning)
        if scanning:
            self._scan_btn.setText("⏳  Scanning...")
            self._device_list.clear()
            self._devices.clear()
        else:
            self._scan_btn.setText("🔍  Scan for Devices")

    def add_device(self, device: DeviceInfo):
        """Add a discovered device to the list."""
        self._devices.append(device)
        item = QListWidgetItem(f"  {device.name}")
        item.setData(Qt.UserRole, len(self._devices) - 1)
        rssi_str = f"{device.rssi} dBm" if device.rssi else "N/A"
        item.setToolTip(f"Address: {device.address}\nRSSI: {rssi_str}")
        self._device_list.addItem(item)

    def set_connected(self, device: DeviceInfo):
        """Update UI to connected state."""
        self._status_dot.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 18px; background: transparent;"
        )
        self._status_label.setText("Connected")
        self._status_label.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 13px; background: transparent;"
        )
        self._device_label.setText(f"{device.name}  •  {device.address}")
        self._device_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 12px; background: transparent;"
        )
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._scan_btn.setEnabled(False)

    def set_disconnected(self):
        """Update UI to disconnected state."""
        self._status_dot.setStyleSheet(
            f"color: {COLORS['error']}; font-size: 18px; background: transparent;"
        )
        self._status_label.setText("Disconnected")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 13px; background: transparent;"
        )
        self._device_label.setText("No device connected")
        self._device_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 12px; background: transparent;"
        )
        self._connect_btn.setEnabled(self._device_list.currentRow() >= 0)
        self._disconnect_btn.setEnabled(False)
        self._scan_btn.setEnabled(True)

    def set_connecting(self):
        """Update UI to connecting state."""
        self._status_dot.setStyleSheet(
            f"color: {COLORS['warning']}; font-size: 18px; background: transparent;"
        )
        self._status_label.setText("Connecting...")
        self._status_label.setStyleSheet(
            f"color: {COLORS['warning']}; font-size: 13px; background: transparent;"
        )
        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(False)

    # ─── Private ────────────────────────────────────────────────────────

    def _on_connect_clicked(self):
        row = self._device_list.currentRow()
        if row >= 0 and row < len(self._devices):
            self.connect_requested.emit(self._devices[row])

    def _on_device_double_clicked(self, item: QListWidgetItem):
        idx = item.data(Qt.UserRole)
        if idx is not None and idx < len(self._devices):
            self.connect_requested.emit(self._devices[idx])
