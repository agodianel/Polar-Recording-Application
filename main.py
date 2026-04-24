#!/usr/bin/env python3
"""
PolarRecorder — Polar H10 ECG Band Data Acquisition & Live Visualization

A professional-grade Python desktop application for recording and
visualizing data from the Polar H10 ECG chest strap.

Capabilities:
  - ECG (130 Hz, 14-bit, µV)
  - Accelerometer (25-200 Hz, 16-bit, mG)
  - Heart Rate (BPM + RR intervals)
  - Session markers/annotations
  - CSV output compatible with Polar Sensor Logger (Android)

Usage:
  python main.py

Requirements:
  pip install -r requirements.txt

Author: PolarRecorder
License: MIT
"""

import sys
import logging
from pathlib import Path

# ─── Logging Setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-30s │ %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

# Suppress noisy BLE debug logs
logging.getLogger("bleak").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

logger = logging.getLogger("PolarRecorder")


def main():
    """Application entry point."""
    from polar_recorder.utils.config import AppConfig
    from polar_recorder.app import run

    logger.info("=" * 60)
    logger.info("  PolarRecorder v1.0.0")
    logger.info("  Polar H10 Data Acquisition & Live Visualization")
    logger.info("=" * 60)

    config = AppConfig()
    config.ensure_dirs()

    logger.info(f"Data output directory: {config.recording.output_dir}")
    logger.info(f"ECG: {config.streams.ecg.sample_rate}Hz, {config.streams.ecg.resolution}-bit")
    logger.info(f"ACC: {config.streams.acc.sample_rate}Hz, ±{config.streams.acc.range_g}G")

    try:
        sys.exit(run(config))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
