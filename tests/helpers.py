"""Payloads, fakes and wait helpers for the DOT test suite."""

import asyncio
from typing import Any

from flitsmeister_dot_ble import (
    ConnectionLostCallback,
    DisconnectedCallback,
    FlitsmeisterDotClient,
    NotificationCallback,
    UpdateCallback,
)
from flitsmeister_dot_ble.const import (
    BATTERY_CHARGING_CHARACTERISTIC_UUID,
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    BRIGHTNESS_CHARACTERISTIC_UUID,
    FIRMWARE_REVISION_CHARACTERISTIC_UUID,
    LED_ROTATION_CHARACTERISTIC_UUID,
    MANUFACTURER_NAME_CHARACTERISTIC_UUID,
    MODEL_NUMBER_CHARACTERISTIC_UUID,
    MOTION_CHARACTERISTIC_UUID,
    SERIAL_NUMBER_CHARACTERISTIC_UUID,
    SOFTWARE_REVISION_CHARACTERISTIC_UUID,
)
from flitsmeister_dot_ble.transport_types import BleTransport

WAIT_SECONDS = 2.0

DEFAULT_READS: dict[str, bytes] = {
    BATTERY_LEVEL_CHARACTERISTIC_UUID: b"\x64",
    BATTERY_CHARGING_CHARACTERISTIC_UUID: b"\x00\x00\x01",
    MOTION_CHARACTERISTIC_UUID: b"\x00",
    BRIGHTNESS_CHARACTERISTIC_UUID: b"\x64",
    LED_ROTATION_CHARACTERISTIC_UUID: b"\x00",
    MANUFACTURER_NAME_CHARACTERISTIC_UUID: b"Flitsmeister",
    MODEL_NUMBER_CHARACTERISTIC_UUID: b"DOT",
    SERIAL_NUMBER_CHARACTERISTIC_UUID: b"\x11\x22\x33",
    FIRMWARE_REVISION_CHARACTERISTIC_UUID: b"1.0.14",
    SOFTWARE_REVISION_CHARACTERISTIC_UUID: b"1.0.14",
}


class FakeTransport:
    """In-memory transport that answers every read.

    Like Bleak, ``disconnect()`` calls the disconnected callback while the
    link is up.
    """

    def __init__(self, reads: dict[str, bytes] | None = None) -> None:
        self.reads = dict(DEFAULT_READS) if reads is None else dict(reads)
        self.writes: list[bytes] = []
        self.write_characteristics: list[str] = []
        self.notify_characteristics: list[str] = []
        self.read_characteristics: list[str] = []
        self.stopped_characteristics: list[str] = []
        self.responses: list[bool] = []
        self.callbacks: dict[str, NotificationCallback] = {}
        self.disconnected_callback: DisconnectedCallback | None = None
        self.linked = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.fail_writes = False
        self.fail_connect: BaseException | None = None
        self.fail_start_notify: BaseException | None = None
        self.fail_read: BaseException | None = None
        self.fail_stop_notify: BaseException | None = None
        self.hang_reads: set[str] = set()

    async def connect(self, disconnected_callback: DisconnectedCallback) -> None:
        self.connect_calls += 1
        if self.fail_connect is not None:
            raise self.fail_connect
        self.disconnected_callback = disconnected_callback
        self.linked = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.linked:
            self.drop()

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None:
        if self.fail_start_notify is not None:
            raise self.fail_start_notify
        self.notify_characteristics.append(characteristic)
        self.callbacks[characteristic] = callback

    async def stop_notify(self, characteristic: str) -> None:
        if self.fail_stop_notify is not None:
            raise self.fail_stop_notify
        self.stopped_characteristics.append(characteristic)

    async def read_gatt_char(self, characteristic: str) -> bytes:
        if characteristic in self.hang_reads:
            await asyncio.Event().wait()
        if self.fail_read is not None:
            raise self.fail_read
        self.read_characteristics.append(characteristic)
        return self.reads[characteristic]

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        if self.fail_writes:
            raise OSError("write failed")
        self.writes.append(data)
        self.write_characteristics.append(characteristic)
        self.responses.append(response)

    def notify(self, characteristic: str, data: bytes) -> None:
        """Deliver one notification or indication payload."""
        callback = self.callbacks[characteristic]
        result = callback(characteristic, data)
        assert not isinstance(result, asyncio.Future)

    def drop(self) -> None:
        """Simulate a link loss reported by the BLE stack."""
        self.linked = False
        assert self.disconnected_callback is not None
        self.disconnected_callback()


def make_client(
    transport: BleTransport,
    *,
    response_timeout_seconds: float = 1.0,
    long_press_seconds: float = 1.0,
    update_callback: UpdateCallback | None = None,
    connection_lost_callback: ConnectionLostCallback | None = None,
) -> FlitsmeisterDotClient:
    return FlitsmeisterDotClient(
        transport,
        response_timeout_seconds=response_timeout_seconds,
        long_press_seconds=long_press_seconds,
        update_callback=update_callback,
        connection_lost_callback=connection_lost_callback,
    )


async def drain(client: FlitsmeisterDotClient) -> None:
    """Wait until the client processed every queued notification."""
    async with asyncio.timeout(WAIT_SECONDS):
        await client._notifications.join()


async def wait_for(event: asyncio.Event) -> None:
    async with asyncio.timeout(WAIT_SECONDS):
        await event.wait()


def any_value(_: Any) -> None:
    """Consume an argument without asserting anything."""
