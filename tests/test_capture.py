"""Replay the live capture fixtures through the client and the decoders.

The fixtures hold real DOT traffic recorded by ``scripts/probe_dot.py``
and ``scripts/live_validate.py``, with the serial number replaced by a
fixed fake value.
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
from flitsmeister_dot_ble.const import (
    ANIMATION_CHARACTERISTIC_UUID,
    BATTERY_CHARGING_CHARACTERISTIC_UUID,
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    BUTTON_EVENTS_CHARACTERISTIC_UUID,
    MOTION_CHARACTERISTIC_UUID,
    SPEECH_LANGUAGE_CHARACTERISTIC_UUID,
)
from flitsmeister_dot_ble.protocol import (
    decode_battery_level,
    decode_brightness,
    decode_button_event,
    decode_charging_state,
    decode_led_orientation,
    decode_motion_status,
    decode_speech,
)

from .helpers import FakeTransport

FIXTURES = Path(__file__).parent / "fixtures"
LIVE_SPEECH_READ = bytes.fromhex("0101")


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
    reads.setdefault(SPEECH_LANGUAGE_CHARACTERISTIC_UUID, LIVE_SPEECH_READ)
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
        assert client.state.speech_language is SpeechLanguage.DUTCH


def test_brightness_maps_unknown_values_to_full() -> None:
    assert decode_brightness(b"\x37") is Brightness.BRIGHTNESS_100


def test_brightness_rejects_wrong_length() -> None:
    with pytest.raises(DotProtocolError, match="1 byte"):
        decode_brightness(b"\x64\x00")


def test_led_orientation_maps_unknown_values_to_upside_down() -> None:
    assert decode_led_orientation(b"\x05") is LedOrientation.UPSIDE_DOWN


def test_speech_read_from_a_live_dot_decodes() -> None:
    assert decode_speech(LIVE_SPEECH_READ) == (SpeechLanguage.DUTCH, 1)


def test_speech_rejects_an_empty_payload() -> None:
    with pytest.raises(DotProtocolError, match="empty"):
        decode_speech(b"")


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


RX_DECODERS = {
    BATTERY_LEVEL_CHARACTERISTIC_UUID: decode_battery_level,
    BATTERY_CHARGING_CHARACTERISTIC_UUID: decode_charging_state,
    MOTION_CHARACTERISTIC_UUID: decode_motion_status,
    BUTTON_EVENTS_CHARACTERISTIC_UUID: decode_button_event,
}


def first_reads(records: list[dict[str, object]]) -> dict[str, bytes]:
    reads: dict[str, bytes] = {}
    for record in records:
        if record["dir"] == "read":
            reads.setdefault(str(record["chr"]), bytes.fromhex(str(record["hex"])))
    return reads


@pytest.mark.parametrize("name", ["dot_live_validation.jsonl", "dot_live_rerun.jsonl"])
def test_live_run_notifications_all_decode(name: str) -> None:
    records = load_records(name)
    received = [record for record in records if record["dir"] == "rx"]

    for record in received:
        RX_DECODERS[str(record["chr"])](bytes.fromhex(str(record["hex"])))

    assert {str(record["chr"]) for record in received} == set(RX_DECODERS)


async def test_live_rerun_connect_replays_through_the_client() -> None:
    transport = FakeTransport(reads=first_reads(load_records("dot_live_rerun.jsonl")))

    async with FlitsmeisterDotClient(transport) as client:
        state = client.state
        assert state.model_number == "nrf54l15"
        assert state.firmware_revision == "2.9.0"
        assert state.charging_state is ChargingState.CONSUMING
        assert state.speech_language is SpeechLanguage.DUTCH
        assert state.speech_voice_raw == 1
        await client.read_settings()
        assert client.state.brightness is Brightness.BRIGHTNESS_100
        assert client.state.led_orientation is LedOrientation.NORMAL


def test_live_run_writes_match_the_library() -> None:
    records = load_records("dot_live_validation.jsonl")
    animation_writes = {
        bytes.fromhex(str(record["hex"]))
        for record in records
        if record["dir"] == "tx" and record["chr"] == ANIMATION_CHARACTERISTIC_UUID
    }

    for builder in (
        animations.speed_trap,
        animations.speed_cam,
        animations.traffic_camera,
        animations.avg_speed_check_start,
        animations.police_hotspot,
        animations.roadworks,
    ):
        assert builder(rateable=True).to_bytes() in animation_writes
        assert builder(rateable=False).to_bytes() in animation_writes
    for color in animations.DotColor:
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            progress = animations.progress(color=color, fraction=fraction)
            assert progress.to_bytes() in animation_writes
    assert (
        animations.progress(color=animations.DotColor.SUCCESS, fraction=1.5).to_bytes()
        in animation_writes
    )


def test_live_run_shows_the_refused_language_write() -> None:
    records = load_records("dot_live_validation.jsonl")
    language_writes = [
        record
        for record in records
        if record["dir"] == "tx"
        and record["chr"] == SPEECH_LANGUAGE_CHARACTERISTIC_UUID
    ]
    rerun = load_records("dot_live_rerun.jsonl")

    assert language_writes
    assert all(
        record["chr"] != SPEECH_LANGUAGE_CHARACTERISTIC_UUID
        for record in rerun
        if record["dir"] == "tx"
    )
