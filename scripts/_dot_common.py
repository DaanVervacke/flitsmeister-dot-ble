"""Shared helpers for the DOT developer scripts."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self, TextIO
from urllib.parse import urlsplit

import habluetooth
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak_esphome import APIConnectionManager, ESPHomeDeviceConfig
from flitsmeister_dot_ble import (
    BleTransport,
    DisconnectedCallback,
    NotificationCallback,
    is_dot_advertisement,
)
from flitsmeister_dot_ble.const import SERIAL_NUMBER_CHARACTERISTIC_UUID
from habluetooth import BluetoothScanningMode, BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)

FAKE_SERIAL = bytes.fromhex("0011223344556677")
DISCOVERY_WARMUP_SECONDS = 5.0
DISCOVERY_POLL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class Sighting:
    """One advertisement seen during a scan."""

    device: BLEDevice
    name: str | None
    rssi: int | None
    service_uuids: tuple[str, ...]

    @property
    def is_dot(self) -> bool:
        """Whether the advertisement looks like a DOT."""
        return is_dot_advertisement(self.name, self.service_uuids)


def redact_payload(characteristic: str, payload: bytes) -> bytes:
    """Replace a serial number with a fixed fake value.

    Other characteristics are returned unchanged.
    """
    if characteristic.lower() != SERIAL_NUMBER_CHARACTERISTIC_UUID:
        return payload
    return (FAKE_SERIAL * (len(payload) // len(FAKE_SERIAL) + 1))[: len(payload)]


class CaptureWriter:
    """Write newline-delimited JSON traffic records."""

    def __init__(self, path: Path | None) -> None:
        """Open ``path`` for appending, or capture nothing when None."""
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8")
        self._start = time.monotonic()

    def __enter__(self) -> Self:
        """Return the writer itself."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the capture file."""
        self.close()

    def write(self, direction: str, characteristic: str, payload: bytes) -> None:
        """Log and store one redacted payload."""
        redacted = redact_payload(characteristic, payload)
        record = {
            "t": round(time.monotonic() - self._start, 3),
            "dir": direction,
            "chr": characteristic,
            "hex": redacted.hex(),
        }
        _LOGGER.info("%s %s %s", direction, characteristic, record["hex"])
        if self._file is not None:
            self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
            self._file.flush()

    def close(self) -> None:
        """Close the capture file. Does nothing when no path was given."""
        if self._file is not None:
            self._file.close()
            self._file = None


class CaptureTransport(BleTransport):
    """Capture transport traffic while delegating to a BLE transport."""

    def __init__(self, transport: BleTransport, capture: CaptureWriter) -> None:
        """Wrap ``transport`` and record every payload in ``capture``."""
        self._transport = transport
        self._capture = capture

    async def connect(self, disconnected_callback: DisconnectedCallback) -> None:
        """Connect the wrapped transport."""
        await self._transport.connect(disconnected_callback)

    async def disconnect(self) -> None:
        """Disconnect the wrapped transport."""
        await self._transport.disconnect()

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None:
        """Subscribe and record every notification."""

        def on_notification(received: str, payload: bytes) -> Awaitable[None] | None:
            self._capture.write("rx", received, payload)
            return callback(received, payload)

        await self._transport.start_notify(characteristic, on_notification)

    async def stop_notify(self, characteristic: str) -> None:
        """Unsubscribe on the wrapped transport."""
        await self._transport.stop_notify(characteristic)

    async def read_gatt_char(self, characteristic: str) -> bytes:
        """Record and forward one read."""
        payload = await self._transport.read_gatt_char(characteristic)
        self._capture.write("read", characteristic, payload)
        return payload

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        """Record and forward one write."""
        self._capture.write("tx", characteristic, data)
        await self._transport.write_gatt_char(characteristic, data, response=response)


class DiscoveryBluetoothManager(habluetooth.BluetoothManager):
    """Bluetooth manager that keeps scanner-owned advertisement data."""

    def _discover_service_info(self, service_info: BluetoothServiceInfoBleak) -> None:
        """Skip the callback dispatch because the scripts read the scanners directly."""


def proxy_host(value: str) -> str:
    """Return the host portion accepted by bleak-esphome."""
    parsed = urlsplit(value if "://" in value else f"//{value}")
    return parsed.hostname or value.removeprefix("//")


Scanner = Callable[[float], Awaitable[list[Sighting]]]
"""Coroutine function that scans for at least the given seconds."""

SCAN_WINDOW_SECONDS = 8.0
CONNECT_ATTEMPTS = 3


async def scan_local(seconds: float) -> list[Sighting]:
    """Scan with the local Bluetooth adapter."""
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    return [
        Sighting(
            device,
            advertisement.local_name or device.name,
            advertisement.rssi,
            tuple(advertisement.service_uuids),
        )
        for device, advertisement in found.values()
    ]


def _proxy_scanner(manager: habluetooth.BluetoothManager) -> Scanner:
    async def scan(seconds: float) -> list[Sighting]:
        await asyncio.sleep(min(seconds, DISCOVERY_WARMUP_SECONDS))
        seen: dict[str, Sighting] = {}
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            for scanner in manager.async_current_scanners():
                discovered = scanner.discovered_devices_and_advertisement_data
                for device, advertisement in discovered.values():
                    seen[device.address] = Sighting(
                        device,
                        advertisement.local_name or device.name,
                        advertisement.rssi,
                        tuple(advertisement.service_uuids),
                    )
            if asyncio.get_running_loop().time() >= deadline:
                return list(seen.values())
            await asyncio.sleep(DISCOVERY_POLL_SECONDS)

    return scan


@asynccontextmanager
async def open_scanner(
    proxy: str | None, noise_psk: str | None
) -> AsyncIterator[Scanner]:
    """Yield a scanner for the local adapter, or for an ESPHome proxy."""
    if proxy is None:
        yield scan_local
        return
    manager = APIConnectionManager(
        ESPHomeDeviceConfig(address=proxy_host(proxy), noise_psk=noise_psk)
    )
    bluetooth_manager = DiscoveryBluetoothManager()
    try:
        await bluetooth_manager.async_setup()
        await manager.start()
        for scanner in bluetooth_manager.async_current_scanners():
            if getattr(scanner, "connectable", False):
                scanner.set_requested_mode(BluetoothScanningMode.ACTIVE)
        yield _proxy_scanner(bluetooth_manager)
    finally:
        try:
            await manager.stop()
        except Exception:
            _LOGGER.debug("Stopping the ESPHome connection failed", exc_info=True)
        try:
            bluetooth_manager.async_stop()
        except Exception:
            _LOGGER.debug("Stopping the Bluetooth manager failed", exc_info=True)


@asynccontextmanager
async def background_scanner(enabled: bool) -> AsyncIterator[None]:
    """Keep a local scanner running, so BlueZ does not forget the device.

    The DOT advertises in short bursts. A running scanner re-adds it to
    BlueZ on every burst, which keeps the connect attempts of
    bleak-retry-connector working. Disabled for proxy connections.
    """
    if not enabled:
        yield
        return
    scanner = BleakScanner()
    await scanner.start()
    try:
        yield
    finally:
        try:
            await scanner.stop()
        except Exception:
            _LOGGER.debug("Stopping the background scanner failed", exc_info=True)


async def find_dot(scan: Scanner, address: str | None, seconds: float) -> BLEDevice:
    """Return the device with ``address``, or the first DOT seen.

    With ``address`` set, any device with that address matches, DOT or
    not. Without it, only a DOT advertisement matches. The scan repeats
    in windows until the deadline, so a device that advertises in
    bursts is still found.

    Raises:
        TimeoutError: No matching device was seen before the deadline.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        sightings = await scan(min(remaining, SCAN_WINDOW_SECONDS))
        for sighting in sightings:
            if address is not None:
                if sighting.device.address.upper() == address.upper():
                    return sighting.device
            elif sighting.is_dot:
                return sighting.device
    raise TimeoutError("Flitsmeister DOT was not found")
