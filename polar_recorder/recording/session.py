"""Recording session lifecycle and marker management.

Orchestrates the creation of output files, data routing to writers,
and session metadata.
"""

import json
import logging
from datetime import datetime
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
from polar_recorder.utils.config import RecordingConfig, StreamConfig

logger = logging.getLogger(__name__)


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
    ):
        self.device_info = device_info
        self.config = config
        self.stream_config = stream_config

        self._session_start: Optional[datetime] = None
        self._session_end: Optional[datetime] = None
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

        # Session directory
        self._session_dir: Optional[Path] = None

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def session_dir(self) -> Optional[Path]:
        return self._session_dir

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

    def start(self) -> Path:
        """Start a new recording session, creating output files.

        Returns:
            Path to the session output directory.
        """
        self._session_start = datetime.now()
        timestamp_str = self._session_start.strftime("%Y%m%d_%H%M%S")

        # Create session directory
        session_name = (
            f"{self.device_info.device_model}_{self.device_info.device_id}"
            f"_{timestamp_str}"
        )
        self._session_dir = self.config.output_dir / session_name
        self._session_dir.mkdir(parents=True, exist_ok=True)

        # File naming: match Android app format
        base = f"{self.device_info.device_model}_{self.device_info.device_id}_{timestamp_str}"

        # Create writers for enabled streams
        if self.stream_config.ecg.enabled:
            self._ecg_writer = CSVWriter(
                self._session_dir / f"{base}_ECG.txt",
                header="Phone timestamp;sensor timestamp [ns];timestamp [ms];ecg [uV]",
            )

        if self.stream_config.acc.enabled:
            self._acc_writer = CSVWriter(
                self._session_dir / f"{base}_ACC.txt",
                header="Phone timestamp;sensor timestamp [ns];X [mg];Y [mg];Z [mg]",
            )

        if self.stream_config.hr.enabled:
            self._hr_writer = CSVWriter(
                self._session_dir / f"{base}_HR.txt",
                header="Phone timestamp;HR [bpm];HRV [ms];Breathing interval [rpm];",
            )
            self._rr_writer = CSVWriter(
                self._session_dir / f"{base}_RR.txt",
                header="Phone timestamp;RR-interval [ms]",
            )

        # Marker writer
        self._marker_writer = CSVWriter(
            self._session_dir / f"MARKER_{timestamp_str}.txt",
            header="Phone timestamp;Marker start/stop",
        )

        self._active = True
        logger.info(f"Recording session started: {self._session_dir}")
        return self._session_dir

    def stop(self) -> dict:
        """Stop the recording session, flush and close all writers.

        Returns:
            Final session statistics.
        """
        self._session_end = datetime.now()
        self._active = False

        # Close all writers
        for writer in [
            self._ecg_writer,
            self._acc_writer,
            self._hr_writer,
            self._rr_writer,
            self._marker_writer,
        ]:
            if writer:
                writer.close()

        # Write session metadata
        self._write_metadata()

        stats = self.stats
        logger.info(
            f"Recording session stopped. Duration: {stats['duration_sec']:.1f}s, "
            f"ECG: {stats['ecg_samples']}, ACC: {stats['acc_samples']}, "
            f"HR: {stats['hr_samples']}, RR: {stats['rr_samples']}"
        )
        return stats

    def write_ecg(self, sample: ECGSample) -> None:
        """Write ECG data to file.

        Expands the packet into individual samples with interpolated timestamps,
        matching the Android app's output format.
        """
        if not self._active or not self._ecg_writer:
            return

        base_ts_ns = sample.sensor_timestamp_ns
        period_ns = int(1e9 / sample.sample_rate)  # ~7,692,308 ns for 130 Hz

        for i, uv_value in enumerate(sample.samples_uv):
            sample_ts_ns = base_ts_ns + (i * period_ns)
            elapsed_ms = (i * period_ns) / 1e6

            ts_str = sample.phone_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            self._ecg_writer.write_row(
                f"{ts_str};{sample_ts_ns};{elapsed_ms:.6f};{uv_value}"
            )
            self._ecg_sample_count += 1

    def write_acc(self, sample: ACCSample) -> None:
        """Write accelerometer data to file."""
        if not self._active or not self._acc_writer:
            return

        for x, y, z in sample.samples_mg:
            ts_str = sample.phone_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            self._acc_writer.write_row(
                f"{ts_str};{sample.sensor_timestamp_ns};{x};{y};{z}"
            )
            self._acc_sample_count += 1

    def write_hr(self, sample: HRSample) -> None:
        """Write heart rate and RR interval data to files."""
        if not self._active:
            return

        ts_str = sample.phone_timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

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
                rr_ts_str = sample.phone_timestamp.strftime(
                    "%Y-%m-%dT%H:%M:%S.%f"
                )[:-3]
                self._rr_writer.write_row(f"{rr_ts_str};{int(rr)}")
                self._rr_sample_count += 1

    def add_marker(self, marker_type: str = "MARKER_START", label: str = "") -> None:
        """Add a marker/annotation to the recording."""
        if not self._active:
            return

        now = datetime.now()
        marker = MarkerEvent(
            phone_timestamp=now,
            marker_type=marker_type,
            label=label,
        )
        self._markers.append(marker)

        if self._marker_writer:
            ts_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            self._marker_writer.write_row(f"{ts_str};{marker_type} {label}".strip())

        logger.info(f"Marker added: {marker_type} {label}")

    def _write_metadata(self) -> None:
        """Write session metadata JSON file."""
        if not self._session_dir:
            return

        metadata = {
            "device": {
                "name": self.device_info.name,
                "address": self.device_info.address,
                "model": self.device_info.device_model,
                "id": self.device_info.device_id,
            },
            "session": {
                "start": self._session_start.isoformat() if self._session_start else None,
                "end": self._session_end.isoformat() if self._session_end else None,
                "duration_seconds": self.duration_seconds,
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
                "name": "PolarRecorder",
                "version": "1.0.0",
                "platform": "PC/Python",
            },
        }

        meta_path = self._session_dir / "session_metadata.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Session metadata saved: {meta_path}")
