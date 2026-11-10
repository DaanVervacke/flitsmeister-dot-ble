import asyncio
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from flitsmeister_dot_ble import (
    DotAnimation,
    DotSound,
    FlitsmeisterDotClient,
    animations,
)
from flitsmeister_dot_ble.const import (
    BATTERY_CHARGING_CHARACTERISTIC_UUID,
    BRIGHTNESS_CHARACTERISTIC_UUID,
    BUTTON_EVENTS_CHARACTERISTIC_UUID,
    LED_ROTATION_CHARACTERISTIC_UUID,
    MOTION_CHARACTERISTIC_UUID,
    SPEECH_LANGUAGE_CHARACTERISTIC_UUID,
)
from scripts import _dot_common as common
from scripts import live_validate
from scripts.live_validate import CheckResult, Outcome

from .helpers import FakeTransport

BUTTON_BYTES = {"RED": (b"\x01\x00", b"\x02\x00"), "BLUE": (b"\x00\x01", b"\x00\x02")}


class EchoTransport(FakeTransport):
    """Fake transport that reads back the written settings."""

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        await super().write_gatt_char(characteristic, data, response)
        if characteristic in {
            BRIGHTNESS_CHARACTERISTIC_UUID,
            LED_ROTATION_CHARACTERISTIC_UUID,
        }:
            self.reads[characteristic] = data


class FakeConsole:
    """Console that answers every question and acts out every instruction."""

    def __init__(
        self,
        transport: FakeTransport,
        answer: Outcome = Outcome.PASS,
        act: bool = True,
    ) -> None:
        self.transport = transport
        self.answer = answer
        self.act = act
        self.messages: list[str] = []
        self.questions: list[str] = []
        self.pauses: list[str] = []

    def say(self, message: str) -> None:
        self.messages.append(message)

    async def instruct(self, message: str) -> None:
        self.say(message)
        if self.act:
            self._act(message)
        await asyncio.sleep(0)

    def _act(self, message: str) -> None:
        transport = self.transport
        loop = asyncio.get_running_loop()
        for label, (pushed, released) in BUTTON_BYTES.items():
            if message.startswith(f"Short press the {label}"):
                transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, pushed)
                transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, released)
            if message.startswith(f"Hold the {label}"):
                transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, pushed)
                loop.call_later(
                    0.15,
                    transport.notify,
                    BUTTON_EVENTS_CHARACTERISTIC_UUID,
                    released,
                )
        if message.startswith("Plug the USB"):
            transport.notify(BATTERY_CHARGING_CHARACTERISTIC_UUID, b"\x00\x00\x01")
        if message.startswith("Unplug the USB"):
            transport.notify(BATTERY_CHARGING_CHARACTERISTIC_UUID, b"\x00\x00\x00")
        if message.startswith("Leave the DOT"):
            transport.notify(MOTION_CHARACTERISTIC_UUID, b"\x00")
        if message.startswith("Pick up the DOT"):
            transport.notify(MOTION_CHARACTERISTIC_UUID, b"\x01")
        if message.startswith("Switch the DOT off"):
            transport.drop()

    async def ask(self, question: str) -> tuple[Outcome, str]:
        self.questions.append(question)
        await asyncio.sleep(0)
        note = "" if self.answer is Outcome.PASS else "nothing happened"
        return self.answer, note

    async def pause(self, message: str) -> None:
        self.pauses.append(message)
        await asyncio.sleep(0)


def _config(**changes: object) -> live_validate.RunConfig:
    values: dict[str, object] = {
        "address": None,
        "output": None,
        "report": Path("report.json"),
        "scan_seconds": 0.0,
        "sections": live_validate.SECTIONS,
        "event_seconds": 2.0,
        "motion_seconds": 2.0,
        "reconnect_seconds": 2.0,
        "pause_seconds": 0.0,
        "verbose": False,
    }
    values.update(changes)
    return live_validate.RunConfig(**values)  # type: ignore[arg-type]


def _transport(inner: FakeTransport) -> live_validate.CountingTransport:
    return live_validate.CountingTransport(inner, common.CaptureWriter(None))


@pytest.fixture(autouse=True)
def _fast_long_press(monkeypatch: pytest.MonkeyPatch) -> None:
    original = FlitsmeisterDotClient

    def client(*args: object, **kwargs: object) -> object:
        kwargs.setdefault("long_press_seconds", 0.05)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(live_validate, "FlitsmeisterDotClient", client)
    monkeypatch.setattr(live_validate, "RECONNECT_RETRY_SECONDS", 0.01)


async def test_full_run_passes_on_a_well_behaved_device() -> None:
    inner = EchoTransport()
    console = FakeConsole(inner)
    results = await live_validate.validate(_config(), _transport(inner), console)
    failed = [result for result in results if result.outcome is not Outcome.PASS]
    assert failed == []
    sections = {result.section for result in results}
    assert sections == {"connect", "restore", *live_validate.SECTIONS}
    assert console.pauses == ["Switch the DOT on again or bring it back in range."]
    assert any("custom green" in question for question in console.questions)


async def test_full_run_covers_every_sound_and_restores_settings() -> None:
    inner = EchoTransport()
    await live_validate.validate(
        _config(sections=("sounds",)), _transport(inner), FakeConsole(inner)
    )
    played = {write[6] for write in inner.writes if len(write) == 10}
    assert {int(sound) for sound in DotSound} <= played
    assert inner.writes[-4:-1] == [b"\x64", b"\x00", b"\x02"]


async def test_sounds_use_the_language_the_dot_reports() -> None:
    inner = EchoTransport()
    console = FakeConsole(inner)
    await live_validate.validate(
        _config(sections=("sounds",)), _transport(inner), console
    )
    assert any("Dutch announcement for 'roadworks'" in q for q in console.questions)


async def test_unknown_language_is_called_the_installed_voice() -> None:
    inner = EchoTransport()
    inner.reads[SPEECH_LANGUAGE_CHARACTERISTIC_UUID] = b"\x09"
    console = FakeConsole(inner)
    results = await live_validate.validate(
        _config(sections=("info", "sounds")), _transport(inner), console
    )
    assert any("installed announcement" in q for q in console.questions)
    failed = {result.name for result in results if result.outcome is Outcome.FAIL}
    assert failed == {"speech_language read"}


async def test_errors_section_checks_out_of_range_progress() -> None:
    inner = EchoTransport()
    results = await live_validate.validate(
        _config(sections=("errors",)), _transport(inner), FakeConsole(inner)
    )
    outcomes = {result.name: result.outcome for result in results}
    assert outcomes["progress 1.5 clamps to 8 LEDs"] is Outcome.PASS
    assert outcomes["progress -0.5 clamps to 1 LEDs"] is Outcome.PASS


class RetryOnceConsole(FakeConsole):
    """Console that asks for a retry the first time, then passes."""

    def __init__(self, transport: FakeTransport) -> None:
        super().__init__(transport)
        self.retried = False

    async def ask(self, question: str) -> tuple[Outcome, str]:
        self.questions.append(question)
        await asyncio.sleep(0)
        if self.retried:
            return Outcome.PASS, ""
        self.retried = True
        return Outcome.RETRY, ""


async def test_retry_runs_the_check_again() -> None:
    inner = EchoTransport()
    console = RetryOnceConsole(inner)
    validator = live_validate.Validator(
        FlitsmeisterDotClient(_transport(inner), long_press_seconds=0.05),
        _transport(inner),
        live_validate.Monitor(),
        console,
        _config(),
    )
    runs = 0

    async def action() -> None:
        nonlocal runs
        await asyncio.sleep(0)
        runs += 1

    await validator.observe("twice", action, "ok?")
    assert runs == 2
    assert console.questions == ["ok?", "ok?"]
    assert validator.results == [CheckResult("", "twice", Outcome.PASS)]


async def test_failed_answers_and_missing_events_are_recorded() -> None:
    inner = EchoTransport()
    console = FakeConsole(inner, answer=Outcome.FAIL, act=False)
    config = _config(
        sections=("info", "buttons", "sensors", "reconnect"),
        event_seconds=0.01,
        motion_seconds=0.01,
        reconnect_seconds=0.01,
    )
    results = await live_validate.validate(config, _transport(inner), console)
    failed = {
        (result.section, result.name)
        for result in results
        if result.outcome is Outcome.FAIL
    }
    assert ("info", "device information looks right") in failed
    assert ("buttons", "RED short: SHORT_PRESS") in failed
    assert ("buttons", "BLUE long: LONG_PRESS") in failed
    assert ("sensors", "consuming after unplug") in failed
    assert ("sensors", "motion DRIVING when moved") in failed
    assert ("reconnect", "connection_lost_callback called") in failed
    notes = {result.detail for result in results if result.name.startswith("device")}
    assert notes == {"nothing happened"}


async def test_write_errors_fail_the_check_without_stopping() -> None:
    inner = EchoTransport()
    console = FakeConsole(inner)
    validator = live_validate.Validator(
        FlitsmeisterDotClient(_transport(inner), long_press_seconds=0.05),
        _transport(inner),
        live_validate.Monitor(),
        console,
        _config(),
    )
    validator.section = "manual"

    async def boom() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("boom")

    await validator.observe("broken", boom, "unused")
    await validator.raises("wrong error", ValueError, boom)
    await validator.raises("no error", ValueError, live_validate._nothing)
    assert [result.detail for result in validator.results] == [
        "RuntimeError: boom",
        "raised RuntimeError: boom",
        "did not raise ValueError",
    ]
    assert console.questions == []


async def test_reconnect_gives_up_after_the_deadline() -> None:
    inner = EchoTransport()
    inner.fail_connect = OSError("gone")
    console = FakeConsole(inner)
    validator = live_validate.Validator(
        FlitsmeisterDotClient(_transport(inner), long_press_seconds=0.05),
        _transport(inner),
        live_validate.Monitor(),
        console,
        _config(reconnect_seconds=0.0),
    )
    assert not await validator.ensure_ready()
    assert validator.results[-1].name == "reconnect before the section"


async def test_section_crash_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def crash(_v: live_validate.Validator) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("crash")

    monkeypatch.setitem(live_validate.SECTION_CHECKS, "info", crash)
    inner = EchoTransport()
    results = await live_validate.validate(
        _config(sections=("info",)), _transport(inner), FakeConsole(inner)
    )
    assert (
        CheckResult("info", "section stopped", Outcome.FAIL, "RuntimeError('crash')")
        in results
    )


def test_summary_and_report(tmp_path: Path) -> None:
    results = [
        CheckResult("info", "a", Outcome.PASS),
        CheckResult("info", "b", Outcome.FAIL, "why"),
        CheckResult("sounds", "c", Outcome.SKIP),
    ]
    assert live_validate.summary(results) == (
        "1 passed, 1 failed, 1 skipped\nFAIL info: b why"
    )
    path = tmp_path / "out" / "report.json"
    live_validate.write_report(path, _config(sections=("info",)), results)
    report = json.loads(path.read_text())
    assert report["sections"] == ["info"]
    assert report["results"][1] == {
        "section": "info",
        "name": "b",
        "outcome": "fail",
        "detail": "why",
    }


def test_config_needs_the_config_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        live_validate.config_from_args(["--config", str(tmp_path / "none.json")])


def test_config_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "local.json"
    path.write_text("[]")
    with pytest.raises(SystemExit):
        live_validate.config_from_args(["--config", str(path)])


def test_config_keeps_section_order(tmp_path: Path) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"address": "AA"}')
    config = live_validate.config_from_args(
        ["--config", str(path), "--section", "errors", "--section", "info"]
    )
    assert config.address == "AA"
    assert config.sections == ("info", "errors")
    full = live_validate.config_from_args(["--config", str(path)])
    assert full.sections == live_validate.SECTIONS


async def test_terminal_console_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["maybe", "y", "r", "s", "n", " too dim "])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    console = live_validate.TerminalConsole()
    assert await console.ask("ok?") == (Outcome.PASS, "")
    assert await console.ask("ok?") == (Outcome.RETRY, "")
    assert await console.ask("ok?") == (Outcome.SKIP, "")
    assert await console.ask("ok?") == (Outcome.FAIL, "too dim")
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    await console.pause("wait")
    await console.instruct("hello")
    assert ">>> hello" in capsys.readouterr().out


async def test_file_console_waits_for_matching_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live_validate, "BRIDGE_POLL_SECONDS", 0.001)
    folder = tmp_path / "bridge"
    console = live_validate.FileConsole(folder)
    answers = iter(
        [
            None,
            "{broken",
            {"id": 99, "answer": "y"},
            {"id": 1, "answer": "maybe"},
            {"id": 2, "answer": "n", "note": " too dim "},
            {"id": 3, "answer": "y"},
            {"id": 4, "answer": "r"},
            {"id": 5, "answer": "s"},
            {"id": 6, "answer": "done"},
            {"id": 7, "answer": "done"},
        ]
    )

    async def respond() -> None:
        for answer in answers:
            question = folder / "question.json"
            for _ in range(1000):
                if question.exists():
                    break
                await asyncio.sleep(0.001)
            path = folder / "answer.json"
            if answer is None:
                path.unlink(missing_ok=True)
            elif isinstance(answer, str):
                path.write_text(answer)
            else:
                path.write_text(json.dumps(answer))
            await asyncio.sleep(0.01)

    responder = asyncio.create_task(respond())
    assert await console.ask("ok?") == (Outcome.FAIL, "too dim")
    assert await console.ask("ok?") == (Outcome.PASS, "")
    assert await console.ask("ok?") == (Outcome.RETRY, "")
    assert await console.ask("ok?") == (Outcome.SKIP, "")
    await console.pause("wait")
    await console.instruct("press it")
    await responder
    log = (folder / "log.txt").read_text()
    assert log.startswith("ASK: ok?\n")
    assert log.endswith("PAUSE: wait\nINSTRUCT: press it\n")
    assert not (folder / "question.json").exists()


def test_config_reads_the_proxy_from_the_file_and_the_flags(tmp_path: Path) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"address": "AA", "proxy": "10.0.0.2", "noise_psk": "key"}')
    config = live_validate.config_from_args(["--config", str(path)])
    assert (config.proxy, config.noise_psk) == ("10.0.0.2", "key")
    flagged = live_validate.config_from_args(
        ["--config", str(path), "--proxy", "10.0.0.3", "--noise-psk", "other"]
    )
    assert (flagged.proxy, flagged.noise_psk) == ("10.0.0.3", "other")


def test_config_reads_the_bridge_folder(tmp_path: Path) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"address": "AA"}')
    config = live_validate.config_from_args(
        ["--config", str(path), "--bridge", str(tmp_path / "b")]
    )
    assert config.bridge == tmp_path / "b"


def test_main_exit_code_follows_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"address": "AA"}')
    report = tmp_path / "report.json"
    outcome = Outcome.PASS

    async def fake(
        _config: live_validate.RunConfig, _console: object
    ) -> list[CheckResult]:
        await asyncio.sleep(0)
        return [CheckResult("info", "a", outcome)]

    monkeypatch.setattr(live_validate, "connect_and_validate", fake)
    argv = ["--config", str(path), "--report", str(report)]
    assert live_validate.main(argv) == 0
    assert report.exists()
    outcome = Outcome.FAIL
    assert live_validate.main(argv) == 1


def test_main_reports_a_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "local.json"
    path.write_text('{"address": "AA"}')

    async def failing(_config: object, _console: object) -> list[CheckResult]:
        await asyncio.sleep(0)
        raise RuntimeError("no adapter")

    monkeypatch.setattr(live_validate, "connect_and_validate", failing)
    assert live_validate.main(["--config", str(path)]) == 1
    assert "no adapter" in caplog.text


DESCRIBED_PRESETS: list[Callable[..., DotAnimation]] = [
    animations.startup,
    animations.fade_out_without_cut_off,
    animations.lane_closure,
    *(documented for _name, _builder, documented in live_validate.RATEABLE_PRESETS),
    *(preset for _name, preset in live_validate.PLAIN_PRESETS),
]


@pytest.mark.parametrize(
    "preset", DESCRIBED_PRESETS, ids=lambda preset: preset.__name__
)
def test_every_prompted_preset_describes_what_the_dot_does(
    preset: Callable[..., DotAnimation],
) -> None:
    description = live_validate._describe(preset)
    assert description.startswith(("The ", "All ")), description
    assert description.endswith("."), description


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        ("y", Outcome.PASS),
        (" YES ", Outcome.PASS),
        ("n", Outcome.FAIL),
        ("retry", Outcome.RETRY),
        ("s", Outcome.SKIP),
        ("maybe", None),
    ],
)
def test_parse_answer(answer: str, outcome: Outcome | None) -> None:
    assert live_validate.parse_answer(answer) is outcome
