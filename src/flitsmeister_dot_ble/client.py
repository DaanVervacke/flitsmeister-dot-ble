"""Async client for one Flitsmeister DOT.

``FlitsmeisterDotClient`` connects through a ``BleTransport``, subscribes
to the button, battery, charging and motion characteristics, reads the
device information and merges every decoded value into a ``DotState``.
When a ready session fails, a background task tears it down and then
calls ``connection_lost_callback``.
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum, auto
from functools import partial
from types import TracebackType
from typing import Final, Self, TypeAlias

from .animations import DotAnimation, DotAnimationType
from .const import (
    ANIMATION_CHARACTERISTIC_UUID,
    BATTERY_CHARGING_CHARACTERISTIC_UUID,
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    BRIGHTNESS_CHARACTERISTIC_UUID,
    BUTTON_EVENTS_CHARACTERISTIC_UUID,
    DEFAULT_LONG_PRESS_SECONDS,
    DEFAULT_RESPONSE_TIMEOUT_SECONDS,
    FIRMWARE_REVISION_CHARACTERISTIC_UUID,
    LED_ROTATION_CHARACTERISTIC_UUID,
    MANUFACTURER_NAME_CHARACTERISTIC_UUID,
    MODEL_NUMBER_CHARACTERISTIC_UUID,
    MOTION_CHARACTERISTIC_UUID,
    READ_CHARACTERISTICS,
    SERIAL_NUMBER_CHARACTERISTIC_UUID,
    SOFTWARE_REVISION_CHARACTERISTIC_UUID,
    SPEECH_LANGUAGE_CHARACTERISTIC_UUID,
    SUBSCRIBE_CHARACTERISTICS,
    VOLUME_CHARACTERISTIC_UUID,
)
from .exceptions import (
    DotConnectionError,
    DotError,
    DotNotReadyError,
    DotProtocolError,
    DotTimeoutError,
    DotValidationError,
)
from .models import (
    Brightness,
    ButtonAction,
    ConnectionStatus,
    DotButton,
    DotButtonEvent,
    DotState,
    DotUpdate,
    LedOrientation,
    SpeechLanguage,
    Volume,
)
from .protocol import (
    decode_battery_level,
    decode_brightness,
    decode_button_event,
    decode_charging_state,
    decode_led_orientation,
    decode_motion_status,
    decode_text,
    serial_number_uuid,
)
from .transport_types import BleTransport

__all__ = [
    "ConnectionLostCallback",
    "FlitsmeisterDotClient",
    "UpdateCallback",
]

UpdateCallback: TypeAlias = Callable[[DotUpdate], Awaitable[None] | None]  # noqa: UP040
"""Sync or async function called with each ``DotUpdate``.

It runs in the notification worker, or in the connecting task for the
values read during ``connect()``. It must return quickly.
"""
ConnectionLostCallback: TypeAlias = Callable[[Exception], Awaitable[None] | None]  # noqa: UP040
"""Sync or async function called with the exception that ended a session."""

_LOGGER = logging.getLogger(__name__)


class _Phase(Enum):
    """Lifecycle phase of one session.

    ``IDLE`` has no open transport. ``connect()`` moves through ``OPENING``
    while the transport connects and ``CONNECTED`` while it subscribes
    and reads. Once both finished the session is ``READY``. A failure in
    ``READY`` moves to ``FAILED`` until the recovery task finished its
    teardown. A teardown for any other reason, including a failure in
    ``CONNECTED``, runs in ``CLOSING``. Every teardown ends in ``IDLE``.
    Only ``CONNECTED`` and ``READY`` react to a session failure.
    """

    IDLE = auto()
    OPENING = auto()
    CONNECTED = auto()
    READY = auto()
    FAILED = auto()
    CLOSING = auto()


_PHASE_STATUS: Final[Mapping[_Phase, ConnectionStatus]] = {
    _Phase.IDLE: ConnectionStatus.DISCONNECTED,
    _Phase.OPENING: ConnectionStatus.DISCONNECTED,
    _Phase.CONNECTED: ConnectionStatus.CONNECTED,
    _Phase.READY: ConnectionStatus.READY,
    _Phase.FAILED: ConnectionStatus.DISCONNECTED,
    _Phase.CLOSING: ConnectionStatus.DISCONNECTED,
}
_LIVE_PHASES = frozenset((_Phase.CONNECTED, _Phase.READY))

_TRANSPORT_ERRORS = (OSError, TimeoutError)


@dataclass(slots=True)
class _ButtonPress:
    """One held button and the timer that resolves its long press."""

    payload: bytes
    timer: asyncio.Task[None]
    long_fired: bool = False


_Decoder = Callable[[DotState, bytes], tuple[DotState, DotButtonEvent | None]]


def _decode_battery(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, battery_level=decode_battery_level(payload)), None


def _decode_charging(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, charging_state=decode_charging_state(payload)), None


def _decode_motion(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, motion_status=decode_motion_status(payload)), None


def _decode_brightness(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, brightness=decode_brightness(payload)), None


def _decode_led_orientation(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, led_orientation=decode_led_orientation(payload)), None


def _decode_button(state: DotState, payload: bytes) -> tuple[DotState, DotButtonEvent]:
    return state, decode_button_event(payload)


def _decode_manufacturer(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, manufacturer_name=decode_text(payload)), None


def _decode_model(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, model_number=decode_text(payload)), None


def _decode_serial(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return (
        replace(
            state,
            serial_raw=payload.hex(),
            serial_uuid=serial_number_uuid(payload),
        ),
        None,
    )


def _decode_firmware(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, firmware_revision=decode_text(payload)), None


def _decode_software(state: DotState, payload: bytes) -> tuple[DotState, None]:
    return replace(state, software_revision=decode_text(payload)), None


_DECODERS: Final[dict[str, _Decoder]] = {
    BATTERY_LEVEL_CHARACTERISTIC_UUID: _decode_battery,
    BATTERY_CHARGING_CHARACTERISTIC_UUID: _decode_charging,
    MOTION_CHARACTERISTIC_UUID: _decode_motion,
    BRIGHTNESS_CHARACTERISTIC_UUID: _decode_brightness,
    LED_ROTATION_CHARACTERISTIC_UUID: _decode_led_orientation,
    BUTTON_EVENTS_CHARACTERISTIC_UUID: _decode_button,
    MANUFACTURER_NAME_CHARACTERISTIC_UUID: _decode_manufacturer,
    MODEL_NUMBER_CHARACTERISTIC_UUID: _decode_model,
    SERIAL_NUMBER_CHARACTERISTIC_UUID: _decode_serial,
    FIRMWARE_REVISION_CHARACTERISTIC_UUID: _decode_firmware,
    SOFTWARE_REVISION_CHARACTERISTIC_UUID: _decode_software,
}


def _check_timings(response_timeout_seconds: float, long_press_seconds: float) -> None:
    timings = {
        "response_timeout_seconds": response_timeout_seconds,
        "long_press_seconds": long_press_seconds,
    }
    for name, value in timings.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise DotValidationError(f"{name} must be a number")
        if not math.isfinite(value):
            raise DotValidationError(f"{name} must be finite")
        if value <= 0:
            raise DotValidationError(f"{name} must be above 0")


class FlitsmeisterDotClient:
    """Communicate with one Flitsmeister DOT."""

    def __init__(
        self,
        transport: BleTransport,
        *,
        response_timeout_seconds: float = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        long_press_seconds: float = DEFAULT_LONG_PRESS_SECONDS,
        update_callback: UpdateCallback | None = None,
        connection_lost_callback: ConnectionLostCallback | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            transport: BLE transport that owns the GATT connection.
            response_timeout_seconds: Seconds allowed for every transport
                call after the transport connect. The transport sets its
                own connect timeout.
            long_press_seconds: Seconds a button must be held before the
                client emits a ``LONG_PRESS`` event. The Flitsmeister
                app sends its report after a full second.
            update_callback: Called, sync or async, with a ``DotUpdate``
                for every decoded value, including the values read
                during ``connect()``. It must return quickly.
            connection_lost_callback: Called, sync or async, with the
                exception that ended a ready session. Not called for
                ``disconnect()`` or for a failed ``connect()``.

        Raises:
            DotValidationError: A timing is not a finite number above 0.
        """
        _check_timings(response_timeout_seconds, long_press_seconds)
        self.transport = transport
        self.update_callback = update_callback
        self.connection_lost_callback = connection_lost_callback
        self._response_timeout = response_timeout_seconds
        self._long_press_seconds = long_press_seconds
        self._state = DotState()
        self._phase = _Phase.IDLE
        self._lifecycle_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._notifications: asyncio.Queue[tuple[str, bytes] | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._connect_tasks: set[asyncio.Task[None]] = set()
        self._recovery_task: asyncio.Task[None] | None = None
        self._close_requests = 0
        self._session_failure: Exception | None = None
        self._last_animation: DotAnimation | None = None
        self._presses: dict[DotButton, _ButtonPress] = {}

    @property
    def state(self) -> DotState:
        """The latest decoded DOT state."""
        return self._state

    @property
    def status(self) -> ConnectionStatus:
        """The session status."""
        return _PHASE_STATUS[self._phase]

    @property
    def connected(self) -> bool:
        """Whether the transport is connected, ready or not."""
        return self._phase in _LIVE_PHASES

    @property
    def ready(self) -> bool:
        """Whether the session is ready."""
        return self._phase is _Phase.READY

    async def connect(self) -> None:
        """Connect, subscribe and read the device information.

        Connects the transport, subscribes to the button, battery,
        charging and motion characteristics, reads the device information
        and returns once every read succeeded. Does nothing when already
        connected. Waits for the cleanup of a failed session first. The
        client can connect again after ``disconnect()`` or after a lost
        session.

        A failed attempt cleans up the transport and does not call
        ``connection_lost_callback``.

        Raises:
            DotConnectionError: The transport failed, the link dropped
                while connecting, or ``disconnect()`` cancelled the
                attempt. Transport errors are chained as ``__cause__``.
            DotTimeoutError: A subscribe or a read did not finish within
                ``response_timeout_seconds``.
            DotProtocolError: A read returned a malformed payload.
        """
        task = asyncio.create_task(self._connect())
        self._connect_tasks.add(task)
        task.add_done_callback(self._connect_tasks.discard)
        try:
            await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            raise DotConnectionError(
                "disconnect() cancelled the connection attempt"
            ) from None

    async def disconnect(self) -> None:
        """Disconnect and tear down the session.

        Cancels an in-flight ``connect()``, waits for the cleanup of a
        failed session, stops the notifications and disconnects the
        transport. Errors during teardown are logged at debug level.
        Does nothing when already disconnected.
        ``connection_lost_callback`` is not called once this method
        returned.
        """
        self._close_requests += 1
        try:
            await self._cancel_connects()
            await self._wait_for_recovery()
            async with self._lifecycle_lock:
                await self._teardown()
        finally:
            self._close_requests -= 1

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.disconnect()

    async def play_animation(self, animation: DotAnimation) -> None:
        """Play one animation on the device.

        A progression top to bottom animation that equals the last one
        played is skipped, like the Flitsmeister app does, so repeated
        progress updates do not spam the device.

        Args:
            animation: The animation to play, built by one of the preset
                functions in ``animations`` or by hand.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier or the write
                failed. Transport errors are chained as ``__cause__``.
            DotValidationError: The animation does not fit the packet.
        """
        if self._is_duplicate(animation):
            return
        await self._send(
            ANIMATION_CHARACTERISTIC_UUID, animation.to_bytes(), "animation"
        )
        self._last_animation = animation

    async def set_volume(self, volume: Volume) -> None:
        """Set the speaker volume.

        The device does not report the volume, so the state mirrors the
        written value.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier or the write
                failed.
        """
        await self._send(VOLUME_CHARACTERISTIC_UUID, bytes((volume,)), "volume")
        self._state = replace(self._state, volume=volume)

    async def set_brightness(self, brightness: Brightness) -> None:
        """Set the LED brightness and read it back into the state.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier, the write or
                the read back failed, or the device returned a malformed
                value.
        """
        await self._send(
            BRIGHTNESS_CHARACTERISTIC_UUID, bytes((brightness,)), "brightness"
        )
        await self._read_and_apply(BRIGHTNESS_CHARACTERISTIC_UUID)

    async def set_led_orientation(self, orientation: LedOrientation) -> None:
        """Set the LED ring orientation and read it back into the state.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier, the write or
                the read back failed, or the device returned a malformed
                value.
        """
        await self._send(
            LED_ROTATION_CHARACTERISTIC_UUID, bytes((orientation,)), "orientation"
        )
        await self._read_and_apply(LED_ROTATION_CHARACTERISTIC_UUID)

    async def set_speech_language(self, language: SpeechLanguage) -> None:
        """Set the voice language.

        The device does not report the language, so the state mirrors
        the written value.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier or the write
                failed.
        """
        await self._send(
            SPEECH_LANGUAGE_CHARACTERISTIC_UUID, bytes((language,)), "language"
        )
        self._state = replace(self._state, speech_language=language)

    async def read_settings(self) -> None:
        """Read brightness and LED orientation into the state.

        The Flitsmeister app reads both only after a write, so
        ``connect()`` leaves them unset until this method or a setting
        write fills them.

        Raises:
            DotNotReadyError: The session is not ready.
            DotConnectionError: The session failed earlier, a read
                failed, or the device returned a malformed value.
        """
        await self._read_and_apply(BRIGHTNESS_CHARACTERISTIC_UUID)
        await self._read_and_apply(LED_ROTATION_CHARACTERISTIC_UUID)

    @property
    def _closing(self) -> bool:
        return self._close_requests > 0

    async def _connect(self) -> None:
        while True:
            await self._wait_for_teardown()
            async with self._lifecycle_lock:
                if self._phase is _Phase.FAILED:
                    continue
                if not self.connected:
                    await self._open_session()
                return

    async def _open_session(self) -> None:
        self._reset_session()
        try:
            self._phase = _Phase.OPENING
            await self.transport.connect(self._on_disconnected)
            self._phase = _Phase.CONNECTED
            self._notifications = asyncio.Queue()
            self._worker = asyncio.create_task(self._consume(self._notifications))
            for characteristic in SUBSCRIBE_CHARACTERISTICS:
                async with asyncio.timeout(self._response_timeout):
                    await self.transport.start_notify(
                        characteristic, self._notification
                    )
            for characteristic in READ_CHARACTERISTICS:
                async with asyncio.timeout(self._response_timeout):
                    payload = await self.transport.read_gatt_char(characteristic)
                    await self._apply(characteristic, payload)
            self._phase = _Phase.READY
        except DotError:
            await self._abort_open()
            raise
        except TimeoutError as err:
            await self._abort_open()
            raise DotTimeoutError("The DOT did not answer while connecting") from err
        except BaseException as err:
            await self._abort_open()
            if isinstance(err, Exception):
                raise DotConnectionError("Connecting to the DOT failed") from err
            raise

    async def _abort_open(self) -> None:
        self._close_requests += 1
        try:
            await self._teardown()
        finally:
            self._close_requests -= 1

    async def _cancel_connects(self) -> None:
        tasks = [task for task in self._connect_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    async def _wait_for_teardown(self) -> None:
        task = self._recovery_task
        if self._phase is _Phase.FAILED and task is not None:
            await asyncio.wait((task,))

    async def _wait_for_recovery(self) -> None:
        task = self._recovery_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            await asyncio.wait((task,))

    def _notification(self, characteristic: str, payload: bytes) -> None:
        if self._worker is not None:
            self._notifications.put_nowait((characteristic, bytes(payload)))

    async def _consume(self, queue: asyncio.Queue[tuple[str, bytes] | None]) -> None:
        while (item := await queue.get()) is not None:
            characteristic, payload = item
            try:
                await self._apply(characteristic, payload)
            except DotProtocolError as err:
                _LOGGER.warning("Dropped DOT notification %s: %s", payload.hex(), err)
            except Exception:
                _LOGGER.exception("DOT notification processing failed")
            finally:
                queue.task_done()
        queue.task_done()

    async def _apply(self, characteristic: str, payload: bytes) -> None:
        state, button = self._decode(characteristic, payload)
        self._state = state
        await self._emit(characteristic, payload, button)
        if button is not None:
            await self._resolve_press(button, payload)

    async def _emit(
        self, characteristic: str, payload: bytes, button: DotButtonEvent | None
    ) -> None:
        callback = self.update_callback
        if callback is None:
            return
        try:
            result = callback(
                DotUpdate(self._state, self.status, characteristic, payload, button)
            )
            if result is not None:
                await result
        except Exception:
            _LOGGER.exception("DOT update callback failed")

    async def _resolve_press(self, event: DotButtonEvent, payload: bytes) -> None:
        if event.action is ButtonAction.PUSHED:
            self._presses[event.button] = _ButtonPress(
                payload=payload,
                timer=asyncio.get_running_loop().create_task(
                    self._long_press(event.button)
                ),
            )
            return
        if event.action is not ButtonAction.RELEASED:
            return
        press = self._presses.pop(event.button, None)
        if press is None or press.long_fired:
            return
        press.timer.cancel()
        await self._emit(
            BUTTON_EVENTS_CHARACTERISTIC_UUID,
            press.payload,
            DotButtonEvent(event.button, ButtonAction.SHORT_PRESS),
        )

    async def _long_press(self, button: DotButton) -> None:
        await asyncio.sleep(self._long_press_seconds)
        press = self._presses.get(button)
        if press is None:
            return
        press.long_fired = True
        await self._emit(
            BUTTON_EVENTS_CHARACTERISTIC_UUID,
            press.payload,
            DotButtonEvent(button, ButtonAction.LONG_PRESS),
        )

    async def _cancel_presses(self) -> None:
        presses = list(self._presses.values())
        self._presses.clear()
        for press in presses:
            press.timer.cancel()
        if presses:
            await asyncio.gather(
                *(press.timer for press in presses), return_exceptions=True
            )

    def _is_duplicate(self, animation: DotAnimation) -> bool:
        last = self._last_animation
        return (
            last is not None
            and last.type is DotAnimationType.PROGRESSION_TOP_TO_BOTTOM
            and animation == last
        )

    def _raise_if_session_failed(self) -> None:
        failure = self._session_failure
        if failure is not None:
            raise DotConnectionError(f"The DOT session failed: {failure}") from failure

    def _require_ready(self) -> None:
        self._raise_if_session_failed()
        if not self.ready:
            raise DotNotReadyError("The DOT session is not ready")

    async def _write(self, characteristic: str, data: bytes) -> None:
        async with self._write_lock:
            async with asyncio.timeout(self._response_timeout):
                await self.transport.write_gatt_char(
                    characteristic, data, response=True
                )

    async def _send(self, characteristic: str, data: bytes, label: str) -> None:
        self._require_ready()
        try:
            await self._write(characteristic, data)
        except _TRANSPORT_ERRORS as err:
            failure = DotConnectionError(f"Writing {label} to the DOT failed")
            self._fail(failure)
            raise DotConnectionError(f"Writing {label} to the DOT failed") from err

    async def _read_and_apply(self, characteristic: str) -> None:
        self._require_ready()
        try:
            async with asyncio.timeout(self._response_timeout):
                payload = await self.transport.read_gatt_char(characteristic)
        except _TRANSPORT_ERRORS as err:
            failure = DotConnectionError("Reading the DOT failed")
            self._fail(failure)
            raise DotConnectionError("Reading the DOT failed") from err
        await self._apply(characteristic, payload)

    def _decode(
        self, characteristic: str, payload: bytes
    ) -> tuple[DotState, DotButtonEvent | None]:
        decoder = _DECODERS.get(characteristic.lower())
        if decoder is None:
            raise DotProtocolError(f"Unknown characteristic {characteristic}")
        return decoder(self._state, payload)

    def _on_disconnected(self) -> None:
        self._fail(DotConnectionError("The DOT disconnected"))

    def _fail(self, error: Exception) -> None:
        if self._closing or not self.connected:
            return
        self._session_failure = error
        if self._phase is _Phase.CONNECTED:
            self._phase = _Phase.CLOSING
            return
        _LOGGER.warning("DOT session failed: %s", error)
        self._phase = _Phase.FAILED
        self._recovery_task = asyncio.get_running_loop().create_task(
            self._recover(error)
        )

    async def _recover(self, error: Exception) -> None:
        try:
            async with self._lifecycle_lock:
                await self._teardown()
        finally:
            if self._phase is _Phase.FAILED:
                self._phase = _Phase.CLOSING
        if self._closing:
            return
        callback = self.connection_lost_callback
        if callback is None:
            return
        try:
            result = callback(error)
            if result is not None:
                await result
        except Exception:
            _LOGGER.exception("DOT connection lost callback failed")

    async def _teardown(self) -> None:
        transport_open = self._phase is not _Phase.IDLE
        if self._phase is not _Phase.FAILED and transport_open:
            self._phase = _Phase.CLOSING
        if transport_open:
            for characteristic in SUBSCRIBE_CHARACTERISTICS:
                await self._quietly(
                    "stop_notify", partial(self.transport.stop_notify, characteristic)
                )
            await self._quietly("disconnect", self.transport.disconnect)
        await self._stop_worker()
        await self._cancel_presses()
        self._phase = _Phase.IDLE

    async def _quietly(self, label: str, action: Callable[[], Awaitable[None]]) -> None:
        try:
            async with asyncio.timeout(self._response_timeout):
                await action()
        except Exception:
            _LOGGER.debug(
                "DOT transport %s failed during teardown", label, exc_info=True
            )

    async def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        self._notifications.put_nowait(None)
        if worker is not asyncio.current_task():
            await asyncio.gather(worker, return_exceptions=True)

    def _reset_session(self) -> None:
        self._state = DotState()
        self._session_failure = None
        self._last_animation = None
