"""Recording session lifecycle and marker management.

Orchestrates the creation of output files, data routing to writers,
and session metadata.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

import numpy as np

from polar_recorder.ble.data_models import (
    ECGSample,
    ACCSample,
    HRSample,
    MarkerEvent,
    DeviceInfo,
)
from polar_recorder.recording.writer import CSVWriter
from polar_recorder.utils.config import APP_NAME, APP_VERSION, RecordingConfig, StreamConfig

logger = logging.getLogger(__name__)

TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def _format_ts(dt: datetime) -> str:
    return dt.strftime(TS_FORMAT)[:-3]


def sanitize_folder_name(name: str) -> str:
    """Make a user-entered label safe to use as a folder name on any OS."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name.strip().rstrip(".")


def frame_sample_timestamps(
    frame_ts_ns: int, prev_frame_ts_ns: Optional[int], n: int, nominal_rate_hz: float
) -> tuple[list[int], float]:
    """Per-sample sensor timestamps for a PMD frame.

    Polar stamps each frame with the time of its *last* sample (the convention
    the Polar BLE SDK uses). The sample period is taken from the gap to the
    previous frame, which follows the strap's real clock (~130.2 Hz rather than
    exactly 130 Hz); it falls back to the nominal rate for the first frame or
    when a frame was dropped.

    Returns:
        (timestamps in ns, sample period in ns)
    """
    period = 1e9 / nominal_rate_hz
    if prev_frame_ts_ns is not None and n > 0:
        measured = (frame_ts_ns - prev_frame_ts_ns) / n
        if abs(measured - period) <= 0.1 * period:
            period = measured
    return [round(frame_ts_ns - (n - 1 - i) * period) for i in range(n)], period


class RecordingSession:
    """Manages a single data recording session.

    Creates timestamped output files matching the Android app format,
    routes incoming data to the appropriate writers, and manages markers.
    """

    def __init__(
        self,
        device_info: DeviceInfo,
        config: RecordingConfig,
        stream_config: StreamConfig,
        label: str = "",
        battery_level: Optional[int] = None,
    ):
        self.device_info = device_info
        self.config = config
        self.stream_config = stream_config
        self.label = label.strip()
        self.battery_level = battery_level

        self._session_start: Optional[datetime] = None
        self._session_end: Optional[datetime] = None
        self._end_reason: Optional[str] = None
        self._active = False

        # Writers for each data type
        self._ecg_writer: Optional[CSVWriter] = None
        self._acc_writer: Optional[CSVWriter] = None
        self._hr_writer: Optional[CSVWriter] = None
        self._rr_writer: Optional[CSVWriter] = None
        self._marker_writer: Optional[CSVWriter] = None

        # Statistics and buffers
        self._ecg_sample_count = 0
        self._acc_sample_count = 0
        self._hr_sample_count = 0
        self._rr_sample_count = 0
        self._markers: List[MarkerEvent] = []
        self._rr_buffer: List[float] = []  # For HRV RMSSD calculation

        # Previous frame timestamps, for per-sample timestamp interpolation
        self._prev_ecg_frame_ts: Optional[int] = None
        self._prev_acc_frame_ts: Optional[int] = None
        self._first_ecg_ts: Optional[int] = None

        # Session directory
        self._session_dir: Optional[Path] = None

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def session_dir(self) -> Optional[Path]:
        return self._session_dir

    @property
    def start_time(self) -> Optional[datetime]:
        return self._session_start

    @property
    def duration_seconds(self) -> float:
        """Elapsed time since session start."""
        if self._session_start is None:
            return 0.0
        end = self._session_end or datetime.now()
        return (end - self._session_start).total_seconds()

    @property
    def stats(self) -> dict:
        """Current recording statistics."""
        return {
            "ecg_samples": self._ecg_sample_count,
            "acc_samples": self._acc_sample_count,
            "hr_samples": self._hr_sample_count,
            "rr_samples": self._rr_sample_count,
            "markers": len(self._markers),
            "duration_sec": self.duration_seconds,
        }

    def _make_session_dir(self, timestamp_str: str) -> Path:
        default_name = (
            f"{self.device_info.device_model}_{self.device_info.device_id}"
            f"_{timestamp_str}"
        )
        name = sanitize_folder_name(self.label) or default_name
        path = self.config.output_dir / name
        if path.exists() and self.label:
            path = self.config.output_dir / f"{name}_{timestamp_str}"
        counter = 2
        base = path
        while path.exists():
            path = base.with_name(f"{base.name}_{counter}")
            counter += 1
        path.mkdir(parents=True)
        return path

    def start(self) -> Path:
        """Start a new recording session, creating output files.

        Returns:
            Path to the session output directory.
        """
        self._session_start = datetime.now()
        timestamp_str = self._session_start.strftime("%Y%m%d_%H%M%S")
        self._session_dir = self._make_session_dir(timestamp_str)

        # File naming: match Android app format
        base = f"{self.device_info.device_model}_{self.device_info.device_id}_{timestamp_str}"
        flush_sec = self.config.flush_interval_sec

        # Create writers for enabled streams
        if self.stream_config.ecg.enabled:
            self._ecg_writer = CSVWriter(
                self._session_dir / f"{base}_ECG.txt",
                header="Phone timestamp;sensor timestamp [ns];timestamp [ms];ecg [uV]",
                flush_interval_sec=flush_sec,
            )

        if self.stream_config.acc.enabled:
            self._acc_writer = CSVWriter(
                self._session_dir / f"{base}_ACC.txt",
                header="Phone timestamp;sensor timestamp [ns];X [mg];Y [mg];Z [mg]",
                flush_interval_sec=flush_sec,
            )

        if self.stream_config.hr.enabled:
            self._hr_writer = CSVWriter(
                self._session_dir / f"{base}_HR.txt",
                header="Phone timestamp;HR [bpm];HRV [ms];Breathing interval [rpm];",
                flush_interval_sec=flush_sec,
            )
            self._rr_writer = CSVWriter(
                self._session_dir / f"{base}_RR.txt",
                header="Phone timestamp;RR-interval [ms]",
                flush_interval_sec=flush_sec,
            )

        # Marker writer — markers are rare and important, write each one immediately
        self._marker_writer = CSVWriter(
            self._session_dir / f"MARKER_{timestamp_str}.txt",
            header="Phone timestamp;Marker start/stop",
            buffer_size=1,
        )

        self._active = True
        # Written now so a crashed session still documents its configuration
        self._write_metadata()
        logger.info(f"Recording session started: {self._session_dir}")
        return self._session_dir

    def stop(self, reason: str = "user") -> dict:
        """Stop the recording session, flush and close all writers.

        Args:
            reason: Why the session ended (stored in the metadata).

        Returns:
            Final session statistics.
        """
        if not self._active:
            return self.stats

        self._session_end = datetime.now()
        self._end_reason = reason
        self._active = False

        # Close all writers; keep going if one fails so the others still get saved
        for writer in [
            self._ecg_writer,
            self._acc_writer,
            self._hr_writer,
            self._rr_writer,
            self._marker_writer,
        ]:
            if writer:
                try:
                    writer.close()
                except OSError as e:
                    logger.error(f"Failed to close {writer.filepath}: {e}")

        # Write session metadata
        try:
            self._write_metadata()
        except OSError as e:
            logger.error(f"Failed to write session metadata: {e}")

        stats = self.stats
        logger.info(
            f"Recording session stopped ({reason}). Duration: {stats['duration_sec']:.1f}s, "
            f"ECG: {stats['ecg_samples']}, ACC: {stats['acc_samples']}, "
            f"HR: {stats['hr_samples']}, RR: {stats['rr_samples']}"
        )
        return stats

    def write_ecg(self, sample: ECGSample) -> None:
        """Write ECG data to file.

        Expands the packet into individual samples with interpolated sensor and
        phone timestamps, matching the Android app's output format.
        """
        if not self._active or not self._ecg_writer:
            return

        n = len(sample.samples_uv)
        sensor_ts, period_ns = frame_sample_timestamps(
            sample.sensor_timestamp_ns, self._prev_ecg_frame_ts, n,
            self.stream_config.ecg.sample_rate,
        )
        self._prev_ecg_frame_ts = sample.sensor_timestamp_ns
        if self._first_ecg_ts is None and sensor_ts:
            self._first_ecg_ts = sensor_ts[0]

        for i, (ts_ns, uv_value) in enumerate(zip(sensor_ts, sample.samples_uv)):
            phone_ts = sample.phone_timestamp - timedelta(
                microseconds=(n - 1 - i) * period_ns / 1000
            )
            elapsed_ms = (ts_ns - self._first_ecg_ts) / 1e6
            self._ecg_writer.write_row(
                f"{_format_ts(phone_ts)};{ts_ns};{elapsed_ms};{uv_value}"
            )
            self._ecg_sample_count += 1

    def write_acc(self, sample: ACCSample) -> None:
        """Write accelerometer data to file, one timestamped row per sample."""
        if not self._active or not self._acc_writer:
            return

        n = len(sample.samples_mg)
        sensor_ts, period_ns = frame_sample_timestamps(
            sample.sensor_timestamp_ns, self._prev_acc_frame_ts, n,
            self.stream_config.acc.sample_rate,
        )
        self._prev_acc_frame_ts = sample.sensor_timestamp_ns

        for i, (ts_ns, (x, y, z)) in enumerate(zip(sensor_ts, sample.samples_mg)):
            phone_ts = sample.phone_timestamp - timedelta(
                microseconds=(n - 1 - i) * period_ns / 1000
            )
            self._acc_writer.write_row(f"{_format_ts(phone_ts)};{ts_ns};{x};{y};{z}")
            self._acc_sample_count += 1

    def write_hr(self, sample: HRSample) -> None:
        """Write heart rate and RR interval data to files."""
        if not self._active:
            return

        ts_str = _format_ts(sample.phone_timestamp)

        # HR file
        if self._hr_writer:
            hrv_str = ""
            if sample.rr_intervals_ms:
                self._rr_buffer.extend(sample.rr_intervals_ms)
                # Keep last 30 RR intervals to calculate RMSSD (standard short-term HRV metric)
                self._rr_buffer = self._rr_buffer[-30:]

                if len(self._rr_buffer) >= 2:
                    diffs = np.diff(self._rr_buffer)
                    rmssd = np.sqrt(np.mean(diffs**2))
                    hrv_str = f"{rmssd:.1f}"

            # We write an empty value for Breathing Interval as calculating it requires complex DSP from the ECG trace.
            # Notice the extra semicolon at the end to match the 4 columns in the header.
            self._hr_writer.write_row(f"{ts_str};{sample.heart_rate_bpm};{hrv_str};;")
            self._hr_sample_count += 1

        # RR file
        if self._rr_writer and sample.rr_intervals_ms:
            for rr in sample.rr_intervals_ms:
                self._rr_writer.write_row(f"{ts_str};{round(rr)}")
                self._rr_sample_count += 1

    def add_marker(self, marker_type: str = "MARKER_START", label: str = "") -> Optional[MarkerEvent]:
        """Add a marker/annotation to the recording."""
        if not self._active:
            return None

        now = datetime.now()
        marker = MarkerEvent(
            phone_timestamp=now,
            marker_type=marker_type,
            label=label.strip(),
        )
        self._markers.append(marker)

        if self._marker_writer:
            # Same layout as the Android app: "MARKER_START " with an empty label
            self._marker_writer.write_row(f"{_format_ts(now)};{marker_type} {marker.label}")

        logger.info(f"Marker added: {marker_type} {marker.label}")
        return marker

    def _write_metadata(self) -> None:
        """Write session metadata JSON file."""
        if not self._session_dir:
            return

        metadata = {
            "label": self.label,
            "device": {
                "name": self.device_info.name,
                "address": self.device_info.address,
                "model": self.device_info.device_model,
                "id": self.device_info.device_id,
                "battery_level_at_start": self.battery_level,
            },
            "session": {
                "start": self._session_start.isoformat() if self._session_start else None,
                "end": self._session_end.isoformat() if self._session_end else None,
                "duration_seconds": self.duration_seconds,
                "end_reason": self._end_reason,
            },
            "streams": {
                "ecg": {
                    "enabled": self.stream_config.ecg.enabled,
                    "sample_rate": self.stream_config.ecg.sample_rate,
                    "resolution": self.stream_config.ecg.resolution,
                    "total_samples": self._ecg_sample_count,
                },
                "acc": {
                    "enabled": self.stream_config.acc.enabled,
                    "sample_rate": self.stream_config.acc.sample_rate,
                    "resolution": self.stream_config.acc.resolution,
                    "range_g": self.stream_config.acc.range_g,
                    "total_samples": self._acc_sample_count,
                },
                "hr": {
                    "enabled": self.stream_config.hr.enabled,
                    "total_samples": self._hr_sample_count,
                    "total_rr_intervals": self._rr_sample_count,
                },
            },
            "markers": [
                {
                    "timestamp": m.phone_timestamp.isoformat(),
                    "type": m.marker_type,
                    "label": m.label,
                }
                for m in self._markers
            ],
            "software": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "platform": "PC/Python",
            },
        }

        meta_path = self._session_dir / "session_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.debug(f"Session metadata saved: {meta_path}")
