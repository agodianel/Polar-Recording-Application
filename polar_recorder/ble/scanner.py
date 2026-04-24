"""BLE device scanner for discovering Polar devices."""

import asyncio
import logging
from typing import List, Optional, Callable

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from polar_recorder.ble.data_models import DeviceInfo
from polar_recorder.utils.config import POLAR_DEVICE_PREFIX, SCAN_TIMEOUT_SEC

logger = logging.getLogger(__name__)


class PolarScanner:
    """Asynchronous BLE scanner for Polar devices.

    Emits discovered devices via a callback as they are found,
    and returns the full list when scanning completes.
    """

    def __init__(self, timeout: float = SCAN_TIMEOUT_SEC):
        self.timeout = timeout
        self._discovered: dict[str, DeviceInfo] = {}
        self._on_device_found: Optional[Callable[[DeviceInfo], None]] = None
        self._scanning = False

    @property
    def is_scanning(self) -> bool:
        return self._scanning

    def set_callback(self, callback: Callable[[DeviceInfo], None]) -> None:
        """Set callback invoked when a new Polar device is discovered."""
        self._on_device_found = callback

    async def scan(self) -> List[DeviceInfo]:
        """Scan for nearby Polar devices.

        Returns:
            List of discovered DeviceInfo objects.
        """
        self._discovered.clear()
        self._scanning = True

        logger.info(f"Starting BLE scan (timeout={self.timeout}s)...")

        try:
            scanner = BleakScanner(detection_callback=self._detection_callback)
            await scanner.start()
            await asyncio.sleep(self.timeout)
            await scanner.stop()
        except Exception as e:
            logger.error(f"BLE scan failed: {e}")
            raise
        finally:
            self._scanning = False

        devices = list(self._discovered.values())
        logger.info(f"Scan complete. Found {len(devices)} Polar device(s).")
        return devices

    def _detection_callback(
        self, device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Internal callback for BleakScanner detection events."""
        if device.name and device.name.startswith(POLAR_DEVICE_PREFIX):
            if device.address not in self._discovered:
                info = DeviceInfo(
                    name=device.name,
                    address=device.address,
                    rssi=advertisement_data.rssi,
                    ble_device=device,  # Store raw BLEDevice for direct connection
                )
                self._discovered[device.address] = info
                logger.info(f"Discovered: {info}")

                if self._on_device_found:
                    self._on_device_found(info)

    async def find_device(self, name_filter: str = "Polar H10") -> Optional[DeviceInfo]:
        """Find a specific Polar device by partial name match.

        Args:
            name_filter: Substring to match in device name.

        Returns:
            DeviceInfo if found, None otherwise.
        """
        devices = await self.scan()
        for dev in devices:
            if name_filter in dev.name:
                return dev
        return None
