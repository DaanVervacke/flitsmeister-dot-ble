"""Validate the library against a real DOT, one check at a time.

The script walks every public function of the library on the device.
Checks that need your eyes, ears or hands ask a yes or no question.
Each run writes a JSON report and records the traffic with the serial
redacted. ``--section`` reruns one section. Repeat it to rerun more.
"""

import argparse
import asyncio
import inspect
import json
import logging
import math
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Protocol

from flitsmeister_dot_ble import (
    Brightness,
    ButtonAction,
    ChargingState,
    ConnectionStatus,
    DotAnimation,
    DotAnimationType,
    DotButton,
    DotColor,
    DotConnectionError,
    DotEnd,
    DotError,
    DotNotReadyError,
    DotSound,
    DotState,
    DotUpdate,
    DotValidationError,
    FlitsmeisterDotClient,
    LedOrientation,
    MotionStatus,
    Volume,
    __version__,
    animations,
)
from flitsmeister_dot_ble.const import (
    BATTERY_CHARGING_CHARACTERISTIC_UUID,
    MOTION_CHARACTERISTIC_UUID,
    READ_CHARACTERISTICS,
)
from flitsmeister_dot_ble.transport_types import (
    BleTransport,
    DisconnectedCallback,
)

from scripts import _dot_common as common
from scripts.drive_dot_client import DEFAULT_CONFIG

_LOGGER = logging.getLogger(__name__)

DEFAULT_OUTPUT = Path("tests/fixtures/dot_live_validation.jsonl")
DEFAULT_REPORT = Path("reports/live_validation_report.json")
PROGRESS_FRACTIONS = (0.0, 0.25, 0.5, 0.75, 1.0)
PROGRESS_LEDS = "1, 2, 4, 6 and 8"
CUSTOM_COLOR = 0xFF00FF00
ORIENTATION_PROBE = animations.progress(color=DotColor.SUCCESS, fraction=0.25)
RESTORE_VOLUME = Volume.NORMAL
SOUND_CHECK_VOLUME = Volume.NORMAL
SOUND_CHECK_LEDS = 2
UUID_STRING_LENGTH = 36
LONG_HOLD_SECONDS = 3
LOST_CALLBACK_GRACE_SECONDS = 1.0
RECONNECT_RETRY_SECONDS = 2.0
BRIDGE_POLL_SECONDS = 0.2
VOLUME_HINTS = {
    Volume.SILENT: "silent",
    Volume.LOW: "quiet",
    Volume.NORMAL: "at a normal level",
    Volume.HARD: "loud",
}


class Outcome(StrEnum):
    """Result of one check.

    ``RETRY`` is only an answer to a question. It makes the check run again
    and never ends up in the results.
    """

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    SKIP = "skip"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One finished check."""

    section: str
    name: str
    outcome: Outcome
    detail: str = ""


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Settings for one validation run."""

    address: str | None
    output: Path | None
    report: Path
    scan_seconds: float
    sections: tuple[str, ...]
    event_seconds: float
    motion_seconds: float
    reconnect_seconds: float
    pause_seconds: float
    verbose: bool
    bridge: Path | None = None
    proxy: str | None = None
    noise_psk: str | None = None


class Console(Protocol):
    """Talks to the person running the checks."""

    def say(self, message: str) -> None: ...

    async def instruct(self, message: str) -> None: ...

    async def ask(self, question: str) -> tuple[Outcome, str]: ...

    async def pause(self, message: str) -> None: ...


ANSWERS = {
    "y": Outcome.PASS,
    "yes": Outcome.PASS,
    "n": Outcome.FAIL,
    "no": Outcome.FAIL,
    "r": Outcome.RETRY,
    "retry": Outcome.RETRY,
    "s": Outcome.SKIP,
    "skip": Outcome.SKIP,
}


def parse_answer(answer: str) -> Outcome | None:
    """Return the outcome a typed answer stands for, or None when unknown."""
    return ANSWERS.get(answer.strip().lower())


class TerminalConsole:
    """Console on stdin and stdout."""

    def say(self, message: str) -> None:
        sys.stdout.write(f"\n>>> {message}\n")
        sys.stdout.flush()

    async def instruct(self, message: str) -> None:
        self.say(message)
        await asyncio.sleep(0)

    async def ask(self, question: str) -> tuple[Outcome, str]:
        while True:
            answer = await asyncio.to_thread(input, f"\n??? {question} [y/n/r/s] ")
            outcome = parse_answer(answer)
            if outcome is None:
                continue
            if outcome is not Outcome.FAIL:
                return outcome, ""
            note = await asyncio.to_thread(input, "    What happened instead? ")
            return outcome, note.strip()

    async def pause(self, message: str) -> None:
        await asyncio.to_thread(input, f"\n>>> {message} Press Enter when done. ")


class FileConsole:
    """Console that talks through files in a folder, for a driver program.

    Messages are appended to ``log.txt``. A question, an instruction or a
    pause is written to ``question.json`` and the console waits for
    ``answer.json`` with the same ``id``. A question takes y, n, r or s with
    an optional note. An instruction or a pause takes done. An instruction
    waits for done so the person acts before the check starts waiting.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        for name in ("log.txt", "question.json", "answer.json"):
            (self.folder / name).unlink(missing_ok=True)
        self._next_id = 0

    def _write(self, name: str, payload: dict[str, object]) -> None:
        self._next_id += 1
        payload["id"] = self._next_id
        staging = self.folder / f"{name}.tmp"
        staging.write_text(json.dumps(payload), encoding="utf-8")
        staging.replace(self.folder / name)

    def say(self, message: str) -> None:
        with (self.folder / "log.txt").open("a", encoding="utf-8") as log:
            log.write(f"{message}\n")

    async def instruct(self, message: str) -> None:
        await self._answer("instruct", message)

    async def _answer(self, kind: str, text: str) -> tuple[str, str]:
        self.say(f"{kind.upper()}: {text}")
        self._write("question.json", {"kind": kind, "text": text})
        wanted = self._next_id
        path = self.folder / "answer.json"
        while True:
            await asyncio.sleep(BRIDGE_POLL_SECONDS)
            try:
                answer = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError, json.JSONDecodeError:
                continue
            if answer.get("id") != wanted:
                continue
            path.unlink(missing_ok=True)
            (self.folder / "question.json").unlink(missing_ok=True)
            return str(answer.get("answer", "")), str(answer.get("note", ""))

    async def ask(self, question: str) -> tuple[Outcome, str]:
        while True:
            answer, note = await self._answer("ask", question)
            outcome = parse_answer(answer)
            if outcome is None:
                continue
            return outcome, note.strip() if outcome is Outcome.FAIL else ""

    async def pause(self, message: str) -> None:
        await self._answer("pause", message)


class CountingTransport(common.CaptureTransport):
    """Capture transport that also counts connects and writes."""

    def __init__(self, transport: BleTransport, capture: common.CaptureWriter) -> None:
        super().__init__(transport, capture)
        self.connects = 0
        self.writes = 0

    async def connect(self, disconnected_callback: DisconnectedCallback) -> None:
        """Count and forward one connect."""
        self.connects += 1
        await super().connect(disconnected_callback)

    async def write_gatt_char(
        self, characteristic: str, data: bytes, response: bool = False
    ) -> None:
        """Count and forward one write."""
        self.writes += 1
        await super().write_gatt_char(characteristic, data, response=response)


class Monitor:
    """Collect the updates and lost sessions the client reports."""

    def __init__(self) -> None:
        self.updates: list[DotUpdate] = []
        self.lost: list[Exception] = []
        self._changed = asyncio.Event()

    def on_update(self, update: DotUpdate) -> None:
        """Store one update."""
        self.updates.append(update)
        self._changed.set()

    def on_lost(self, error: Exception) -> None:
        """Store the error that ended a session."""
        self.lost.append(error)
        self._changed.set()

    def mark(self) -> int:
        """Return a position to look for new updates from."""
        return len(self.updates)

    def buttons_since(self, mark: int, button: DotButton) -> list[ButtonAction]:
        """Return the actions of ``button`` reported after ``mark``."""
        return [
            update.button.action
            for update in self.updates[mark:]
            if update.button is not None and update.button.button is button
        ]

    def updates_since(self, mark: int, characteristic: str) -> list[DotUpdate]:
        """Return the updates of one characteristic reported after ``mark``."""
        return [
            update
            for update in self.updates[mark:]
            if update.characteristic == characteristic and update.button is None
        ]

    async def wait_for_action(
        self, mark: int, button: DotButton, action: ButtonAction, seconds: float
    ) -> bool:
        """Wait until ``button`` reported ``action`` after ``mark``."""
        return await self.wait_for(
            lambda: action in self.buttons_since(mark, button), seconds
        )

    async def wait_for(self, predicate: Callable[[], bool], seconds: float) -> bool:
        """Wait until ``predicate`` holds or ``seconds`` passed."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while not predicate():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            self._changed.clear()
            try:
                async with asyncio.timeout(remaining):
                    await self._changed.wait()
            except TimeoutError:
                return predicate()
        return True


class Validator:
    """Run checks against one client and keep the results."""

    def __init__(
        self,
        client: FlitsmeisterDotClient,
        transport: CountingTransport,
        monitor: Monitor,
        console: Console,
        config: RunConfig,
    ) -> None:
        self.client = client
        self.transport = transport
        self.monitor = monitor
        self.console = console
        self.config = config
        self.results: list[CheckResult] = []
        self.section = ""

    def record(self, name: str, outcome: Outcome, detail: str = "") -> None:
        """Store one result and show it."""
        self.results.append(CheckResult(self.section, name, outcome, detail))
        suffix = f" ({detail})" if detail else ""
        self.console.say(f"[{outcome.value.upper()}] {self.section}: {name}{suffix}")

    def expect(self, name: str, condition: bool, detail: str = "") -> bool:
        """Record a check the script decides on its own."""
        self.record(name, Outcome.PASS if condition else Outcome.FAIL, detail)
        return condition

    async def attempt(self, name: str, action: Callable[[], Awaitable[object]]) -> bool:
        """Run ``action`` and record a failure when it raises."""
        try:
            await action()
        except Exception as err:  # noqa: BLE001
            self.record(name, Outcome.FAIL, f"{type(err).__name__}: {err}")
            return False
        return True

    async def observe(
        self, name: str, action: Callable[[], Awaitable[object]], question: str
    ) -> None:
        """Run ``action`` and ask whether the device did the right thing.

        A retry answer runs ``action`` again and asks the same question.
        """
        while True:
            if not await self.attempt(name, action):
                return
            outcome, note = await self.console.ask(question)
            if outcome is not Outcome.RETRY:
                self.record(name, outcome, note)
                return

    async def raises(
        self,
        name: str,
        error_type: type[Exception],
        action: Callable[[], Awaitable[object]],
    ) -> None:
        """Record whether ``action`` raises ``error_type``."""
        try:
            await action()
        except error_type:
            self.record(name, Outcome.PASS)
        except Exception as err:  # noqa: BLE001
            self.record(name, Outcome.FAIL, f"raised {type(err).__name__}: {err}")
        else:
            self.record(name, Outcome.FAIL, f"did not raise {error_type.__name__}")

    async def ensure_ready(self) -> bool:
        """Reconnect when an earlier check lost the session."""
        if self.client.ready:
            return True
        self.console.say("The DOT is not connected, reconnecting.")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.reconnect_seconds
        while True:
            try:
                await self.client.connect()
            except DotError as err:
                if loop.time() >= deadline:
                    self.record("reconnect before the section", Outcome.FAIL, str(err))
                    return False
                await asyncio.sleep(RECONNECT_RETRY_SECONDS)
            else:
                return True


async def _nothing() -> None:
    """Do nothing, for questions about values already read."""


def _describe(builder: Callable[..., DotAnimation]) -> str:
    """Return the sentence of a preset docstring that says what the DOT does."""
    paragraphs = (inspect.getdoc(builder) or "").split("\n\n")
    text = paragraphs[1] if len(paragraphs) > 1 else paragraphs[0]
    return " ".join(text.split())


def _sequence(
    client: FlitsmeisterDotClient, steps: Sequence[DotAnimation], pause: float
) -> Callable[[], Awaitable[None]]:
    async def play() -> None:
        for index, step in enumerate(steps):
            if index:
                await asyncio.sleep(pause)
            await client.play_animation(step)

    return play


def _sound_label(sound: DotSound, language: str) -> str:
    words = sound.name.split("_", 1)[1].lower().replace("_", " ")
    if sound.name.startswith("SPEECH_"):
        return f"the {language} announcement for '{words}'"
    return f"the '{words}' sound effect"


def _language_name(state: DotState) -> str:
    if state.speech_language is None:
        return "installed"
    return state.speech_language.name.title()


async def check_info(v: Validator) -> None:
    """Check the session flags and every value read while connecting."""
    client = v.client
    v.expect("status is READY", client.status is ConnectionStatus.READY)
    v.expect("connected is True", client.connected)
    v.expect("ready is True", client.ready)
    state = client.state
    level = state.battery_level
    v.expect("battery level read", level is not None and 0 <= level <= 100, str(level))
    for name, value in (
        ("charging_state", state.charging_state),
        ("motion_status", state.motion_status),
        ("manufacturer_name", state.manufacturer_name),
        ("model_number", state.model_number),
        ("serial_raw", state.serial_raw),
        ("serial_uuid", state.serial_uuid),
        ("firmware_revision", state.firmware_revision),
        ("software_revision", state.software_revision),
        ("speech_language", state.speech_language),
    ):
        found = value is not None
        v.expect(f"{name} read", found, "" if found else "missing")
    uuid = state.serial_uuid or ""
    v.expect(
        "serial uuid is an uppercase UUID",
        len(uuid) == UUID_STRING_LENGTH and uuid == uuid.upper(),
    )
    seen = {update.characteristic for update in v.monitor.updates}
    v.expect(
        "update callback saw every read",
        set(READ_CHARACTERISTICS) <= seen,
        f"missing {sorted(set(READ_CHARACTERISTICS) - seen)}",
    )
    charging = state.charging_state.name if state.charging_state is not None else None
    await v.observe(
        "battery and charging match",
        _nothing,
        f"Battery {level}% and charging state {charging}. Does that match the"
        " DOT (cable in or out)?",
    )
    await v.observe(
        "device information looks right",
        _nothing,
        f"Manufacturer {state.manufacturer_name!r}, model {state.model_number!r},"
        f" firmware {state.firmware_revision!r}, software"
        f" {state.software_revision!r}. Does that look right?",
    )
    await v.observe(
        "speech language looks right",
        _nothing,
        f"The DOT reports the {_language_name(state)} voice, voice byte"
        f" {state.speech_voice_raw}. Is that the voice you installed in the app?",
    )
    if await v.attempt("read_settings", client.read_settings):
        state = client.state
        v.expect("read_settings filled brightness", state.brightness is not None)
        v.expect("read_settings filled orientation", state.led_orientation is not None)
        brightness = state.brightness.value if state.brightness is not None else None
        orientation = (
            state.led_orientation.name if state.led_orientation is not None else None
        )
        await v.observe(
            "settings match the app",
            _nothing,
            f"Brightness {brightness}% and orientation {orientation}. Does that"
            " match the settings in the Flitsmeister app?",
        )


async def check_settings(v: Validator) -> None:
    """Write every value of every setting and read back where possible."""
    client = v.client
    for volume in Volume:

        async def set_volume(volume: Volume = volume) -> None:
            await client.set_volume(volume)
            await client.play_animation(animations.reporting())

        await v.observe(
            f"set_volume {volume.name}",
            set_volume,
            f"Volume {volume.name}: was the confirm beep {VOLUME_HINTS[volume]}?",
        )
        v.expect(f"state volume is {volume.name}", client.state.volume is volume)
    await v.attempt(
        f"set_volume {RESTORE_VOLUME.name}", partial(client.set_volume, RESTORE_VOLUME)
    )
    for brightness in Brightness:

        async def set_brightness(brightness: Brightness = brightness) -> None:
            await client.set_brightness(brightness)
            await client.play_animation(animations.fade_out())
            await client.play_animation(animations.brightness_sample())

        await v.observe(
            f"set_brightness {brightness.value}",
            set_brightness,
            f"Did all 8 LEDs light white at about {brightness.value}% brightness?",
        )
        v.expect(
            f"brightness read back {brightness.value}",
            client.state.brightness is brightness,
            str(client.state.brightness),
        )
    for orientation in LedOrientation:

        async def set_orientation(orientation: LedOrientation = orientation) -> None:
            await client.set_led_orientation(orientation)
            await client.play_animation(animations.fade_out())
            await client.play_animation(ORIENTATION_PROBE)

        side = (
            "the side away from the USB-C port"
            if orientation is LedOrientation.NORMAL
            else "the USB-C side"
        )
        question = f"Did 2 green LEDs light on {side}?"
        await v.observe(
            f"set_led_orientation {orientation.name}", set_orientation, question
        )
        v.expect(
            f"orientation read back {orientation.name}",
            client.state.led_orientation is orientation,
            str(client.state.led_orientation),
        )
    await v.attempt(
        "set_led_orientation NORMAL after the samples",
        partial(client.set_led_orientation, LedOrientation.NORMAL),
    )


AnimationCheck = tuple[str, Callable[[], Awaitable[None]], str]
RATEABLE_PRESETS: tuple[
    tuple[str, Callable[..., DotAnimation], Callable[..., DotAnimation]], ...
] = (
    ("speed_trap", animations.speed_trap, animations.speed_trap),
    ("speed_cam", animations.speed_cam, animations.speed_cam),
    ("traffic_camera", animations.traffic_camera, animations.traffic_camera),
    (
        "avg_speed_check_start",
        animations.avg_speed_check_start,
        animations.avg_speed_check_start,
    ),
    ("police_hotspot", animations.police_hotspot, animations.police_hotspot),
    ("roadworks", animations.roadworks, animations.roadworks),
    (
        "incident ACCIDENT",
        partial(animations.incident, speech=DotSound.SPEECH_ACCIDENT),
        animations.incident,
    ),
)
PLAIN_PRESETS: tuple[tuple[str, Callable[[], DotAnimation]], ...] = (
    ("avg_speed_check_end", animations.avg_speed_check_end),
    ("traffic_jam_start", animations.traffic_jam_start),
    ("traffic_jam_end", animations.traffic_jam_end),
    ("ambulance", animations.ambulance),
    ("fire_truck", animations.fire_truck),
    ("police", animations.police),
    ("emergency_vehicle", animations.emergency_vehicle),
    ("railway_crossing", animations.railway_crossing),
    ("wrong_way_driving", animations.wrong_way_driving),
    ("wrong_way_driver", animations.wrong_way_driver),
    ("reporting", animations.reporting),
    ("brightness_sample", animations.brightness_sample),
    ("orientation_sample", animations.orientation_sample),
    ("updating", animations.updating),
)
LANE_CLOSURE_SPEECH = (
    DotSound.SPEECH_LEFT_LANE_CLOSED,
    DotSound.SPEECH_LANE_CLOSED,
    DotSound.SPEECH_RIGHT_LANE_CLOSED,
)


def _single(
    client: FlitsmeisterDotClient, name: str, animation: DotAnimation, question: str
) -> AnimationCheck:
    return name, partial(client.play_animation, animation), question


def _fade_checks(client: FlitsmeisterDotClient, pause: float) -> list[AnimationCheck]:
    return [
        _single(
            client,
            "startup",
            animations.startup(),
            f"{_describe(animations.startup)} Right?",
        ),
        (
            "fade_out",
            _sequence(client, (animations.updating(), animations.fade_out()), pause),
            "A white wave started, then the LEDs went dark. Right?",
        ),
        (
            "fade_out_without_cut_off",
            _sequence(
                client,
                (animations.updating(), animations.fade_out_without_cut_off()),
                pause,
            ),
            (
                "A white wave started. "
                f"{_describe(animations.fade_out_without_cut_off)} Did that happen?"
            ),
        ),
    ]


def _rateable_checks(client: FlitsmeisterDotClient) -> list[AnimationCheck]:
    checks: list[AnimationCheck] = []
    for name, builder, documented in RATEABLE_PRESETS:
        description = _describe(documented)
        checks.append(
            _single(
                client,
                f"{name} rateable",
                builder(rateable=True),
                f"{description} Then press a button. Did it wait for your press"
                " and end on it?",
            )
        )
        checks.append(
            _single(
                client,
                f"{name} not rateable",
                builder(rateable=False),
                f"{description} Did it end by itself without a button press?",
            )
        )
    return checks


def _plain_checks(client: FlitsmeisterDotClient) -> list[AnimationCheck]:
    checks = [
        _single(client, name, preset(), f"{_describe(preset)} Did that happen?")
        for name, preset in PLAIN_PRESETS
    ]
    for speech in LANE_CLOSURE_SPEECH:
        words = speech.name.removeprefix("SPEECH_").lower().replace("_", " ")
        checks.append(
            _single(
                client,
                f"lane_closure {speech.name}",
                animations.lane_closure(speech=speech),
                f"{_describe(animations.lane_closure)} The speech says '{words}'."
                " Did that happen?",
            )
        )
    return checks


def _progress_checks(
    client: FlitsmeisterDotClient, pause: float
) -> list[AnimationCheck]:
    colors: list[tuple[str, int]] = [(color.name, color) for color in DotColor]
    colors.append((f"custom green {CUSTOM_COLOR:#010x}", CUSTOM_COLOR))
    checks: list[AnimationCheck] = []
    for label, color in colors:
        steps = [
            animations.progress(color=color, fraction=fraction)
            for fraction in PROGRESS_FRACTIONS
        ]
        checks.append(
            (
                f"progress {label}",
                _sequence(client, steps, pause),
                (
                    f"Did the ring fill from the top down in {label} with"
                    f" {PROGRESS_LEDS} LEDs, one step at a time?"
                ),
            )
        )
    checks.append(
        (
            "overspeed",
            _sequence(
                client,
                [animations.overspeed(fraction=f) for f in PROGRESS_FRACTIONS],
                pause,
            ),
            f"Did {PROGRESS_LEDS} red LEDs blink, with the reduce speed sound?",
        )
    )
    return checks


def _animation_checks(
    client: FlitsmeisterDotClient, pause: float
) -> list[AnimationCheck]:
    return [
        *_fade_checks(client, pause),
        *_rateable_checks(client),
        *_plain_checks(client),
        *_progress_checks(client, pause),
    ]


async def check_animations(v: Validator) -> None:
    """Play every preset in every variant."""
    for name, play, question in _animation_checks(v.client, v.config.pause_seconds):
        await v.observe(name, play, question)
    await v.attempt(
        "fade_out after animations",
        partial(v.client.play_animation, animations.fade_out()),
    )


async def check_sounds(v: Validator) -> None:
    """Play every sound once in the voice language the DOT reports."""
    client = v.client
    language = _language_name(client.state)
    await v.attempt(
        f"set_volume {SOUND_CHECK_VOLUME.name}",
        partial(client.set_volume, SOUND_CHECK_VOLUME),
    )
    for sound in DotSound:
        animation = DotAnimation(
            type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
            color=DotColor.WHITE,
            value=SOUND_CHECK_LEDS,
            primary_sound=sound,
            end=DotEnd.FADE_OUT,
            cut_off=True,
        )
        question = (
            "Did the ring breathe white without any sound?"
            if sound is DotSound.NO_AUDIO
            else f"Did you hear {_sound_label(sound, language)}?"
        )
        await v.observe(
            f"sound {sound.name}", partial(client.play_animation, animation), question
        )
    both = DotAnimation(
        type=DotAnimationType.MID_TO_OUTWARD_AND_BREATHE,
        color=DotColor.WHITE,
        value=SOUND_CHECK_LEDS,
        primary_sound=DotSound.SFX_CONFIRM,
        secondary_sound=DotSound.SPEECH_ROADWORKS,
        end=DotEnd.FADE_OUT,
        cut_off=True,
    )
    await v.observe(
        "primary then secondary sound",
        partial(client.play_animation, both),
        "Did you hear the confirm beep and then the roadworks announcement?",
    )


async def check_buttons(v: Validator) -> None:
    """Check the raw, short and long press events of both buttons."""
    monitor = v.monitor
    seconds = v.config.event_seconds
    for button in DotButton:
        label = button.value.upper()
        mark = monitor.mark()
        await v.console.instruct(f"Short press the {label} button once.")
        await monitor.wait_for_action(mark, button, ButtonAction.SHORT_PRESS, seconds)
        actions = monitor.buttons_since(mark, button)
        v.expect(f"{label} short: PUSHED", ButtonAction.PUSHED in actions, str(actions))
        v.expect(
            f"{label} short: RELEASED", ButtonAction.RELEASED in actions, str(actions)
        )
        v.expect(
            f"{label} short: SHORT_PRESS",
            ButtonAction.SHORT_PRESS in actions,
            str(actions),
        )
        v.expect(
            f"{label} short: no LONG_PRESS",
            ButtonAction.LONG_PRESS not in actions,
            str(actions),
        )
        mark = monitor.mark()
        await v.console.instruct(
            f"Hold the {label} button for {LONG_HOLD_SECONDS} seconds, then release it."
        )
        await monitor.wait_for_action(mark, button, ButtonAction.RELEASED, seconds)
        actions = monitor.buttons_since(mark, button)
        v.expect(
            f"{label} long: LONG_PRESS",
            ButtonAction.LONG_PRESS in actions,
            str(actions),
        )
        v.expect(
            f"{label} long: no SHORT_PRESS",
            ButtonAction.SHORT_PRESS not in actions,
            str(actions),
        )
        v.expect(
            f"{label} long: LONG_PRESS before RELEASED",
            ButtonAction.LONG_PRESS in actions
            and ButtonAction.RELEASED in actions
            and actions.index(ButtonAction.LONG_PRESS)
            < actions.index(ButtonAction.RELEASED),
            str(actions),
        )


async def _wait_for_value(
    v: Validator,
    name: str,
    instruction: str,
    characteristic: str,
    accepted: Callable[[DotUpdate], bool],
    seconds: float,
) -> None:
    mark = v.monitor.mark()
    await v.console.instruct(instruction)

    def seen() -> bool:
        return any(
            accepted(update) for update in v.monitor.updates_since(mark, characteristic)
        )

    await v.monitor.wait_for(seen, seconds)
    values = [
        update.payload.hex() for update in v.monitor.updates_since(mark, characteristic)
    ]
    v.expect(name, seen(), f"payloads {values}")


async def check_sensors(v: Validator) -> None:
    """Check the charging and motion notifications."""
    charging = v.client.state.charging_state

    def plugged(update: DotUpdate) -> bool:
        return update.state.charging_state in {
            ChargingState.CHARGING,
            ChargingState.CHARGING_DONE,
        }

    def unplugged(update: DotUpdate) -> bool:
        return update.state.charging_state is ChargingState.CONSUMING

    steps = [
        ("charging after plug in", "Plug the USB cable in.", plugged),
        ("consuming after unplug", "Unplug the USB cable.", unplugged),
    ]
    if charging is not ChargingState.CONSUMING:
        steps.reverse()
    for name, instruction, accepted in steps:
        await _wait_for_value(
            v,
            name,
            instruction,
            BATTERY_CHARGING_CHARACTERISTIC_UUID,
            accepted,
            v.config.event_seconds,
        )
    if v.client.state.motion_status is not MotionStatus.PARKED:
        await _wait_for_value(
            v,
            "motion PARKED when still",
            "Leave the DOT completely still until it reports parked.",
            MOTION_CHARACTERISTIC_UUID,
            lambda update: update.state.motion_status is MotionStatus.PARKED,
            v.config.motion_seconds,
        )
        if not await v.ensure_ready():
            return
    await _wait_for_value(
        v,
        "motion DRIVING when moved",
        "Pick up the DOT and move it around for a few seconds.",
        MOTION_CHARACTERISTIC_UUID,
        lambda update: update.state.motion_status is MotionStatus.DRIVING,
        v.config.motion_seconds,
    )


async def check_reconnect(v: Validator) -> None:
    """Lose the link on purpose and connect again."""
    client = v.client
    monitor = v.monitor
    lost = len(monitor.lost)
    await v.console.instruct("Switch the DOT off or carry it out of range now.")
    await monitor.wait_for(lambda: len(monitor.lost) > lost, v.config.reconnect_seconds)
    if not v.expect("connection_lost_callback called", len(monitor.lost) > lost):
        return
    error = monitor.lost[-1]
    v.expect(
        "lost error is DotConnectionError",
        isinstance(error, DotConnectionError),
        repr(error),
    )
    v.expect(
        "status DISCONNECTED after loss", client.status is ConnectionStatus.DISCONNECTED
    )
    v.expect("ready is False after loss", not client.ready)
    await v.raises(
        "play_animation after loss raises DotConnectionError",
        DotConnectionError,
        partial(client.play_animation, animations.startup()),
    )
    await v.console.pause("Switch the DOT on again or bring it back in range.")
    if not v.expect("connect() after a lost session", await v.ensure_ready()):
        return
    v.expect("device info read again", client.state.manufacturer_name is not None)
    await v.observe(
        "play after reconnect",
        partial(client.play_animation, animations.startup()),
        "Did the startup animation play?",
    )


async def check_errors(v: Validator) -> None:
    """Check the errors the library promises and the plain lifecycle calls."""
    await _check_not_ready(v)
    await _check_validation(v)
    await _check_progress_skips(v)
    await _check_lifecycle(v)


async def _check_not_ready(v: Validator) -> None:
    transport = v.transport
    fresh = FlitsmeisterDotClient(transport)
    v.expect(
        "new client is DISCONNECTED",
        fresh.status is ConnectionStatus.DISCONNECTED and not fresh.ready,
    )
    writes = transport.writes
    calls: tuple[tuple[str, Callable[[], Awaitable[None]]], ...] = (
        ("play_animation", partial(fresh.play_animation, animations.startup())),
        ("set_volume", partial(fresh.set_volume, Volume.NORMAL)),
        ("set_brightness", partial(fresh.set_brightness, Brightness.BRIGHTNESS_50)),
        (
            "set_led_orientation",
            partial(fresh.set_led_orientation, LedOrientation.NORMAL),
        ),
        ("read_settings", fresh.read_settings),
    )
    for name, call in calls:
        await v.raises(f"{name} before connect raises", DotNotReadyError, call)
    v.expect("nothing written before connect", transport.writes == writes)


async def _check_validation(v: Validator) -> None:
    client = v.client
    transport = v.transport

    async def build(response_timeout: float, long_press: float) -> None:
        FlitsmeisterDotClient(
            transport,
            response_timeout_seconds=response_timeout,
            long_press_seconds=long_press,
        )

    for label, timeout, long_press in (
        ("timeout 0", 0.0, 1.0),
        ("timeout nan", math.nan, 1.0),
        ("long press -1", 10.0, -1.0),
        ("long press inf", 10.0, math.inf),
    ):
        await v.raises(
            f"client with {label} raises",
            DotValidationError,
            partial(build, timeout, long_press),
        )
    writes = transport.writes
    for label, bad in (
        (
            "value 256",
            DotAnimation(type=DotAnimationType.PROGRESSION_TOP_TO_BOTTOM, value=256),
        ),
        ("color 2**32", DotAnimation(type=DotAnimationType.WAVE, color=2**32)),
    ):
        await v.raises(
            f"animation with {label} raises",
            DotValidationError,
            partial(client.play_animation, bad),
        )
    v.expect("bad animations wrote nothing", transport.writes == writes)
    v.expect("session still ready after bad animations", client.ready)


async def _check_progress_skips(v: Validator) -> None:
    client = v.client
    transport = v.transport
    half = animations.progress(color=DotColor.SUCCESS, fraction=0.5)
    if await v.attempt("progress 0.5", partial(client.play_animation, half)):
        writes = transport.writes
        await v.attempt("progress 0.5 again", partial(client.play_animation, half))
        v.expect("repeated progress skipped", transport.writes == writes)
        await v.attempt(
            "progress 0.75",
            partial(
                client.play_animation,
                animations.progress(color=DotColor.SUCCESS, fraction=0.75),
            ),
        )
        v.expect("changed progress written", transport.writes == writes + 1)
    for fraction, leds in ((1.5, 8), (-0.5, 1)):
        clamped = animations.progress(color=DotColor.SUCCESS, fraction=fraction)
        v.expect(
            f"progress {fraction} clamps to {leds} LEDs",
            clamped.value == leds,
            str(clamped.value),
        )
        await v.attempt(f"progress {fraction}", partial(client.play_animation, clamped))


async def _check_lifecycle(v: Validator) -> None:
    client = v.client
    transport = v.transport
    connects = transport.connects
    await v.attempt("connect() while ready", client.connect)
    v.expect("connect() while ready does nothing", transport.connects == connects)
    lost = len(v.monitor.lost)
    if not await v.attempt("disconnect()", client.disconnect):
        return
    v.expect("status DISCONNECTED", client.status is ConnectionStatus.DISCONNECTED)
    v.expect("connected is False", not client.connected)
    await asyncio.sleep(LOST_CALLBACK_GRACE_SECONDS)
    v.expect("disconnect() does not call connection_lost", len(v.monitor.lost) == lost)
    await v.raises(
        "play_animation after disconnect raises",
        DotNotReadyError,
        partial(client.play_animation, animations.startup()),
    )
    await v.attempt("second disconnect()", client.disconnect)
    v.expect("second disconnect() keeps DISCONNECTED", not client.connected)
    if not await v.attempt("connect() after disconnect", client.connect):
        return
    v.expect("ready after connect()", client.ready)
    v.expect("state read again", client.state.manufacturer_name is not None)
    await v.observe(
        "play after connect()",
        partial(client.play_animation, animations.startup()),
        "Did the startup animation play?",
    )


SECTION_CHECKS: dict[str, Callable[[Validator], Awaitable[None]]] = {
    "info": check_info,
    "settings": check_settings,
    "animations": check_animations,
    "sounds": check_sounds,
    "buttons": check_buttons,
    "sensors": check_sensors,
    "reconnect": check_reconnect,
    "errors": check_errors,
}
SECTIONS = tuple(SECTION_CHECKS)


async def restore(
    v: Validator, brightness: Brightness | None, orientation: LedOrientation | None
) -> None:
    """Write the settings back the way they were before the run."""
    v.section = "restore"
    if not await v.ensure_ready():
        return
    client = v.client
    if brightness is not None and await v.attempt(
        f"set_brightness {brightness.value}", partial(client.set_brightness, brightness)
    ):
        v.expect("brightness restored", client.state.brightness is brightness)
    if orientation is not None and await v.attempt(
        f"set_led_orientation {orientation.name}",
        partial(client.set_led_orientation, orientation),
    ):
        v.expect("orientation restored", client.state.led_orientation is orientation)
    await v.attempt(
        f"set_volume {RESTORE_VOLUME.name}", partial(client.set_volume, RESTORE_VOLUME)
    )
    await v.attempt("fade_out", partial(client.play_animation, animations.fade_out()))


async def validate(
    config: RunConfig, transport: CountingTransport, console: Console
) -> list[CheckResult]:
    """Connect, run the chosen sections, restore the settings and return the results."""
    monitor = Monitor()
    client = FlitsmeisterDotClient(
        transport,
        update_callback=monitor.on_update,
        connection_lost_callback=monitor.on_lost,
    )
    v = Validator(client, transport, monitor, console, config)
    async with client:
        v.section = "connect"
        v.expect("connect() through async with", client.ready)
        await client.read_settings()
        brightness = client.state.brightness
        orientation = client.state.led_orientation
        try:
            for number, name in enumerate(config.sections, start=1):
                v.section = name
                console.say(f"Section {number} of {len(config.sections)}: {name}")
                if not await v.ensure_ready():
                    continue
                try:
                    await SECTION_CHECKS[name](v)
                except Exception as err:  # noqa: BLE001
                    v.record("section stopped", Outcome.FAIL, repr(err))
        finally:
            await restore(v, brightness, orientation)
    return v.results


def summary(results: Sequence[CheckResult]) -> str:
    """Return the counts and every failed check as text."""
    counts = dict.fromkeys(Outcome, 0)
    for result in results:
        counts[result.outcome] += 1
    lines = [
        (
            f"{counts[Outcome.PASS]} passed, {counts[Outcome.FAIL]} failed,"
            f" {counts[Outcome.SKIP]} skipped"
        )
    ]
    lines.extend(
        f"FAIL {result.section}: {result.name} {result.detail}".rstrip()
        for result in results
        if result.outcome is Outcome.FAIL
    )
    return "\n".join(lines)


def write_report(path: Path, config: RunConfig, results: Sequence[CheckResult]) -> None:
    """Write the results as a JSON report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": __version__,
        "sections": list(config.sections),
        "results": [asdict(result) for result in results],
    }
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


async def connect_and_validate(
    config: RunConfig, console: Console
) -> list[CheckResult]:
    """Scan for the DOT and run the checks against it."""
    with common.CaptureWriter(config.output) as writer:
        return await common.run_with_dot(
            proxy=config.proxy,
            noise_psk=config.noise_psk,
            address=config.address,
            scan_seconds=config.scan_seconds,
            wrap=partial(CountingTransport, capture=writer),
            body=partial(validate, config, console=console),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--address")
    parser.add_argument("--proxy", help="ESPHome Bluetooth proxy host")
    parser.add_argument("--noise-psk", help="API encryption key of the proxy")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scan-seconds", type=float, default=60.0)
    parser.add_argument("--section", action="append", choices=SECTIONS)
    parser.add_argument("--event-seconds", type=float, default=60.0)
    parser.add_argument("--motion-seconds", type=float, default=180.0)
    parser.add_argument("--reconnect-seconds", type=float, default=120.0)
    parser.add_argument("--pause-seconds", type=float, default=1.5)
    parser.add_argument("--verbose", action="store_true", help="Log every payload")
    parser.add_argument(
        "--bridge",
        type=Path,
        help="Ask the questions through files in this folder instead of the terminal",
    )
    return parser


def config_from_args(argv: Sequence[str] | None = None) -> RunConfig:
    """Parse the command line and fill the connection options from the config file.

    The config file supplies ``address``, ``proxy`` and ``noise_psk`` when
    the command line leaves them unset.

    Raises:
        SystemExit: The config file is missing or not a JSON object.
    """
    args = _parser().parse_args(argv)
    try:
        file_config = common.load_config(args.config)
    except ValueError as err:
        sys.stderr.write(f"{err}\n")
        raise SystemExit(2) from err
    if not file_config:
        sys.stderr.write(f"Writing to the DOT needs the config file {args.config}\n")
        raise SystemExit(2)
    chosen = set(args.section or SECTIONS)
    return RunConfig(
        address=args.address or file_config.get("address"),
        output=args.output,
        report=args.report,
        scan_seconds=args.scan_seconds,
        sections=tuple(name for name in SECTIONS if name in chosen),
        event_seconds=args.event_seconds,
        motion_seconds=args.motion_seconds,
        reconnect_seconds=args.reconnect_seconds,
        pause_seconds=args.pause_seconds,
        verbose=args.verbose,
        bridge=args.bridge,
        proxy=args.proxy or file_config.get("proxy"),
        noise_psk=args.noise_psk or file_config.get("noise_psk"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, run the checks and return 0 only when nothing failed."""
    config = config_from_args(argv)
    logging.basicConfig(
        level=logging.INFO if config.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    console: Console = (
        TerminalConsole() if config.bridge is None else FileConsole(config.bridge)
    )
    console.say("Turn Bluetooth off on your phone so the app does not take the DOT.")
    try:
        results = asyncio.run(connect_and_validate(config, console))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted\n")
        return 1
    except Exception as err:
        _LOGGER.warning("Validation failed: %s", err, exc_info=True)
        return 1
    write_report(config.report, config, results)
    sys.stdout.write(f"\n{summary(results)}\nReport: {config.report}\n")
    return 1 if any(result.outcome is Outcome.FAIL for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
