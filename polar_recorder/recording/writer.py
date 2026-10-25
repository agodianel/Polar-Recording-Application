"""File writers for recording data to disk.

Supports CSV (semicolon-delimited, matching Android app format).
"""

import logging
import time
from pathlib import Path
from typing import Optional, TextIO

logger = logging.getLogger(__name__)


class CSVWriter:
    """Buffered CSV file writer with semicolon delimiter.

    Matches the output format of the Polar Sensor Logger Android app
    for maximum compatibility with existing research pipelines.
    """

    def __init__(
        self,
        filepath: Path,
        header: str,
        buffer_size: int = 100,
        flush_interval_sec: float = 1.0,
    ):
        """Initialize a CSV writer.

        Args:
            filepath: Output file path.
            header: Header line (semicolon-separated column names).
            buffer_size: Number of rows to buffer before flushing.
            flush_interval_sec: Max time rows may sit in the buffer, so slow
                streams (HR, markers) still reach the disk promptly.
        """
        self.filepath = filepath
        self.buffer_size = buffer_size
        self.flush_interval_sec = flush_interval_sec
        self._buffer: list[str] = []
        self._file: Optional[TextIO] = None
        self._row_count = 0

        # Open file and write header
        self._file = open(filepath, "w", encoding="utf-8", newline="")
        self._file.write(header + "\r\n")
        self._file.flush()
        self._last_flush = time.monotonic()

        logger.debug(f"CSVWriter opened: {filepath}")

    def write_row(self, row: str) -> None:
        """Write a single data row.

        Args:
            row: Semicolon-separated data string (no newline needed).
        """
        if self._file is None:
            return

        self._buffer.append(row)
        self._row_count += 1

        if (
            len(self._buffer) >= self.buffer_size
            or time.monotonic() - self._last_flush >= self.flush_interval_sec
        ):
            self.flush()

    def flush(self) -> None:
        """Flush buffered rows to disk."""
        if self._file and self._buffer:
            self._file.write("\r\n".join(self._buffer) + "\r\n")
            self._file.flush()
            self._buffer.clear()
        self._last_flush = time.monotonic()

    def close(self) -> None:
        """Flush remaining buffer and close the file."""
        self.flush()
        if self._file:
            self._file.close()
            self._file = None
            logger.debug(
                f"CSVWriter closed: {self.filepath} ({self._row_count} rows)"
            )

    @property
    def row_count(self) -> int:
        return self._row_count

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
