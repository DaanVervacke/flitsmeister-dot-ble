"""Replay the live capture fixtures through the client and the decoders.

The fixtures hold real DOT traffic recorded by ``scripts/probe_dot.py``,
with the serial number replaced by the probe's fixed fake value.
"""

import json
from pathlib import Path

import pytest
from flitsmeister_dot_ble import (
    Brightness,
    ButtonAction,
    ChargingState,
    DotButton,
    DotProtocolError,
    FlitsmeisterDotClient,
    LedOrientation,
    MotionStatus,
    SpeechLanguage,
    Volume,
    animations,
)
from flitsmeister_dot_ble.const import BUTTON_EVENTS_CHARACTERISTIC_UUID
from flitsmeister_dot_ble.protocol import (
    decode_brightness,
    decode_button_event,
    decode_led_orientation,
)

from .helpers import FakeTransport

FIXTURES = Path(__file__).parent / "fixtures"


def load_records(name: str) -> list[dict[str, object]]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_dot_connect_read_capture_exists() -> None:
    records = load_records("dot_connect_read.jsonl")

    assert len(records) == 22
    assert {record["dir"] for record in records} == {"rx", "read"}


async def test_dot_connect_read_capture_replays_through_the_client() -> None:
    records = load_records("dot_connect_read.jsonl")
    reads = {
        str(record["chr"]): bytes.fromhex(str(record["hex"]))
        for record in records
        if record["dir"] == "read"
    }
    transport = FakeTransport(reads=reads)

    async with FlitsmeisterDotClient(transport) as client:
        assert client.state.battery_level == 69
        assert client.state.charging_state is ChargingState.CHARGING_DONE
        assert client.state.motion_status is MotionStatus.DRIVING
        assert client.state.manufacturer_name == "Flitsmeister"
        assert client.state.model_number == "nrf54l15"
        assert client.state.serial_raw == "0011223344556677"
        assert client.state.serial_uuid is not None
        assert client.state.firmware_revision == "2.9.0"
        assert client.state.software_revision == "2.9.0"


def test_brightness_maps_unknown_values_to_full() -> None:
    assert decode_brightness(b"\x37") is Brightness.BRIGHTNESS_100


def test_brightness_rejects_wrong_length() -> None:
    with pytest.raises(DotProtocolError, match="1 byte"):
        decode_brightness(b"\x64\x00")


def test_led_orientation_maps_unknown_values_to_upside_down() -> None:
    assert decode_led_orientation(b"\x05") is LedOrientation.UPSIDE_DOWN


def test_led_orientation_rejects_wrong_length() -> None:
    with pytest.raises(DotProtocolError, match="1 byte"):
        decode_led_orientation(b"")


def test_drive_tour_writes_match_the_presets() -> None:
    records = load_records("dot_drive_tour.jsonl")
    writes = [
        bytes.fromhex(str(record["hex"])) for record in records if record["dir"] == "tx"
    ]

    assert animations.startup().to_bytes() in writes
    assert animations.speed_trap().to_bytes() in writes
    assert animations.speed_cam().to_bytes() in writes
    assert animations.traffic_camera().to_bytes() in writes
    assert animations.avg_speed_check_start().to_bytes() in writes
    assert animations.avg_speed_check_end().to_bytes() in writes
    assert animations.traffic_jam_start().to_bytes() in writes
    assert animations.traffic_jam_end().to_bytes() in writes
    assert animations.police_hotspot().to_bytes() in writes
    assert animations.roadworks().to_bytes() in writes
    assert animations.ambulance().to_bytes() in writes
    assert animations.fire_truck().to_bytes() in writes
    assert animations.police().to_bytes() in writes
    assert animations.emergency_vehicle().to_bytes() in writes
    assert animations.railway_crossing().to_bytes() in writes
    assert animations.wrong_way_driving().to_bytes() in writes
    assert animations.wrong_way_driver().to_bytes() in writes
    assert animations.reporting().to_bytes() in writes
    assert animations.updating().to_bytes() in writes
    assert (
        animations.incident(speech=animations.DotSound.SPEECH_ACCIDENT).to_bytes()
        in writes
    )
    assert (
        animations.lane_closure(
            speech=animations.DotSound.SPEECH_LANE_CLOSED
        ).to_bytes()
        in writes
    )
    assert (
        animations.progress(
            color=animations.DotColor.SPEED_TRAP, fraction=0.5
        ).to_bytes()
        in writes
    )
    assert animations.overspeed(fraction=0.75).to_bytes() in writes
    assert animations.brightness_sample().to_bytes() in writes
    assert animations.orientation_sample().to_bytes() in writes
    assert animations.fade_out_without_cut_off().to_bytes() in writes
    assert animations.fade_out().to_bytes() in writes
    assert bytes((Volume.NORMAL,)) in writes
    assert bytes((Brightness.BRIGHTNESS_10,)) in writes
    assert bytes((LedOrientation.UPSIDE_DOWN,)) in writes
    assert bytes((SpeechLanguage.DUTCH,)) in writes


def test_dot_button_events_from_capture_decode() -> None:
    records = load_records("dot_connect_read.jsonl")
    payloads = [
        bytes.fromhex(str(record["hex"]))
        for record in records
        if record["chr"] == BUTTON_EVENTS_CHARACTERISTIC_UUID and record["dir"] == "rx"
    ]

    events = [decode_button_event(payload) for payload in payloads]

    assert [(event.button, event.action) for event in events] == [
        (DotButton.RED, ButtonAction.RELEASED),
        (DotButton.BLUE, ButtonAction.RELEASED),
        (DotButton.BLUE, ButtonAction.PUSHED),
        (DotButton.RED, ButtonAction.PUSHED),
        (DotButton.RED, ButtonAction.RELEASED),
        (DotButton.BLUE, ButtonAction.RELEASED),
        (DotButton.BLUE, ButtonAction.PUSHED),
        (DotButton.BLUE, ButtonAction.RELEASED),
        (DotButton.BLUE, ButtonAction.PUSHED),
        (DotButton.RED, ButtonAction.PUSHED),
    ]
