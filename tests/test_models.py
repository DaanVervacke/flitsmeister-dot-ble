from dataclasses import replace

from flitsmeister_dot_ble import (
    ButtonAction,
    ChargingState,
    ConnectionStatus,
    DotButton,
    DotButtonEvent,
    DotState,
    DotUpdate,
    MotionStatus,
)


def test_state_defaults_to_unknown() -> None:
    state = DotState()

    assert state.battery_level is None
    assert state.charging_state is None
    assert state.motion_status is None
    assert state.manufacturer_name is None
    assert state.model_number is None
    assert state.serial_raw is None
    assert state.serial_uuid is None
    assert state.firmware_revision is None
    assert state.software_revision is None


def test_state_replace_keeps_other_fields() -> None:
    state = replace(DotState(), battery_level=50, model_number="DOT")
    state = replace(state, charging_state=ChargingState.CHARGING)

    assert state.battery_level == 50
    assert state.model_number == "DOT"
    assert state.charging_state is ChargingState.CHARGING


def test_button_wire_values() -> None:
    assert ButtonAction.PUSHED.value == 1
    assert ButtonAction.RELEASED.value == 2
    assert ButtonAction.SHORT_PRESS.value == 3
    assert ButtonAction.LONG_PRESS.value == 4


def test_button_names() -> None:
    assert DotButton.RED.value == "red"
    assert DotButton.BLUE.value == "blue"


def test_status_values() -> None:
    assert ConnectionStatus.DISCONNECTED.value == "disconnected"
    assert ConnectionStatus.CONNECTED.value == "connected"
    assert ConnectionStatus.READY.value == "ready"


def test_charging_and_motion_values() -> None:
    assert ChargingState.CONSUMING.value == 0
    assert ChargingState.CHARGING.value == 1
    assert ChargingState.CHARGING_DONE.value == 2
    assert MotionStatus.PARKED.value == 0
    assert MotionStatus.DRIVING.value == 1


def test_button_event_and_update() -> None:
    event = DotButtonEvent(DotButton.BLUE, ButtonAction.RELEASED)
    update = DotUpdate(
        DotState(),
        ConnectionStatus.READY,
        "characteristic",
        b"\x00\x02",
        event,
    )

    assert update.button == event
    assert update.payload == b"\x00\x02"
    assert update.status is ConnectionStatus.READY
    assert (
        DotUpdate(DotState(), ConnectionStatus.READY, "characteristic", b"").button
        is None
    )
