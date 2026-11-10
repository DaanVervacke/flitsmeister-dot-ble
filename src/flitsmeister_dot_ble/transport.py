"""Bleak based transport for the Flitsmeister DOT."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError, BleakGATTProtocolError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from .const import DEFAULT_CONNECT_TIMEOUT_SECONDS
from .exceptions import DotConnectionError
from .transport_types import BleTransport, DisconnectedCallback, NotificationCallback

__all__ = ["BleakTransport"]

_LOGGER = logging.getLogger(__name__)

_ATT_ERROR_CODES = range(1, 256)


def _proxy_att_error(err: BleakError) -> int | None:
    """Return the ATT error code an ESPHome proxy wrapped in ``err``.

    bleak-esphome raises a plain ``BleakError`` caused by an aioesphomeapi
    ``BluetoothGATTAPIError``. Its ``error.error`` holds the ATT error code
    of the device, or -1 when the link dropped. The code is read by
    attribute so this module does not import aioesphomeapi.
    """
    code = getattr(getattr(err.__cause__, "error", None), "error", None)
    if isinstance(code, int) and code in _ATT_ERROR_CODES:
        return code
    return None


class BleakTransport(BleTransport):
    """Adapt a Bleak client to the DOT transport protocol."""

    def __init__(
        self,
        device: BLEDevice,
        *,
        timeout: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        client_factory: type[BleakClient] | None = None,
        ble_device_callback: Callable[[], BLEDevice] | None = None,
    ) -> None:
        """Initialize the transport.

        Args:
            device: The BLE device to connect to.
            timeout: Timeout in seconds passed to the Bleak client.
                ``establish_connection`` sets its own timeout for each
                connect attempt, so this value does not limit the connect.
            client_factory: The Bleak client class. Defaults to
                ``BleakClientWithServiceCache``.
            ble_device_callback: Returns the latest ``BLEDevice``. It is
                passed to ``establish_connection``, which accepts it but
                does not call it in bleak-retry-connector 4.7.1.
        """
        self.device = device
        self.timeout = timeout
        self._client_class: type[BleakClient] = (
            client_factory
            if client_factory is not None
            else BleakClientWithServiceCache
        )
        self._ble_device_callback = ble_device_callback
        self._client: BleakClient | None = None
        self._disconnected_callback: DisconnectedCallback | None = None
        self._notification_tasks: set[asyncio.Task[None]] = set()
        self._accept_notifications = True

    @property
    def client(self) -> BleakClient:
        """The connected Bleak client.

        Raises:
            DotConnectionError: The transport is not connected.
        """
        if self._client is None:
            raise DotConnectionError("DOT BLE transport is not connected")
        return self._client

    async def connect(self, disconnected_callback: DisconnectedCallback) -> None:
        """Connect to the device. A live connection is reused.

        Args:
            disconnected_callback: Called when Bleak reports that the link
                dropped. A reused connection reports to the latest
                callback.
        """
        self._accept_notifications = True
        self._disconnected_callback = disconnected_callback
        if self._client is None or not self._client.is_connected:
            self._client = await establish_connection(
                self._client_class,
                self.device,
                self.device.name or self.device.address,
                disconnected_callback=self._on_disconnect,
                ble_device_callback=self._ble_device_callback,
                timeout=self.timeout,
            )

    async def disconnect(self) -> None:
        """Disconnect and cancel any in-flight notification callbacks."""
        self._accept_notifications = False
        await self._cancel_notification_tasks()
        client = self._client
        try:
            if client is not None:
                await client.disconnect()
        finally:
            self._client = None

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None:
        """Call ``callback`` with every notification on ``characteristic``.

        A callback that returns an awaitable runs as a task. ``disconnect()``
        cancels those tasks, and errors they raise are logged.

        Raises:
            DotConnectionError: The transport is not connected.
        """

        def on_notification(
            gatt_characteristic: BleakGATTCharacteristic, payload: bytearray
        ) -> None:
            if not self._accept_notifications:
                return
            result = callback(gatt_characteristic.uuid, bytes(payload))
            if isinstance(result, Awaitable):
                task = asyncio.ensure_future(result)
                self._notification_tasks.add(task)
                task.add_done_callback(self._notification_task_done)

        await self.client.start_notify(characteristic, on_notification)

    async def stop_notify(self, characteristic: str) -> None:
        """Unsubscribe from notifications.

        Does nothing when the link already dropped.
        """
        if self._client is not None and self._client.is_connected:
            await self._client.stop_notify(characteristic)

    async def read_gatt_char(self, characteristic: str) -> bytes:
        """Read ``characteristic`` and return its value.

        Raises:
            DotConnectionError: The transport is not connected.
            BleakGATTProtocolError: The device refused the read, also when
                an ESPHome proxy reports the refusal.
        """
        try:
            return bytes(await self.client.read_gatt_char(characteristic))
        except BleakGATTProtocolError:
            raise
        except BleakError as err:
            code = _proxy_att_error(err)
            if code is None:
                raise
            raise BleakGATTProtocolError(code) from err

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        """Write ``data`` to ``characteristic``, with or without response.

        Raises:
            DotConnectionError: The transport is not connected.
            BleakGATTProtocolError: The device refused the write, also when
                an ESPHome proxy reports the refusal.
        """
        try:
            await self.client.write_gatt_char(characteristic, data, response=response)
        except BleakGATTProtocolError:
            raise
        except BleakError as err:
            code = _proxy_att_error(err)
            if code is None:
                raise
            raise BleakGATTProtocolError(code) from err

    def _on_disconnect(self, _client: BleakClient) -> None:
        callback = self._disconnected_callback
        if callback is not None:
            callback()

    def _notification_task_done(self, task: asyncio.Task[None]) -> None:
        self._notification_tasks.discard(task)
        if task.cancelled():
            return
        with suppress(asyncio.CancelledError):
            error = task.exception()
        if error is not None:
            _LOGGER.error("DOT notification callback failed", exc_info=error)

    async def _cancel_notification_tasks(self) -> None:
        tasks = tuple(self._notification_tasks)
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
