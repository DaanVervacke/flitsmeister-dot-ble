import uuid

import pytest
from flitsmeister_dot_ble import (
    ButtonAction,
    ChargingState,
    DotButton,
    DotButtonEvent,
    DotProtocolError,
    MotionStatus,
    is_dot_advertisement,
)
from flitsmeister_dot_ble.const import SERVICE_UUID
from flitsmeister_dot_ble.protocol import (
    decode_battery_level,
    decode_button_event,
    decode_charging_state,
    decode_motion_status,
    decode_text,
    serial_number_uuid,
)


def test_advertisement_matches_device_name() -> None:
    assert is_dot_advertisement("FM DOT", ())
    assert not is_dot_advertisement("FM DOT 2", ())
    assert not is_dot_advertisement(None, ())


def test_advertisement_matches_service_uuid() -> None:
    assert is_dot_advertisement(None, (SERVICE_UUID,))
    assert is_dot_advertisement("Other", (SERVICE_UUID.upper(),))
    assert not is_dot_advertisement("Other", ("0000180f-0000-1000-8000-00805f9b34fb",))


def test_battery_level_decodes() -> None:
    assert decode_battery_level(b"\x00") == 0
    assert decode_battery_level(b"\x64") == 100


@pytest.mark.parametrize("payload", [b"", b"\x64\x00", b"\x00\x00"])
def test_battery_level_rejects_wrong_length(payload: bytes) -> None:
    with pytest.raises(DotProtocolError, match="1 byte"):
        decode_battery_level(payload)


@pytest.mark.parametrize("payload", [b"\x65", b"\xff"])
def test_battery_level_rejects_out_of_range(payload: bytes) -> None:
    with pytest.raises(DotProtocolError, match="outside 0 to 100"):
        decode_battery_level(payload)


def test_charging_state_decodes() -> None:
    assert decode_charging_state(b"\x00\x00\x00") is ChargingState.CONSUMING
    assert decode_charging_state(b"\x01\x02\x01") is ChargingState.CHARGING
    assert decode_charging_state(b"\xff\xff\x02") is ChargingState.CHARGING_DONE


@pytest.mark.parametrize("payload", [b"", b"\x00", b"\x00\x00"])
def test_charging_state_rejects_short_payload(payload: bytes) -> None:
    with pytest.raises(DotProtocolError, match="at least 3 bytes"):
        decode_charging_state(payload)


def test_charging_state_rejects_unknown_state() -> None:
    with pytest.raises(DotProtocolError, match="Unknown charging state 3"):
        decode_charging_state(b"\x00\x00\x03")


def test_motion_status_decodes() -> None:
    assert decode_motion_status(b"\x00") is MotionStatus.PARKED
    assert decode_motion_status(b"\x01") is MotionStatus.DRIVING
    assert decode_motion_status(b"\xff") is MotionStatus.DRIVING


def test_motion_status_rejects_empty_payload() -> None:
    with pytest.raises(DotProtocolError, match="empty"):
        decode_motion_status(b"")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x01\x00", DotButtonEvent(DotButton.RED, ButtonAction.PUSHED)),
        (b"\x02\x00", DotButtonEvent(DotButton.RED, ButtonAction.RELEASED)),
        (b"\x00\x01", DotButtonEvent(DotButton.BLUE, ButtonAction.PUSHED)),
        (b"\x00\x02", DotButtonEvent(DotButton.BLUE, ButtonAction.RELEASED)),
    ],
)
def test_button_event_decodes(payload: bytes, expected: DotButtonEvent) -> None:
    assert decode_button_event(payload) == expected


@pytest.mark.parametrize("payload", [b"", b"\x01", b"\x01\x00\x00"])
def test_button_event_rejects_wrong_length(payload: bytes) -> None:
    with pytest.raises(DotProtocolError, match="2 bytes"):
        decode_button_event(payload)


def test_button_event_rejects_both_buttons() -> None:
    with pytest.raises(DotProtocolError, match="both buttons at once"):
        decode_button_event(b"\x01\x02")


def test_button_event_rejects_unknown_state() -> None:
    with pytest.raises(DotProtocolError, match="unknown state 3"):
        decode_button_event(b"\x03\x00")


def test_button_event_rejects_idle_payload() -> None:
    with pytest.raises(DotProtocolError, match="both buttons idle"):
        decode_button_event(b"\x00\x00")


def test_text_decodes() -> None:
    assert decode_text(b"Flitsmeister") == "Flitsmeister"


def test_text_rejects_invalid_utf8() -> None:
    with pytest.raises(DotProtocolError, match="not valid UTF-8"):
        decode_text(b"\xff\xfe")


def test_serial_number_uuid_is_deterministic() -> None:
    first = serial_number_uuid(b"\x11\x22\x33")
    second = serial_number_uuid(b"\x11\x22\x33")

    assert first == second
    assert first == first.upper()
    assert first != serial_number_uuid(b"\x11\x22\x34")


def test_serial_number_uuid_is_a_version_3_uuid() -> None:
    parsed = uuid.UUID(serial_number_uuid(b"\x11\x22\x33"))

    assert parsed.version == 3
    assert parsed.variant == uuid.RFC_4122


def test_serial_number_uuid_hashes_empty_payload() -> None:
    assert (
        serial_number_uuid(b"")
        == str(
            uuid.UUID(
                bytes=b"\xd4\x1d\x8c\xd9\x8f\x00\xb2\x04\xe9\x80\x09\x98\xec\xf8\x42\x7e",
                version=3,
            )
        ).upper()
    )
