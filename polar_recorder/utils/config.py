"""Application configuration and constants."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ─── Paths ──────────────────────────────────────────────────────────────────────
APP_NAME = "PolarRecorder"
APP_VERSION = "1.0.0"
# Store recordings inside the app directory, not home
_APP_DIR = Path(__file__).resolve().parent.parent.parent  # -> PolarRecorder/
DEFAULT_DATA_DIR = _APP_DIR / "recordings"


# ─── BLE Constants ──────────────────────────────────────────────────────────────
SCAN_TIMEOUT_SEC = 10
POLAR_DEVICE_PREFIX = "Polar"
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY_SEC = 2


# ─── Stream Configurations ──────────────────────────────────────────────────────
@dataclass
class ECGConfig:
    """ECG stream configuration for Polar H10."""
    sample_rate: int = 130
    resolution: int = 14
    enabled: bool = True


@dataclass
class ACCConfig:
    """Accelerometer stream configuration for Polar H10."""
    sample_rate: int = 200  # 25, 50, 100, 200 Hz
    resolution: int = 16
    range_g: int = 8  # 2, 4, 8 G
    enabled: bool = True


@dataclass
class HRConfig:
    """Heart rate stream configuration."""
    enabled: bool = True


@dataclass
class StreamConfig:
    """Complete stream configuration bundle."""
    ecg: ECGConfig = field(default_factory=ECGConfig)
    acc: ACCConfig = field(default_factory=ACCConfig)
    hr: HRConfig = field(default_factory=HRConfig)


# ─── Chart Settings ─────────────────────────────────────────────────────────────
@dataclass
class ChartConfig:
    """Live chart display settings."""
    ecg_window_seconds: float = 5.0    # How many seconds of ECG to show
    acc_window_seconds: float = 10.0   # How many seconds of ACC to show
    hr_window_seconds: float = 120.0   # How many seconds of HR history
    update_rate_ms: int = 33           # ~30 FPS chart refresh


# ─── Recording Settings ─────────────────────────────────────────────────────────
@dataclass
class RecordingConfig:
    """Recording session settings."""
    output_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    file_format: str = "csv"  # csv or hdf5
    flush_interval_sec: float = 1.0  # How often to flush to disk


@dataclass
class AppConfig:
    """Main application configuration."""
    streams: StreamConfig = field(default_factory=StreamConfig)
    charts: ChartConfig = field(default_factory=ChartConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)

    def ensure_dirs(self) -> None:
        """Create necessary directories."""
        self.recording.output_dir.mkdir(parents=True, exist_ok=True)
