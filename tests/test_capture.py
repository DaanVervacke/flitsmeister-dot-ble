"""Replay the live capture fixtures through the client and the decoders.

The fixtures hold real DOT traffic recorded by ``scripts/probe_dot.py``,
with the serial number replaced by the probe's fixed fake value.
"""

import json
from pathlib import Path

from flitsmeister_dot_ble import (
    ButtonAction,
    ChargingState,
    DotButton,
    FlitsmeisterDotClient,
    MotionStatus,
)
from flitsmeister_dot_ble.const import BUTTON_EVENTS_CHARACTERISTIC_UUID
from flitsmeister_dot_ble.protocol import decode_button_event

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
