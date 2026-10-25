"""Polar device connection and stream management.

Wraps polar-python's PolarDevice to provide a thread-safe interface
that bridges async BLE operations with the Qt UI via signals.

NOTE: We bypass PolarDevice's constructor to inject a BleakClient
with a proper timeout, because polar-python creates BleakClient
without one and connect() hangs forever on Linux/BlueZ.

We also start/stop PMD streams and parse heart rate ourselves:
polar-python waits forever for the strap's response to a start request,
ignores the error code in it, and its HR parser ignores the flags byte.
"""

import asyncio
import copy
import logging
import struct
import sys
from datetime import datetime
from typing import Optional, Callable, List, Tuple

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from polar_python import PolarDevice
from polar_python.constants import (
    PmdControlOperationCode,
    PmdControlPointErrorCode,
    PmdMeasurementType,
    PmdSettingType,
    PolarCharacteristic,
)
from polar_python.models import ECGData, ACCData, MeasurementSettings

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
# Max wait for the strap to answer a stream start/stop request
STREAM_START_TIMEOUT = 10
STREAM_STOP_TIMEOUT = 3
DISCONNECT_TIMEOUT = 5

BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

IS_MACOS = sys.platform == "darwin"

# CoreBluetooth reports this when the OS still holds a bond the strap has
# already dropped (the H10 only stores a handful of bonded devices). macOS has
# no unpair API, so the stale bond can only be cleared at the OS level or by
# resetting the strap.
_PEER_REMOVED_PAIRING_HINT = (
    "macOS has a stale Bluetooth pairing for this strap "
    "(CoreBluetooth error 14: 'Peer removed pairing information'). "
    "To fix: open System Settings → Bluetooth, click (i) next to the Polar H10 "
    "and choose 'Forget This Device'; also toggle Bluetooth off/on "
    "(Shift+Option-click the menu bar Bluetooth icon → 'Reset the Bluetooth module'). "
    "Then remove the H10 battery for ~10s and reinsert it to clear the strap's own "
    "stored pairing, and connect again."
)


def parse_hr_measurement(data: bytearray) -> Tuple[int, List[float], Optional[bool]]:
    """Parse a Bluetooth Heart Rate Measurement (0x2A37) notification.

    Returns:
        (heart rate in BPM, RR intervals in ms, sensor contact or None if not reported)
    """
    flags = data[0]
    if flags & 0x01:  # 16-bit heart rate value
        hr = int.from_bytes(data[1:3], "little")
        offset = 3
    else:
        hr = data[1]
        offset = 2

    # Bit 2 says whether contact detection is supported, bit 1 is the status
    contact = bool(flags & 0x02) if flags & 0x04 else None

    if flags & 0x08:  # Energy expended field present
        offset += 2

    rr_intervals = []
    if flags & 0x10:  # RR intervals present, in 1/1024 s
        rr_intervals = [
            int.from_bytes(data[i:i + 2], "little") * 1000.0 / 1024.0
            for i in range(offset, len(data) - 1, 2)
        ]
    return hr, rr_intervals, contact


def _describe_error(e: Exception) -> str:
    if isinstance(e, asyncio.TimeoutError):
        return "no response from the strap"
    return str(e) or type(e).__name__


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
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connecting = False
        self._connected = False
        self._streaming = False
        self._battery_level: Optional[int] = None

        # What is actually running on the strap (may differ from what was requested)
        self._active_config: Optional[StreamConfig] = None
        self._running_pmd: List[PmdMeasurementType] = []
        self._hr_notifying = False

        # Data callbacks — set by the UI/recording layer
        self._ecg_callback: Optional[Callable[[ECGSample], None]] = None
        self._acc_callback: Optional[Callable[[ACCSample], None]] = None
        self._hr_callback: Optional[Callable[[HRSample], None]] = None

        # Connection state callbacks
        self._on_connected: Optional[Callable[[], None]] = None
        self._on_disconnected: Optional[Callable[[bool], None]] = None  # arg: unexpected
        self._on_error: Optional[Callable[[str], None]] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def is_busy(self) -> bool:
        """True while connecting or connected."""
        return self._connecting or self._connected

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def device_info(self) -> Optional[DeviceInfo]:
        return self._device_info

    @property
    def battery_level(self) -> Optional[int]:
        return self._battery_level

    @property
    def active_stream_config(self) -> Optional[StreamConfig]:
        """Configuration of the streams that actually started on the strap."""
        return self._active_config

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
        on_disconnected: Optional[Callable[[bool], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Set callbacks for connection state changes.

        on_disconnected receives True when the link dropped unexpectedly
        (out of range, strap removed), False for a user-initiated disconnect.
        """
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
        if self.is_busy:
            logger.warning("Connect ignored: already connected or connecting")
            return False

        self._connecting = True
        self._loop = asyncio.get_running_loop()
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
                disconnected_callback=self._on_link_lost,
                timeout=CONNECT_TIMEOUT,
            )

            # Step 2: Connect with a hard timeout wrapper
            logger.info("Connecting BleakClient...")
            await asyncio.wait_for(
                self._client.connect(),
                timeout=CONNECT_TIMEOUT,
            )
            logger.info(f"BleakClient connected: {self._client.is_connected}")

            # Step 3: Pair device. On Linux/BlueZ an explicit pair() is required
            # so the PMD indicate characteristics can be subscribed. macOS
            # CoreBluetooth has no explicit pairing API: it auto-pairs when an
            # encrypted characteristic is accessed, and bleak's pair() raises
            # NotImplementedError there, so skip it.
            if IS_MACOS:
                logger.info("Skipping explicit pair on macOS (CoreBluetooth auto-pairs)")
            else:
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
                    self._handle_pmd_data,
                ),
                timeout=10,
            )

            # Step 6: Battery level (optional, informational)
            try:
                raw = await asyncio.wait_for(
                    self._client.read_gatt_char(BATTERY_LEVEL_UUID), timeout=5
                )
                self._battery_level = int(raw[0])
                logger.info(f"  ✓ Battery level: {self._battery_level}%")
            except Exception as e:
                logger.info(f"  Battery level unavailable: {_describe_error(e)}")

            self._connecting = False
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
            if "Peer removed pairing information" in str(e) or "Code=14" in str(e):
                error_msg = _PEER_REMOVED_PAIRING_HINT
            else:
                error_msg = f"Connection failed: {e}"
            logger.error(error_msg)
            await self._cleanup_failed_connection()
            if self._on_error:
                self._on_error(error_msg)
            return False

        finally:
            self._connecting = False

    async def _cleanup_failed_connection(self):
        """Clean up after a failed connection attempt."""
        self._connected = False
        if self._client and self._client.is_connected:
            try:
                await asyncio.wait_for(self._client.disconnect(), DISCONNECT_TIMEOUT)
            except Exception:
                pass
        self._reset_state()

    def _reset_state(self) -> None:
        self._device = None
        self._client = None
        self._ble_device = None
        self._connected = False
        self._streaming = False
        self._battery_level = None
        self._active_config = None
        self._running_pmd = []
        self._hr_notifying = False

    def _on_link_lost(self, client: BleakClient) -> None:
        """Bleak disconnect callback. May run off the event loop thread on some backends."""
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._handle_link_lost, client)

    def _handle_link_lost(self, client: BleakClient) -> None:
        # Ignore disconnects we initiated, and late callbacks from an old client
        if client is not self._client or not self._connected:
            return
        logger.warning("Connection to the strap was lost")
        self._reset_state()
        if self._on_disconnected:
            self._on_disconnected(True)

    async def disconnect(self) -> None:
        """Disconnect from the current device (or abort a connect in progress)."""
        client = self._client
        if client is None:
            return

        if self._connecting:
            # connect() fails on its next await and cleans up after itself
            try:
                await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT)
            except Exception:
                pass
            return

        was_connected = self._connected
        # From here on the bleak disconnect callback is ignored (see _handle_link_lost)
        self._connected = False
        try:
            if client.is_connected:
                await self.stop_streams()
                await asyncio.wait_for(client.disconnect(), DISCONNECT_TIMEOUT)
        except Exception as e:
            logger.warning(f"Error during disconnect: {_describe_error(e)}")
        finally:
            self._reset_state()
            logger.info("Disconnected from device")
            if was_connected and self._on_disconnected:
                self._on_disconnected(False)

    async def start_streams(self, config: StreamConfig) -> List[str]:
        """Start configured data streams.

        Each stream is started independently, so one failing doesn't take the
        others down. `active_stream_config` afterwards reflects what is running.

        Args:
            config: StreamConfig specifying which streams and their parameters.

        Returns:
            One error message per stream that failed to start (empty on success).
        """
        if not self._device or not self._client:
            raise RuntimeError("Not connected to a device")

        logger.info("Starting data streams...")
        active = copy.deepcopy(config)
        errors: List[str] = []

        if config.hr.enabled:
            try:
                await asyncio.wait_for(
                    self._client.start_notify(
                        PolarCharacteristic.HEART_RATE.value,
                        self._handle_hr_notification,
                    ),
                    timeout=STREAM_START_TIMEOUT,
                )
                self._hr_notifying = True
                logger.info("  ✓ HR stream started")
            except Exception as e:
                active.hr.enabled = False
                errors.append(f"HR: {_describe_error(e)}")

        if config.ecg.enabled:
            self._device._ecg_callback = self._handle_ecg_data
            try:
                await self._start_pmd_stream(MeasurementSettings(
                    measurement_type=PmdMeasurementType.ECG,
                    settings=[
                        MeasurementSettings.SettingType(PmdSettingType.SAMPLE_RATE, [config.ecg.sample_rate]),
                        MeasurementSettings.SettingType(PmdSettingType.RESOLUTION, [config.ecg.resolution]),
                    ],
                ))
                logger.info(
                    f"  ✓ ECG stream started "
                    f"({config.ecg.sample_rate}Hz, {config.ecg.resolution}-bit)"
                )
            except Exception as e:
                self._device._ecg_callback = None
                active.ecg.enabled = False
                errors.append(f"ECG: {_describe_error(e)}")

        if config.acc.enabled:
            self._device._acc_callback = self._handle_acc_data
            try:
                await self._start_pmd_stream(MeasurementSettings(
                    measurement_type=PmdMeasurementType.ACC,
                    settings=[
                        MeasurementSettings.SettingType(PmdSettingType.SAMPLE_RATE, [config.acc.sample_rate]),
                        MeasurementSettings.SettingType(PmdSettingType.RESOLUTION, [config.acc.resolution]),
                        MeasurementSettings.SettingType(PmdSettingType.RANGE, [config.acc.range_g]),
                    ],
                ))
                logger.info(
                    f"  ✓ ACC stream started "
                    f"({config.acc.sample_rate}Hz, ±{config.acc.range_g}G)"
                )
            except Exception as e:
                self._device._acc_callback = None
                active.acc.enabled = False
                errors.append(f"ACC: {_describe_error(e)}")

        for msg in errors:
            logger.error(f"  ✗ Failed to start {msg}")

        self._active_config = active
        self._streaming = active.hr.enabled or active.ecg.enabled or active.acc.enabled
        if self._streaming:
            logger.info("Configured streams are active.")
        return errors

    async def _start_pmd_stream(self, settings: MeasurementSettings) -> None:
        """Start a PMD stream and check the strap's response.

        If the strap reports the stream as already running (e.g. left over from a
        previous run that didn't stop it), it is restarted so the requested
        settings apply.
        """
        pmd_cp = PolarCharacteristic.PMD_CONTROL_POINT.value
        queue = self._device._queue_pmd_control

        for attempt in range(2):
            # Drop stale responses, e.g. from an earlier timed-out request
            while not queue.empty():
                queue.get_nowait()

            await asyncio.wait_for(
                self._client.write_gatt_char(pmd_cp, settings.to_bytes()),
                timeout=STREAM_START_TIMEOUT,
            )
            raw = await asyncio.wait_for(queue.get(), timeout=STREAM_START_TIMEOUT)
            response = MeasurementSettings.from_bytes(raw)

            if response.error_code == PmdControlPointErrorCode.ERROR_ALREADY_IN_STATE and attempt == 0:
                logger.info(f"  {settings.measurement_type.name} already running, restarting it")
                await self._stop_pmd_stream(settings.measurement_type)
                continue
            if response.error_code not in (
                PmdControlPointErrorCode.SUCCESS,
                PmdControlPointErrorCode.ERROR_ALREADY_IN_STATE,
            ):
                raise RuntimeError(f"strap rejected the request ({response.error_code.name})")
            break

        for setting in response.settings:
            if setting.type == PmdSettingType.FACTOR and setting.values:
                raw_int_factor = setting.values[0]
                self._device._factors[settings.measurement_type] = struct.unpack(
                    "<f", struct.pack("<I", raw_int_factor)
                )[0]
                break

        self._running_pmd.append(settings.measurement_type)

    async def _stop_pmd_stream(self, measurement_type: PmdMeasurementType) -> None:
        await asyncio.wait_for(
            self._client.write_gatt_char(
                PolarCharacteristic.PMD_CONTROL_POINT.value,
                bytearray([PmdControlOperationCode.STOP, measurement_type.value]),
            ),
            timeout=STREAM_STOP_TIMEOUT,
        )
        if self._device:
            self._device._factors.pop(measurement_type, None)

    async def stop_streams(self) -> None:
        """Stop all active data streams on the strap."""
        if self._client and self._client.is_connected:
            for measurement_type in self._running_pmd:
                try:
                    await self._stop_pmd_stream(measurement_type)
                except Exception as e:
                    logger.warning(f"Could not stop {measurement_type.name} stream: {_describe_error(e)}")
            if self._hr_notifying:
                try:
                    await asyncio.wait_for(
                        self._client.stop_notify(PolarCharacteristic.HEART_RATE.value),
                        timeout=STREAM_STOP_TIMEOUT,
                    )
                except Exception as e:
                    logger.warning(f"Could not stop HR stream: {_describe_error(e)}")

        if self._device:
            self._device._ecg_callback = None
            self._device._acc_callback = None
        self._running_pmd = []
        self._hr_notifying = False
        self._streaming = False
        logger.info("Streams stopped.")

    # ─── Internal Data Handlers ─────────────────────────────────────────────

    def _handle_pmd_data(self, sender, data: bytearray) -> None:
        """Let polar-python parse PMD frames, without letting a bad frame raise into bleak."""
        try:
            self._device._handle_pmd_data(sender, data)
        except Exception:
            logger.exception("Failed to handle PMD data frame")

    def _dispatch(self, callback: Optional[Callable], sample) -> None:
        if callback is None:
            return
        try:
            callback(sample)
        except Exception:
            logger.exception("Error while handling incoming data")

    def _handle_ecg_data(self, data: ECGData) -> None:
        """Convert polar-python ECGData to our ECGSample model."""
        sample = ECGSample(
            phone_timestamp=datetime.now(),
            sensor_timestamp_ns=data.timestamp,
            samples_uv=list(data.data),
        )
        self._dispatch(self._ecg_callback, sample)

    def _handle_acc_data(self, data: ACCData) -> None:
        """Convert polar-python ACCData to our ACCSample model."""
        sample = ACCSample(
            phone_timestamp=datetime.now(),
            sensor_timestamp_ns=data.timestamp,
            samples_mg=[(x, y, z) for x, y, z in data.data],
        )
        self._dispatch(self._acc_callback, sample)

    def _handle_hr_notification(self, _sender, data: bytearray) -> None:
        """Parse a Heart Rate Measurement notification into an HRSample."""
        try:
            hr, rr_intervals, contact = parse_hr_measurement(data)
        except IndexError:
            logger.warning(f"Malformed heart rate packet: {bytes(data).hex()}")
            return
        sample = HRSample(
            phone_timestamp=datetime.now(),
            heart_rate_bpm=hr,
            rr_intervals_ms=rr_intervals,
            sensor_contact=contact,
        )
        self._dispatch(self._hr_callback, sample)
