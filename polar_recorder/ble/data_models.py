"""Data models for BLE stream data with timestamps."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class ECGSample:
    """A single ECG data packet from the Polar H10.

    Each packet from polar-python contains a sensor timestamp (nanoseconds)
    and a list of µV values sampled at 130 Hz.
    """
    phone_timestamp: datetime
    sensor_timestamp_ns: int
    samples_uv: List[int] = field(default_factory=list)

    @property
    def sample_rate(self) -> int:
        return 130

    @property
    def sample_period_ms(self) -> float:
        """Time between individual samples in ms."""
        return 1000.0 / self.sample_rate


@dataclass
class ACCSample:
    """A single accelerometer data packet from the Polar H10.

    Each packet contains a sensor timestamp (nanoseconds) and a list of
    (X, Y, Z) tuples in milliG.
    """
    phone_timestamp: datetime
    sensor_timestamp_ns: int
    samples_mg: List[Tuple[int, int, int]] = field(default_factory=list)


@dataclass
class HRSample:
    """A heart rate data point from the Polar H10.

    Includes the instantaneous HR and any RR intervals detected since
    the last HR notification.
    """
    phone_timestamp: datetime
    heart_rate_bpm: int
    rr_intervals_ms: List[float] = field(default_factory=list)


@dataclass
class MarkerEvent:
    """A user-placed marker/annotation during a recording session."""
    phone_timestamp: datetime
    marker_type: str  # "MARKER_START", "MARKER_STOP", or custom label
    label: str = ""


@dataclass
class DeviceInfo:
    """Discovered Polar device information."""
    name: str
    address: str
    rssi: Optional[int] = None
    ble_device: object = None  # Raw BLEDevice from bleak, carried from scan to connect

    @property
    def device_id(self) -> str:
        """Extract device ID from name (e.g., 'Polar H10 16E0A933' -> '16E0A933')."""
        parts = self.name.split()
        return parts[-1] if len(parts) >= 3 else self.address.replace(":", "")

    @property
    def device_model(self) -> str:
        """Extract model from name (e.g., 'Polar H10 16E0A933' -> 'Polar_H10')."""
        parts = self.name.split()
        if len(parts) >= 2:
            return f"{parts[0]}_{parts[1]}"
        return self.name.replace(" ", "_")

    def __str__(self) -> str:
        rssi_str = f" ({self.rssi} dBm)" if self.rssi is not None else ""
        return f"{self.name}{rssi_str}"
