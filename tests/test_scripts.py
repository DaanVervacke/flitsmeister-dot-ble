import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import habluetooth
import pytest
from bleak.backends.device import BLEDevice
from flitsmeister_dot_ble import (
    Brightness,
    DotState,
    FlitsmeisterDotClient,
    LedOrientation,
    Volume,
    animations,
    is_dot_advertisement,
)
from flitsmeister_dot_ble.const import (
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    BRIGHTNESS_CHARACTERISTIC_UUID,
    LED_ROTATION_CHARACTERISTIC_UUID,
    READ_CHARACTERISTICS,
    SERIAL_NUMBER_CHARACTERISTIC_UUID,
)
from scripts import _dot_common as common
from scripts import drive_dot_client, probe_dot

from .helpers import FakeTransport, make_client

REAL_SERIAL = bytes.fromhex("a1b2c3d4e5")


@pytest.fixture(autouse=True)
def _clear_script_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DOT_PROXY", "DOT_NOISE_PSK", "DOT_DEVICE_ADDRESS"):
        monkeypatch.delenv(name, raising=False)


def test_redact_payload_replaces_serial() -> None:
    redacted = common.redact_payload(SERIAL_NUMBER_CHARACTERISTIC_UUID, REAL_SERIAL)

    assert redacted == b"\x00\x11\x22\x33\x44"
    assert len(redacted) == len(REAL_SERIAL)


def test_redact_payload_repeats_pattern_for_long_serials() -> None:
    redacted = common.redact_payload(SERIAL_NUMBER_CHARACTERISTIC_UUID, REAL_SERIAL * 3)

    assert redacted == (common.FAKE_SERIAL * 2)[: len(REAL_SERIAL) * 3]


def test_redact_payload_matches_uppercase_uuid() -> None:
    redacted = common.redact_payload(
        SERIAL_NUMBER_CHARACTERISTIC_UUID.upper(), REAL_SERIAL
    )

    assert redacted == b"\x00\x11\x22\x33\x44"


def test_redact_payload_keeps_other_characteristics() -> None:
    payload = b"\x64"

    assert common.redact_payload(BATTERY_LEVEL_CHARACTERISTIC_UUID, payload) == payload


def test_state_record_redacts_the_serial() -> None:
    state = DotState(
        serial_raw="05eb6fdea54731d6",
        serial_uuid="6EFFB6F5-0EA8-3C8E-9B8F-DB97D6B281F5",
        volume=Volume.NORMAL,
    )
    record = common.state_record(state)

    assert record["serial_raw"] == "0011223344556677"
    assert record["serial_uuid"] == "REDACTED"
    assert record["volume"] == "NORMAL"
    empty = common.state_record(DotState())
    assert empty["serial_raw"] is None
    assert empty["serial_uuid"] is None


def test_capture_writer_records_redacted_serial(tmp_path: Path) -> None:
    path = tmp_path / "out" / "capture.jsonl"
    with common.CaptureWriter(path) as writer:
        writer.write("read", SERIAL_NUMBER_CHARACTERISTIC_UUID, REAL_SERIAL)
        writer.write("read", BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x64")
    record = json.loads(path.read_text().splitlines()[0])
    assert record["dir"] == "read"
    assert record["chr"] == SERIAL_NUMBER_CHARACTERISTIC_UUID
    assert record["hex"] == "0011223344"
    battery = json.loads(path.read_text().splitlines()[1])
    assert battery["hex"] == "64"


def test_capture_writer_without_path_captures_nothing() -> None:
    with common.CaptureWriter(None) as writer:
        writer.write("rx", BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x64")
    writer.close()


async def test_capture_transport_records_both_directions(tmp_path: Path) -> None:
    path = tmp_path / "capture.jsonl"
    inner = FakeTransport()
    with common.CaptureWriter(path) as writer:
        async with make_client(common.CaptureTransport(inner, writer)) as client:
            assert client.ready
            inner.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")
            await asyncio.sleep(0.05)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    directions = [record["dir"] for record in records]
    assert directions.count("read") == len(READ_CHARACTERISTICS)
    assert "rx" in directions
    assert inner.stopped_characteristics
    assert inner.disconnect_calls == 1


def test_proxy_host() -> None:
    assert common.proxy_host("192.168.1.2") == "192.168.1.2"
    assert common.proxy_host("http://proxy.local:6053") == "proxy.local"


def _sighting(
    address: str, name: str | None, uuids: tuple[str, ...] = ()
) -> common.Sighting:
    return common.Sighting(BLEDevice(address, name, None), name, -60, uuids)


async def test_find_dot() -> None:
    sightings = [
        _sighting("11:11:11:11:11:11", "Phone"),
        _sighting("22:22:22:22:22:22", "FM DOT"),
    ]

    async def scan(_seconds: float) -> list[common.Sighting]:
        return sightings

    found = await common.find_dot(scan, None, 1)
    assert found.address == "22:22:22:22:22:22"
    found = await common.find_dot(scan, "11:11:11:11:11:11", 1)
    assert found.address == "11:11:11:11:11:11"
    with pytest.raises(TimeoutError):
        await common.find_dot(scan, "33:33:33:33:33:33", 0.05)


async def test_find_dot_scans_in_windows_until_seen() -> None:
    calls: list[float] = []

    async def scan(seconds: float) -> list[common.Sighting]:
        calls.append(seconds)
        if len(calls) == 1:
            return []
        return [_sighting("22:22:22:22:22:22", "FM DOT")]

    found = await common.find_dot(scan, None, 60)
    assert found.address == "22:22:22:22:22:22"
    assert len(calls) == 2
    assert calls[0] <= common.SCAN_WINDOW_SECONDS


class FakeScanner:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0
        self.fail_stop = False

    async def start(self) -> None:
        self.starts += 1

    async def stop(self) -> None:
        self.stops += 1
        if self.fail_stop:
            raise OSError("stop failed")


async def test_background_scanner_disabled_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scanner must not be created")

    monkeypatch.setattr(common, "BleakScanner", fail)
    async with common.background_scanner(False):
        pass


async def test_background_scanner_starts_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = FakeScanner()
    monkeypatch.setattr(common, "BleakScanner", lambda: scanner)
    async with common.background_scanner(True):
        assert scanner.starts == 1
    assert scanner.stops == 1


async def test_background_scanner_survives_stop_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = FakeScanner()
    scanner.fail_stop = True
    monkeypatch.setattr(common, "BleakScanner", lambda: scanner)
    async with common.background_scanner(True):
        pass
    assert scanner.stops == 1


async def test_local_scanner_is_yielded_without_proxy() -> None:
    async with common.open_scanner(None, None) as scan:
        assert scan is common.scan_local


def test_probe_config_from_args() -> None:
    config = probe_dot.config_from_args(
        ["--address", "AA", "--capture-seconds", "5", "--list-advertisements"]
    )
    assert config.address == "AA"
    assert config.capture_seconds == 5
    assert config.list_advertisements
    assert config.proxy is None


def test_probe_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing(_config: probe_dot.ProbeConfig) -> None:
        raise RuntimeError("no adapter")

    monkeypatch.setattr(probe_dot, "capture", failing)
    assert probe_dot.main(["--capture-seconds", "0"]) == 1
    assert "no adapter" in caplog.text
    assert any(record.exc_info for record in caplog.records)


async def test_probe_lists_advertisements(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def local(_seconds: float) -> list[common.Sighting]:
        return [_sighting("22:22:22:22:22:22", "FM DOT")]

    monkeypatch.setattr(common, "scan_local", local)
    config = probe_dot.config_from_args(["--list-advertisements"])
    with caplog.at_level("INFO"):
        await probe_dot.list_advertisements(config)
    assert "dot=True" in caplog.text
    assert "DEVICE_ADDRESS" in caplog.text


async def test_probe_capture_records_traffic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    transport = FakeTransport()

    @asynccontextmanager
    async def scanner(
        _proxy: str | None, _noise_psk: str | None
    ) -> AsyncIterator[common.Scanner]:
        async def scan(_seconds: float) -> list[common.Sighting]:
            return [_sighting("22:22:22:22:22:22", "FM DOT")]

        yield scan

    def bleak_transport(device: BLEDevice) -> FakeTransport:
        assert device.address == "22:22:22:22:22:22"
        return transport

    monkeypatch.setattr(common, "open_scanner", scanner)
    monkeypatch.setattr(common, "BleakScanner", FakeScanner)
    monkeypatch.setattr(common, "BleakTransport", bleak_transport)
    output = tmp_path / "capture.jsonl"
    config = probe_dot.config_from_args(
        ["--capture-seconds", "0", "--output", str(output)]
    )
    await probe_dot.capture(config)
    assert transport.connect_calls == 1
    assert transport.disconnect_calls == 1
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == len(READ_CHARACTERISTICS)
    assert {record["dir"] for record in records} == {"read"}
    serial_records = [
        record
        for record in records
        if record["chr"] == SERIAL_NUMBER_CHARACTERISTIC_UUID
    ]
    assert serial_records[0]["hex"] == "001122"


async def test_probe_capture_retries_after_connect_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transports: list[FakeTransport] = []

    @asynccontextmanager
    async def scanner(
        _proxy: str | None, _noise_psk: str | None
    ) -> AsyncIterator[common.Scanner]:
        async def scan(_seconds: float) -> list[common.Sighting]:
            return [_sighting("22:22:22:22:22:22", "FM DOT")]

        yield scan

    def bleak_transport(_device: BLEDevice) -> FakeTransport:
        transport = FakeTransport()
        if not transports:
            transport.fail_connect = OSError("device gone")
        transports.append(transport)
        return transport

    monkeypatch.setattr(common, "open_scanner", scanner)
    monkeypatch.setattr(common, "BleakScanner", FakeScanner)
    monkeypatch.setattr(common, "BleakTransport", bleak_transport)
    with caplog.at_level("WARNING"):
        await probe_dot.capture(
            probe_dot.config_from_args(
                ["--capture-seconds", "0", "--output", str(tmp_path / "c.jsonl")]
            )
        )
    assert len(transports) == 2
    assert transports[0].connect_calls == 1
    assert transports[1].connect_calls == 1
    assert "Connect attempt 1 failed" in caplog.text


def test_is_dot_advertisement_reaches_the_package() -> None:
    assert is_dot_advertisement("FM DOT", ())
    assert not is_dot_advertisement("FM DASH", ())


async def test_client_works_through_capture_transport(tmp_path: Path) -> None:
    inner = FakeTransport()
    with common.CaptureWriter(tmp_path / "capture.jsonl") as writer:
        async with FlitsmeisterDotClient(common.CaptureTransport(inner, writer)):
            pass
    assert inner.disconnect_calls == 1


def test_drive_needs_confirmation(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        drive_dot_client.config_from_args(
            ["--controls", "--config", str(tmp_path / "none.json")]
        )


def test_drive_rejects_invalid_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "local.json"
    path.write_text("not json")
    with pytest.raises(SystemExit) as exc_info:
        drive_dot_client.config_from_args(["--config", str(path)])
    assert exc_info.value.code == 2
    assert "local.json is not valid JSON" in capsys.readouterr().err


def test_drive_merges_config(tmp_path: Path) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"proxy": "proxy.local", "address": "AA"}')
    config = drive_dot_client.config_from_args(
        ["--config", str(path), "--address", "BB", "--duration", "1"]
    )
    assert config.proxy == "proxy.local"
    assert config.address == "BB"
    assert config.duration == 1
    assert not config.controls


def _run_config(**changes: object) -> drive_dot_client.RunConfig:
    values: dict[str, object] = {
        "proxy": None,
        "noise_psk": None,
        "address": None,
        "output": None,
        "scan_seconds": 0.0,
        "duration": 0.0,
        "pause_seconds": 0.0,
        "controls": False,
    }
    values.update(changes)
    return drive_dot_client.RunConfig(**values)  # type: ignore[arg-type]


async def test_drive_read_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = FakeTransport()
    await drive_dot_client.run(_run_config(), transport)
    assert transport.writes == []
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(READ_CHARACTERISTICS)
    first = json.loads(lines[0])
    assert first["characteristic"] == BATTERY_LEVEL_CHARACTERISTIC_UUID
    assert first["state"]["battery_level"] == 100


async def test_drive_controls() -> None:
    transport = FakeTransport()
    await drive_dot_client.run(_run_config(controls=True), transport)
    writes = transport.writes
    assert animations.startup().to_bytes() in writes
    assert animations.speed_trap().to_bytes() in writes
    assert animations.fade_out().to_bytes() in writes
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
    assert animations.brightness_sample().to_bytes() in writes
    assert animations.orientation_sample().to_bytes() in writes
    assert animations.fade_out_without_cut_off().to_bytes() in writes
    assert bytes((Volume.SILENT,)) in writes
    assert bytes((Volume.HARD,)) in writes
    assert bytes((Brightness.BRIGHTNESS_10,)) in writes
    assert bytes((LedOrientation.UPSIDE_DOWN,)) in writes
    assert transport.read_characteristics.count(BRIGHTNESS_CHARACTERISTIC_UUID) == 2
    assert transport.read_characteristics.count(LED_ROTATION_CHARACTERISTIC_UUID) == 2


def test_drive_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def failing(_config: drive_dot_client.RunConfig) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("no adapter")

    monkeypatch.setattr(drive_dot_client, "connect_and_run", failing)
    assert drive_dot_client.main(["--config", str(tmp_path / "none.json")]) == 1
    assert "no adapter" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_make_transport_uses_the_habluetooth_wrapper_for_a_proxy() -> None:
    device = BLEDevice("AA:BB:CC:DD:EE:FF", "FM DOT", {})
    local = common.make_transport(device, None)
    proxied = common.make_transport(device, "10.0.0.2")
    assert local._client_class is not habluetooth.HaBleakClientWrapper
    assert proxied._client_class is habluetooth.HaBleakClientWrapper
