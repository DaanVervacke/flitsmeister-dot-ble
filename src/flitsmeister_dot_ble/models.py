"""Decoded DOT values, the merged device state and the session status.

The characteristic values merge into ``DotState``. ``DotUpdate`` carries
that snapshot to the update callback, with the button event when the
update came from a button characteristic.
"""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

__all__ = [
    "Brightness",
    "ButtonAction",
    "ChargingState",
    "ConnectionStatus",
    "DotButton",
    "DotButtonEvent",
    "DotState",
    "DotUpdate",
    "LedOrientation",
    "MotionStatus",
    "SpeechLanguage",
    "Volume",
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

    ``PUSHED`` and ``RELEASED`` come straight from the wire. The client
    resolves ``SHORT_PRESS`` and ``LONG_PRESS`` from the hold time, a
    release before ``long_press_seconds`` is a short press and holding
    past it is a long press, like the Flitsmeister app, which sends its
    report after a full second.
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


class Volume(IntEnum):
    """Speaker volume written to the volume characteristic."""

    SILENT = 0
    LOW = 1
    NORMAL = 2
    HARD = 3


class Brightness(IntEnum):
    """LED brightness written to the brightness characteristic, in percent."""

    BRIGHTNESS_10 = 10
    BRIGHTNESS_20 = 20
    BRIGHTNESS_30 = 30
    BRIGHTNESS_40 = 40
    BRIGHTNESS_50 = 50
    BRIGHTNESS_60 = 60
    BRIGHTNESS_70 = 70
    BRIGHTNESS_80 = 80
    BRIGHTNESS_90 = 90
    BRIGHTNESS_100 = 100


class LedOrientation(IntEnum):
    """LED ring orientation written to the LED rotation characteristic."""

    NORMAL = 0
    UPSIDE_DOWN = 1


class SpeechLanguage(IntEnum):
    """Voice language read from byte 0 of the speech language characteristic.

    The voice is part of the firmware image. The Flitsmeister app changes
    it by flashing an image built for another language and voice. The
    characteristic itself is read only.
    """

    ENGLISH = 0
    DUTCH = 1
    GERMAN = 2
    FRENCH = 3


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
    Volume mirrors the last written value, the Flitsmeister app never
    reads it back. Brightness and LED orientation reflect the value read
    back from the device after a write or after ``read_settings``.
    ``speech_language`` and ``speech_voice_raw`` are read while
    connecting. ``speech_language`` stays None for a language byte this
    library does not know. ``speech_voice_raw`` holds byte 1 as is. Its
    meaning is unconfirmed.
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
    volume: Volume | None = None
    brightness: Brightness | None = None
    led_orientation: LedOrientation | None = None
    speech_language: SpeechLanguage | None = None
    speech_voice_raw: int | None = None


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
