"""DOT payload encoding and decoding.

Every payload layout comes from the decompiled Flitsmeister app 15.1.1.
``PROTOCOL.md`` in the repository root holds the full wire notes.
"""

import hashlib
from collections.abc import Iterable
from uuid import UUID

from .const import DEVICE_NAME, SERVICE_UUID
from .exceptions import DotProtocolError
from .models import (
    Brightness,
    ButtonAction,
    ChargingState,
    DotButton,
    DotButtonEvent,
    LedOrientation,
    MotionStatus,
    SpeechLanguage,
)

__all__ = [
    "decode_battery_level",
    "decode_brightness",
    "decode_button_event",
    "decode_charging_state",
    "decode_led_orientation",
    "decode_motion_status",
    "decode_speech",
    "decode_text",
    "is_dot_advertisement",
    "serial_number_uuid",
]

_BUTTON_EVENT_LENGTH = 2
_BUTTON_PUSHED = 1
_BUTTON_RELEASED = 2


def is_dot_advertisement(name: str | None, service_uuids: Iterable[str]) -> bool:
    """Return True when an advertisement looks like a DOT.

    The Flitsmeister app scans for the DOT service UUID and matches the
    device by its advertised name.
    """
    if name == DEVICE_NAME:
        return True
    return any(uuid_.lower() == SERVICE_UUID for uuid_ in service_uuids)


def decode_battery_level(payload: bytes) -> int:
    """Decode the battery level, in percent from 0 to 100.

    Raises:
        DotProtocolError: The payload is not one byte, or the level is
            outside 0 to 100.
    """
    if len(payload) != 1:
        raise DotProtocolError(
            f"Battery level payload must be 1 byte, got {len(payload)}"
        )
    level = payload[0]
    if not 0 <= level <= 100:
        raise DotProtocolError(f"Battery level {level} is outside 0 to 100")
    return level


def decode_charging_state(payload: bytes) -> ChargingState:
    """Decode the charging state from the battery charging characteristic.

    The Flitsmeister app reads the state from byte 2 of the value. The
    meaning of the earlier bytes is unknown, the first captures will
    tell.

    Raises:
        DotProtocolError: The payload is shorter than 3 bytes, or byte 2
            is not a known state.
    """
    if len(payload) < 3:
        raise DotProtocolError(
            f"Charging state payload must be at least 3 bytes, got {len(payload)}"
        )
    try:
        return ChargingState(payload[2])
    except ValueError as err:
        raise DotProtocolError(f"Unknown charging state {payload[2]}") from err


def decode_motion_status(payload: bytes) -> MotionStatus:
    """Decode the motion status from the motion characteristic.

    Raises:
        DotProtocolError: The payload is empty.
    """
    if not payload:
        raise DotProtocolError("Motion status payload is empty")
    if payload[0] == MotionStatus.PARKED:
        return MotionStatus.PARKED
    return MotionStatus.DRIVING


def decode_brightness(payload: bytes) -> Brightness:
    """Decode the brightness from the brightness characteristic.

    The Flitsmeister app maps an unknown value to full brightness.

    Raises:
        DotProtocolError: The payload is not one byte.
    """
    if len(payload) != 1:
        raise DotProtocolError(f"Brightness payload must be 1 byte, got {len(payload)}")
    try:
        return Brightness(payload[0])
    except ValueError:
        return Brightness.BRIGHTNESS_100


def decode_led_orientation(payload: bytes) -> LedOrientation:
    """Decode the LED orientation from the LED rotation characteristic.

    The Flitsmeister app maps an unknown value to upside down.

    Raises:
        DotProtocolError: The payload is not one byte.
    """
    if len(payload) != 1:
        raise DotProtocolError(
            f"LED orientation payload must be 1 byte, got {len(payload)}"
        )
    try:
        return LedOrientation(payload[0])
    except ValueError:
        return LedOrientation.UPSIDE_DOWN


def decode_speech(payload: bytes) -> tuple[SpeechLanguage | None, int | None]:
    """Decode the speech language characteristic into language and voice.

    Byte 0 is the language, None when this library does not know the
    value. Byte 1, when present, is returned as is. A DOT on firmware
    2.9.0 with the Dutch voice reads ``01 01``.

    Raises:
        DotProtocolError: The payload is empty.
    """
    if not payload:
        raise DotProtocolError("Speech language payload is empty")
    try:
        language: SpeechLanguage | None = SpeechLanguage(payload[0])
    except ValueError:
        language = None
    voice = payload[1] if len(payload) > 1 else None
    return language, voice


def decode_button_event(payload: bytes) -> DotButtonEvent:
    """Decode one button event from the button events characteristic.

    The payload holds one byte per button, the red one first. Each byte
    is 0 for idle, 1 for pushed and 2 for released. The device sends
    one event per indication with the other byte at 0.

    Raises:
        DotProtocolError: The payload is not 2 bytes, holds values
            outside 0 to 2, or reports both buttons at once or both
            buttons idle.
    """
    if len(payload) != _BUTTON_EVENT_LENGTH:
        raise DotProtocolError(
            f"Button event payload must be 2 bytes, got {len(payload)}"
        )
    red, blue = payload
    if red and blue:
        raise DotProtocolError(
            f"Button event reports both buttons at once: {payload.hex()}"
        )
    for value in (red, blue):
        if value > _BUTTON_RELEASED:
            raise DotProtocolError(f"Button event holds an unknown state {value}")
    if red:
        return DotButtonEvent(DotButton.RED, _action(red))
    if blue:
        return DotButtonEvent(DotButton.BLUE, _action(blue))
    raise DotProtocolError("Button event reports both buttons idle")


def decode_text(payload: bytes) -> str:
    """Decode a UTF-8 text value, such as the manufacturer name.

    Raises:
        DotProtocolError: The payload is not valid UTF-8.
    """
    try:
        return payload.decode()
    except UnicodeDecodeError as err:
        raise DotProtocolError(
            f"Text payload is not valid UTF-8: {payload.hex()}"
        ) from err


def serial_number_uuid(payload: bytes) -> str:
    """Return the UUID string the Flitsmeister app derives from a serial.

    The app hashes the raw serial bytes with MD5 into a version 3 UUID
    and uppercases it. An empty payload hashes like any other value.
    """
    digest = hashlib.md5(payload).digest()  # noqa: S324
    return str(UUID(bytes=digest, version=3)).upper()


def _action(value: int) -> ButtonAction:
    if value == _BUTTON_PUSHED:
        return ButtonAction.PUSHED
    return ButtonAction.RELEASED
