"""Polar device connection and stream management.

Wraps polar-python's PolarDevice to provide a thread-safe interface
that bridges async BLE operations with the Qt UI via signals.

NOTE: We bypass PolarDevice's constructor to inject a BleakClient
with a proper timeout, because polar-python creates BleakClient
without one and connect() hangs forever on Linux/BlueZ.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Callable, List

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from polar_python import PolarDevice
from polar_python.constants import PolarCharacteristic
from polar_python.models import ECGData, ACCData, HRData

from polar_recorder.ble.data_models import (
    ECGSample,
    ACCSample,
    HRSample,
    DeviceInfo,
)
from polar_recorder.utils.config import StreamConfig

logger = logging.getLogger(__name__)

# Connection timeout in seconds
CONNECT_TIMEOUT = 15


class PolarDeviceManager:
    """Manages the lifecycle of a Polar H10 BLE connection.

    Handles connection, stream start/stop, and data callback routing.
    Designed to be driven by asyncio within the Qt event loop via qasync.
    """

    def __init__(self):
        self._device: Optional[PolarDevice] = None
        self._client: Optional[BleakClient] = None
        self._ble_device: Optional[BLEDevice] = None
        self._device_info: Optional[DeviceInfo] = None
        self._connected = False
        self._streaming = False

        # Data callbacks — set by the UI/recording layer
        self._ecg_callback: Optional[Callable[[ECGSample], None]] = None
        self._acc_callback: Optional[Callable[[ACCSample], None]] = None
        self._hr_callback: Optional[Callable[[HRSample], None]] = None

        # Connection state callbacks
        self._on_connected: Optional[Callable[[], None]] = None
        self._on_disconnected: Optional[Callable[[], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        return self._device_info

    def set_data_callbacks(
        self,
        ecg_callback: Optional[Callable[[ECGSample], None]] = None,
        acc_callback: Optional[Callable[[ACCSample], None]] = None,
        hr_callback: Optional[Callable[[HRSample], None]] = None,
    ) -> None:
        """Set callbacks for incoming data streams."""
        self._ecg_callback = ecg_callback
        self._acc_callback = acc_callback
        self._hr_callback = hr_callback

    def set_connection_callbacks(
        self,
        on_connected: Optional[Callable[[], None]] = None,
        on_disconnected: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Set callbacks for connection state changes."""
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._on_error = on_error

    async def connect(self, device_info: DeviceInfo) -> bool:
        """Connect to a discovered Polar device.

        Bypasses polar-python's broken no-timeout connection by creating
        our own BleakClient with a timeout and injecting it.

        Args:
            device_info: The DeviceInfo from the scanner (carries raw BLEDevice).

        Returns:
            True if connection succeeded.
        """
        self._device_info = device_info
        logger.info(f"Connecting to {device_info.name} ({device_info.address})...")

        try:
            # Get the BLE device reference
            if device_info.ble_device is not None:
                self._ble_device = device_info.ble_device
                logger.info("Using cached BLEDevice from scan")
            else:
                logger.warning("No cached BLEDevice, using address string")
                self._ble_device = device_info.address

            # Step 1: Create BleakClient WITH timeout (polar-python doesn't do this)
            logger.info(f"Creating BleakClient (timeout={CONNECT_TIMEOUT}s)...")
            self._client = BleakClient(
                self._ble_device,
                timeout=CONNECT_TIMEOUT,
            )

            # Step 2: Connect with a hard timeout wrapper
            logger.info("Connecting BleakClient...")
            await asyncio.wait_for(
                self._client.connect(),
                timeout=CONNECT_TIMEOUT,
            )
            logger.info(f"BleakClient connected: {self._client.is_connected}")

            # Step 3: Pair device (required on Linux/BlueZ for PMD indicate chars)
            logger.info("Pairing device (required for PMD on Linux)...")
            try:
                await asyncio.wait_for(self._client.pair(), timeout=10)
                logger.info("  ✓ Device paired")
            except asyncio.TimeoutError:
                logger.warning("  ⚠ Pair timed out (may already be paired)")
            except Exception as e:
                logger.warning(f"  ⚠ Pair skipped: {e}")

            # Step 4: Create PolarDevice and inject our connected client
            # We bypass PolarDevice.__init__ which creates its own client
            self._device = PolarDevice.__new__(PolarDevice)
            self._device._client = self._client
            self._device._queue_pmd_control = asyncio.Queue()
            self._device._factors = {}

            # Step 5: Start PMD notifications with timeouts
            pmd_cp = PolarCharacteristic.PMD_CONTROL_POINT.value
            pmd_data = PolarCharacteristic.PMD_DATA.value
            logger.info(f"Subscribing to PMD Control ({pmd_cp[-8:]})...")
            await asyncio.wait_for(
                self._client.start_notify(
                    pmd_cp,
                    self._device._handle_pmd_control,
                ),
                timeout=10,
            )
            logger.info("  ✓ PMD Control subscribed")

            logger.info(f"Subscribing to PMD Data ({pmd_data[-8:]})...")
            await asyncio.wait_for(
                self._client.start_notify(
                    pmd_data,
                    self._device._handle_pmd_data,
                ),
                timeout=10,
            )

            self._connected = True
            logger.info(f"✓ Connected to {device_info.name}")
            if self._on_connected:
                self._on_connected()

            return True

        except asyncio.TimeoutError:
            error_msg = (
                f"Connection timed out after {CONNECT_TIMEOUT}s. "
                "Make sure the H10 strap is worn (needs skin contact to stay active)."
            )
            logger.error(error_msg)
            await self._cleanup_failed_connection()
            if self._on_error:
                self._on_error(error_msg)
            return False

        except Exception as e:
            error_msg = f"Connection failed: {e}"
            logger.error(error_msg)
            await self._cleanup_failed_connection()
            if self._on_error:
                self._on_error(error_msg)
            return False

    async def _cleanup_failed_connection(self):
        """Clean up after a failed connection attempt."""
        self._connected = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._device = None

    async def disconnect(self) -> None:
        """Disconnect from the current device."""
        try:
            if self._streaming:
                await self.stop_streams()
            if self._client and self._client.is_connected:
                await self._client.disconnect()
        except Exception as e:
            logger.warning(f"Error during disconnect: {e}")
        finally:
            self._device = None
            self._client = None
            self._ble_device = None
            self._connected = False
            self._streaming = False
            logger.info("Disconnected from device")
            if self._on_disconnected:
                self._on_disconnected()

    async def start_streams(self, config: StreamConfig) -> None:
        """Start configured data streams.

        Args:
            config: StreamConfig specifying which streams and their parameters.
        """
        if not self._device or not self._connected:
            raise RuntimeError("Not connected to a device")

        logger.info("Starting data streams...")

        try:
            if config.hr.enabled:
                await self._device.start_hr_stream(
                    hr_callback=self._handle_hr_data
                )
                logger.info("  ✓ HR stream started")

            if config.ecg.enabled:
                await self._device.start_ecg_stream(
                    ecg_callback=self._handle_ecg_data,
                    sample_rate=config.ecg.sample_rate,
                    resolution=config.ecg.resolution,
                )
                logger.info(
                    f"  ✓ ECG stream started "
                    f"({config.ecg.sample_rate}Hz, {config.ecg.resolution}-bit)"
                )

            if config.acc.enabled:
                await self._device.start_acc_stream(
                    acc_callback=self._handle_acc_data,
                    sample_rate=config.acc.sample_rate,
                    resolution=config.acc.resolution,
                    range=config.acc.range_g,
                )
                logger.info(
                    f"  ✓ ACC stream started "
                    f"({config.acc.sample_rate}Hz, ±{config.acc.range_g}G)"
                )

            self._streaming = True
            logger.info("All configured streams are active.")

        except Exception as e:
            error_msg = f"Failed to start streams: {e}"
            logger.error(error_msg)
            if self._on_error:
                self._on_error(error_msg)
            raise

    async def stop_streams(self) -> None:
        """Stop all active data streams."""
        self._streaming = False
        logger.info("Streams stopped.")

    # ─── Internal Data Handlers ─────────────────────────────────────────────

    def _handle_ecg_data(self, data: ECGData) -> None:
        """Convert polar-python ECGData to our ECGSample model."""
        now = datetime.now()
        sample = ECGSample(
            phone_timestamp=now,
            sensor_timestamp_ns=data.timestamp,
            samples_uv=list(data.data),
        )
        if self._ecg_callback:
            self._ecg_callback(sample)

    def _handle_acc_data(self, data: ACCData) -> None:
        """Convert polar-python ACCData to our ACCSample model."""
        now = datetime.now()
        sample = ACCSample(
            phone_timestamp=now,
            sensor_timestamp_ns=data.timestamp,
            samples_mg=[(x, y, z) for x, y, z in data.data],
        )
        if self._acc_callback:
            self._acc_callback(sample)

    def _handle_hr_data(self, data: HRData) -> None:
        """Convert polar-python HRData to our HRSample model."""
        now = datetime.now()
        rr_intervals = list(data.rr_intervals) if data.rr_intervals else []
        sample = HRSample(
            phone_timestamp=now,
            heart_rate_bpm=data.heartrate,
            rr_intervals_ms=rr_intervals,
        )
        if self._hr_callback:
            self._hr_callback(sample)

