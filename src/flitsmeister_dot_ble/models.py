"""Decoded DOT values, the merged device state and the session status.

The characteristic values merge into ``DotState``. ``DotUpdate`` carries
that snapshot to the update callback, with the button event when the
update came from a button characteristic.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

__all__ = [
    "ButtonAction",
    "ChargingState",
    "ConnectionStatus",
    "DotButton",
    "DotButtonEvent",
    "DotState",
    "DotUpdate",
    "MotionStatus",
]


class ConnectionStatus(StrEnum):
    """Protocol session status.

    A session moves from ``DISCONNECTED`` to ``CONNECTED`` when the
    transport connects, and to ``READY`` once the client subscribed to
    every characteristic and read the device information.
    """

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    READY = "ready"


class DotButton(StrEnum):
    """The two DOT buttons.

    The Flitsmeister app files a speed trap report for a long press on
    the red button and a dangerous situation report for the blue one.
    """

    RED = "red"
    BLUE = "blue"


class ButtonAction(IntEnum):
    """What happened to a button.

    ``PUSHED`` and ``RELEASED`` come straight from the wire and are the
    only actions the client emits today. A later milestone resolves
    ``SHORT_PRESS`` and ``LONG_PRESS`` from the hold time, the
    Flitsmeister app holds a button for a full second before it sends a
    report.
    """

    PUSHED = 1
    RELEASED = 2
    SHORT_PRESS = 3
    LONG_PRESS = 4


class ChargingState(IntEnum):
    """Charging state from the battery charging characteristic."""

    CONSUMING = 0
    CHARGING = 1
    CHARGING_DONE = 2


class MotionStatus(IntEnum):
    """Motion status from the motion characteristic.

    The DOT sleeps while parked and wakes on accelerometer motion.
    """

    PARKED = 0
    DRIVING = 1


@dataclass(frozen=True, slots=True)
class DotButtonEvent:
    """One button event decoded from the button events characteristic.

    ``action`` is ``PUSHED`` or ``RELEASED`` for a raw wire event.
    """

    button: DotButton
    action: ButtonAction


@dataclass(frozen=True, slots=True)
class DotState:
    """Merged snapshot of every decoded DOT value.

    Every field is None until the device reported it. ``serial_raw``
    holds the hex bytes of the serial number read, ``serial_uuid`` the
    uppercase UUID string the Flitsmeister app derives from them.
    """

    battery_level: int | None = None
    charging_state: ChargingState | None = None
    motion_status: MotionStatus | None = None
    manufacturer_name: str | None = None
    model_number: str | None = None
    serial_raw: str | None = None
    serial_uuid: str | None = None
    firmware_revision: str | None = None
    software_revision: str | None = None


@dataclass(frozen=True, slots=True)
class DotUpdate:
    """One decoded value passed to the update callback.

    ``characteristic`` is the UUID of the characteristic that carried
    the value, ``payload`` the raw bytes, and ``button`` the decoded
    button event when the update came from a button event.
    """

    state: DotState
    status: ConnectionStatus
    characteristic: str
    payload: bytes
    button: DotButtonEvent | None = None
