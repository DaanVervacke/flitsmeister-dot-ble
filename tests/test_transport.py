import asyncio
import logging
from collections.abc import Callable
from typing import Any

import pytest
from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError, BleakGATTProtocolError, BleakGATTProtocolErrorCode
from bleak_retry_connector import BleakClientWithServiceCache
from flitsmeister_dot_ble import BleakTransport, DotConnectionError
from flitsmeister_dot_ble import transport as transport_module


class FakeCharacteristic:
    uuid = "27831002-33ee-9b9c-124d-109d6b0c0a91"


class FakeBleakClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.notify_callback: Callable[[Any, bytearray], None] | None = None
        self.writes: list[tuple[str, bytes, bool]] = []
        self.reads: list[str] = []
        self.read_replies: dict[str, bytes] = {}
        self.stopped: list[str] = []
        self.disconnects = 0
        self.fail_disconnect = False
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.disconnected_callback: Callable[[Any], None] | None = None
        self.fail_with: Exception | None = None

    async def start_notify(
        self, characteristic: str, callback: Callable[[Any, bytearray], None]
    ) -> None:
        self.notify_callback = callback

    async def stop_notify(self, characteristic: str) -> None:
        self.stopped.append(characteristic)

    async def read_gatt_char(self, characteristic: str) -> bytearray:
        if self.fail_with is not None:
            raise self.fail_with
        self.reads.append(characteristic)
        return bytearray(self.read_replies[characteristic])

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.writes.append((characteristic, data, response))

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.is_connected = False
        if self.fail_disconnect:
            raise OSError("disconnect failed")

    def notify(self, data: bytes) -> None:
        assert self.notify_callback is not None
        self.notify_callback(FakeCharacteristic(), bytearray(data))

    def drop(self) -> None:
        assert self.disconnected_callback is not None
        self.disconnected_callback(self)


@pytest.fixture
def device() -> BLEDevice:
    return BLEDevice("AA:BB:CC:DD:EE:FF", "FM DOT", None)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeBleakClient:
    client = FakeBleakClient()

    async def establish(*args: Any, **kwargs: Any) -> FakeBleakClient:
        client.calls.append((args, kwargs))
        client.disconnected_callback = kwargs["disconnected_callback"]
        client.is_connected = True
        return client

    monkeypatch.setattr(transport_module, "establish_connection", establish)
    return client


async def test_client_needs_connection(device: BLEDevice) -> None:
    transport = BleakTransport(device)
    with pytest.raises(DotConnectionError, match="not connected"):
        _ = transport.client
    with pytest.raises(DotConnectionError, match="not connected"):
        await transport.write_gatt_char("w", b"\x01")
    with pytest.raises(DotConnectionError, match="not connected"):
        await transport.read_gatt_char("r")


async def test_connect_passes_options(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    def lookup() -> BLEDevice:
        return device

    transport = BleakTransport(device, timeout=12.0, ble_device_callback=lookup)
    await transport.connect(lambda: None)
    args, kwargs = fake_client.calls[0]
    assert args == (BleakClientWithServiceCache, device, "FM DOT")
    assert kwargs["timeout"] == 12.0
    assert kwargs["ble_device_callback"] is lookup
    assert callable(kwargs["disconnected_callback"])


async def test_client_factory_overrides_class(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device, client_factory=BleakClient)
    await transport.connect(lambda: None)
    args, _kwargs = fake_client.calls[0]
    assert args[0] is BleakClient
    assert args[0] is not BleakClientWithServiceCache


async def test_connect_uses_address_without_name(
    fake_client: FakeBleakClient,
) -> None:
    device = BLEDevice("AA:BB:CC:DD:EE:FF", None, None)
    await BleakTransport(device).connect(lambda: None)
    args, _kwargs = fake_client.calls[0]
    assert args[2] == "AA:BB:CC:DD:EE:FF"


async def test_connect_reuses_live_client(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    first: list[bool] = []
    second: list[bool] = []
    await transport.connect(lambda: first.append(True))
    await transport.connect(lambda: second.append(True))
    assert len(fake_client.calls) == 1
    current: object = transport.client
    assert current is fake_client
    fake_client.drop()
    assert first == []
    assert second == [True]


async def test_connect_again_when_link_is_down(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.is_connected = False
    await transport.connect(lambda: None)
    assert len(fake_client.calls) == 2


async def test_write_read_stop_notify_and_disconnect(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.read_replies["r"] = b"\x01"
    assert await transport.read_gatt_char("r") == bytearray(b"\x01")
    await transport.write_gatt_char("w", b"\x01", response=True)
    assert fake_client.writes == [("w", b"\x01", True)]
    await transport.stop_notify("n")
    assert fake_client.stopped == ["n"]
    await transport.disconnect()
    assert fake_client.disconnects == 1
    await transport.stop_notify("n")
    assert fake_client.stopped == ["n"]
    await transport.disconnect()
    assert fake_client.disconnects == 1


async def test_stop_notify_after_link_drop_does_nothing(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.is_connected = False
    await transport.stop_notify("n")
    assert fake_client.stopped == []


async def test_disconnect_error_still_resets_client(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.fail_disconnect = True
    with pytest.raises(OSError, match="disconnect failed"):
        await transport.disconnect()
    with pytest.raises(DotConnectionError):
        _ = transport.client


async def test_sync_notification_callback(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    received: list[tuple[str, bytes]] = []

    def on_data(uuid: str, data: bytes) -> None:
        received.append((uuid, data))

    await transport.start_notify("n", on_data)
    fake_client.notify(b"\x01")
    assert received == [(FakeCharacteristic.uuid, b"\x01")]


async def test_async_notification_callback_runs(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    received = asyncio.Event()

    async def on_data(_uuid: str, _data: bytes) -> None:
        received.set()

    await transport.start_notify("n", on_data)
    fake_client.notify(b"\x01")
    async with asyncio.timeout(1):
        await received.wait()


async def test_async_notification_errors_are_logged(
    device: BLEDevice,
    fake_client: FakeBleakClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    failed = asyncio.Event()

    async def failing(_uuid: str, _data: bytes) -> None:
        failed.set()
        raise RuntimeError("boom")

    await transport.start_notify("n", failing)
    with caplog.at_level(logging.ERROR):
        fake_client.notify(b"\x01")
        async with asyncio.timeout(1):
            await failed.wait()
        await asyncio.sleep(0)
    assert "DOT notification callback failed" in caplog.text


async def test_disconnect_cancels_slow_notification_task(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    started = asyncio.Event()
    tasks: list[asyncio.Task[Any]] = []

    async def slow(_uuid: str, _data: bytes) -> None:
        task = asyncio.current_task()
        assert task is not None
        tasks.append(task)
        started.set()
        await asyncio.Event().wait()

    await transport.start_notify("n", slow)
    fake_client.notify(b"\x01")
    async with asyncio.timeout(1):
        await started.wait()
    await transport.disconnect()
    assert tasks[0].cancelled()


async def test_notifications_after_disconnect_are_dropped(
    device: BLEDevice, fake_client: FakeBleakClient
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    received: list[bytes] = []
    await transport.start_notify("n", lambda _uuid, data: received.append(data))
    await transport.disconnect()
    fake_client.notify(b"\x01")
    assert received == []


class ProxyGattStatus:
    """Shape of the ``error`` field on an aioesphomeapi GATT error."""

    def __init__(self, error: int) -> None:
        self.error = error


class ProxyGattError(Exception):
    """Stand in for aioesphomeapi ``BluetoothGATTAPIError``."""

    def __init__(self, error: int) -> None:
        super().__init__(f"Bluetooth GATT Error error={error}")
        self.error = ProxyGattStatus(error)


def proxy_bleak_error(error: int) -> BleakError:
    cause = ProxyGattError(error)
    wrapped = BleakError(str(cause))
    wrapped.__cause__ = cause
    return wrapped


async def run_operation(transport: BleakTransport, operation: str) -> None:
    if operation == "read":
        await transport.read_gatt_char("c")
    else:
        await transport.write_gatt_char("c", b"\x01", response=True)


@pytest.mark.parametrize("operation", ["read", "write"])
async def test_proxy_refusal_becomes_a_gatt_protocol_error(
    device: BLEDevice, fake_client: FakeBleakClient, operation: str
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.fail_with = proxy_bleak_error(3)

    with pytest.raises(BleakGATTProtocolError) as info:
        await run_operation(transport, operation)

    assert info.value.code is BleakGATTProtocolErrorCode.WRITE_NOT_PERMITTED
    assert info.value.__cause__ is fake_client.fail_with


@pytest.mark.parametrize(
    "error",
    [
        proxy_bleak_error(-1),
        BleakError("plain"),
        BleakGATTProtocolError(BleakGATTProtocolErrorCode.READ_NOT_PERMITTED),
    ],
)
@pytest.mark.parametrize("operation", ["read", "write"])
async def test_other_bleak_errors_pass_through(
    device: BLEDevice, fake_client: FakeBleakClient, operation: str, error: BleakError
) -> None:
    transport = BleakTransport(device)
    await transport.connect(lambda: None)
    fake_client.fail_with = error

    with pytest.raises(BleakError) as info:
        await run_operation(transport, operation)

    assert info.value is error
