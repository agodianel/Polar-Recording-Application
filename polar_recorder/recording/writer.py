"""File writers for recording data to disk.

Supports CSV (semicolon-delimited, matching Android app format).
"""

import logging
from pathlib import Path
from typing import Optional, TextIO

logger = logging.getLogger(__name__)


class CSVWriter:
    """Buffered CSV file writer with semicolon delimiter.

    Matches the output format of the Polar Sensor Logger Android app
    for maximum compatibility with existing research pipelines.
    """

    def __init__(self, filepath: Path, header: str, buffer_size: int = 100):
        """Initialize a CSV writer.

        Args:
            filepath: Output file path.
            header: Header line (semicolon-separated column names).
            buffer_size: Number of rows to buffer before flushing.
        """
        self.filepath = filepath
        self.buffer_size = buffer_size
        self._buffer: list[str] = []
        self._file: Optional[TextIO] = None
        self._row_count = 0

        # Open file and write header
        self._file = open(filepath, "w", encoding="utf-8", newline="")
        self._file.write(header + "\r\n")
        self._file.flush()

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

        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def flush(self) -> None:
        """Flush buffered rows to disk."""
        if self._file and self._buffer:
            self._file.write("\r\n".join(self._buffer) + "\r\n")
            self._file.flush()
            self._buffer.clear()

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
        self.close()
