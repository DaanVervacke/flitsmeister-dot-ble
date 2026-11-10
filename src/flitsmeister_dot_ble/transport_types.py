"""The transport protocol the client needs, without a Bleak dependency.

Implement ``BleTransport`` to run the client over another BLE stack or
over a test double.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol, TypeAlias

__all__ = ["BleTransport", "DisconnectedCallback", "NotificationCallback"]

NotificationCallback: TypeAlias = Callable[[str, bytes], Awaitable[None] | None]  # noqa: UP040
"""Transport callback taking the characteristic UUID and the raw payload."""
DisconnectedCallback: TypeAlias = Callable[[], None]  # noqa: UP040
"""Transport callback for a link that dropped."""


class BleTransport(Protocol):
    """Minimal BLE transport supplied by the caller."""

    async def connect(self, disconnected_callback: DisconnectedCallback) -> None:
        """Establish the GATT connection.

        The transport calls ``disconnected_callback`` when the link drops,
        also after an explicit ``disconnect()``.
        """

    async def disconnect(self) -> None:
        """Tear down the GATT connection."""

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None:
        """Call ``callback`` with every notification on ``characteristic``.

        The DOT reports button pushes through indications and the status
        values through notifications. Either way the transport delivers
        them through this callback.
        """

    async def stop_notify(self, characteristic: str) -> None:
        """Stop the notifications on ``characteristic``."""

    async def read_gatt_char(self, characteristic: str) -> bytes:
        """Read ``characteristic`` and return its value.

        Raise ``bleak.exc.BleakGATTProtocolError`` or ``DotRejectedError``
        when the device refuses the read. During ``connect()`` the client
        leaves that value unset. After ``connect()`` the client raises
        ``DotRejectedError`` and keeps the session. An ``OSError``,
        ``BleakError`` or ``TimeoutError`` fails the session.
        """

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        """Write ``data`` to ``characteristic``, with or without response.

        Raise ``bleak.exc.BleakGATTProtocolError`` or ``DotRejectedError``
        when the device refuses the write. The client raises
        ``DotRejectedError`` and keeps the session. An ``OSError``,
        ``BleakError`` or ``TimeoutError`` fails the session.
        """
