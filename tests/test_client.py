import asyncio
import logging

import pytest
from flitsmeister_dot_ble import (
    ButtonAction,
    ChargingState,
    ConnectionStatus,
    DotButton,
    DotButtonEvent,
    DotColor,
    DotConnectionError,
    DotNotReadyError,
    DotProtocolError,
    DotState,
    DotTimeoutError,
    DotUpdate,
    DotValidationError,
    FlitsmeisterDotClient,
    MotionStatus,
    animations,
)
from flitsmeister_dot_ble.const import (
    ANIMATION_CHARACTERISTIC_UUID,
    BATTERY_LEVEL_CHARACTERISTIC_UUID,
    BRIGHTNESS_CHARACTERISTIC_UUID,
    BUTTON_EVENTS_CHARACTERISTIC_UUID,
    LED_ROTATION_CHARACTERISTIC_UUID,
    READ_CHARACTERISTICS,
    SPEECH_LANGUAGE_CHARACTERISTIC_UUID,
    SUBSCRIBE_CHARACTERISTICS,
    VOLUME_CHARACTERISTIC_UUID,
)
from flitsmeister_dot_ble.models import (
    Brightness,
    LedOrientation,
    SpeechLanguage,
    Volume,
)

from .helpers import FakeTransport, drain, make_client


def test_invalid_timing_is_rejected(transport: FakeTransport) -> None:
    for value in (True, "1", float("nan"), float("inf"), 0, -1):
        with pytest.raises(DotValidationError, match="response_timeout_seconds"):
            FlitsmeisterDotClient(transport, response_timeout_seconds=value)  # type: ignore[arg-type]


async def test_connect_subscribes_and_reads(transport: FakeTransport) -> None:
    async with make_client(transport) as client:
        assert client.ready
        assert client.status is ConnectionStatus.READY
        assert client.connected
    assert transport.notify_characteristics == list(SUBSCRIBE_CHARACTERISTICS)
    assert transport.read_characteristics == list(READ_CHARACTERISTICS)
    assert transport.stopped_characteristics == list(SUBSCRIBE_CHARACTERISTICS)
    assert transport.disconnect_calls == 1


async def test_state_filled_from_reads(connected_client: FlitsmeisterDotClient) -> None:
    state = connected_client.state

    assert state.battery_level == 100
    assert state.charging_state is ChargingState.CHARGING
    assert state.motion_status is MotionStatus.PARKED
    assert state.manufacturer_name == "Flitsmeister"
    assert state.model_number == "DOT"
    assert state.serial_raw == "112233"
    assert state.serial_uuid is not None
    assert state.firmware_revision == "1.0.14"
    assert state.software_revision == "1.0.14"


async def test_update_callback_receives_every_read(transport: FakeTransport) -> None:
    updates: list[DotUpdate] = []

    async def collect(update: DotUpdate) -> None:
        updates.append(update)

    async with make_client(transport, update_callback=collect):
        pass

    assert [update.characteristic for update in updates] == list(READ_CHARACTERISTICS)
    battery = updates[0]
    assert battery.state.battery_level == 100
    assert battery.payload == b"\x64"
    assert battery.button is None
    assert battery.status is ConnectionStatus.CONNECTED


async def test_battery_notification_updates_state(
    transport: FakeTransport, connected_client: FlitsmeisterDotClient
) -> None:
    updates: list[DotUpdate] = []

    async def collect(update: DotUpdate) -> None:
        updates.append(update)

    connected_client.update_callback = collect
    transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")
    await drain(connected_client)

    assert connected_client.state.battery_level == 50
    assert updates[0].status is ConnectionStatus.READY
    assert updates[0].payload == b"\x32"


async def test_button_notification_carries_event(
    transport: FakeTransport, connected_client: FlitsmeisterDotClient
) -> None:
    updates: list[DotUpdate] = []

    async def collect(update: DotUpdate) -> None:
        updates.append(update)

    connected_client.update_callback = collect
    transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x01\x00")
    await drain(connected_client)

    assert updates[0].button == DotButtonEvent(DotButton.RED, ButtonAction.PUSHED)
    assert updates[0].state == connected_client.state


async def test_malformed_notification_is_dropped(
    transport: FakeTransport,
    connected_client: FlitsmeisterDotClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x64\x00")
        await drain(connected_client)

    assert connected_client.state.battery_level == 100
    assert "Dropped DOT notification" in caplog.text
    assert connected_client.ready


async def test_unknown_characteristic_notification_is_dropped(
    transport: FakeTransport,
    connected_client: FlitsmeisterDotClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    callback = transport.callbacks[BATTERY_LEVEL_CHARACTERISTIC_UUID]
    with caplog.at_level(logging.WARNING):
        callback("0000180a-0000-1000-8000-00805f9b34fb", b"\x01")
        await drain(connected_client)

    assert "Unknown characteristic" in caplog.text
    assert connected_client.ready


async def test_malformed_read_fails_connect(transport: FakeTransport) -> None:
    transport.reads[BATTERY_LEVEL_CHARACTERISTIC_UUID] = b""
    client = make_client(transport)

    with pytest.raises(DotProtocolError, match="1 byte"):
        await client.connect()
    assert transport.disconnect_calls == 1
    assert not client.connected


async def test_read_failure_fails_connect(transport: FakeTransport) -> None:
    transport.fail_read = OSError("link lost")
    client = make_client(transport)

    with pytest.raises(DotConnectionError, match="Connecting to the DOT failed"):
        await client.connect()
    assert transport.disconnect_calls == 1


async def test_hanging_read_times_out(transport: FakeTransport) -> None:
    transport.hang_reads.add(BATTERY_LEVEL_CHARACTERISTIC_UUID)
    client = make_client(transport, response_timeout_seconds=0.05)

    with pytest.raises(DotTimeoutError, match="did not answer"):
        await client.connect()
    assert transport.disconnect_calls == 1


async def test_link_drop_while_connecting_fails_connect(
    transport: FakeTransport,
) -> None:
    transport.hang_reads.add(BATTERY_LEVEL_CHARACTERISTIC_UUID)
    client = make_client(transport, response_timeout_seconds=0.2)
    connect_task = asyncio.create_task(client.connect())
    await asyncio.sleep(0.05)
    transport.drop()

    with pytest.raises(DotTimeoutError):
        await connect_task
    assert transport.disconnect_calls == 1


async def test_connect_transport_failure(transport: FakeTransport) -> None:
    transport.fail_connect = OSError("no adapter")
    client = make_client(transport)

    with pytest.raises(DotConnectionError, match="Connecting to the DOT failed"):
        await client.connect()


async def test_subscribe_failure_fails_connect(transport: FakeTransport) -> None:
    transport.fail_start_notify = OSError("subscribe failed")
    client = make_client(transport)

    with pytest.raises(DotConnectionError, match="Connecting to the DOT failed"):
        await client.connect()
    assert transport.disconnect_calls == 1


async def test_connect_twice_connects_once(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    await client.connect()

    assert transport.connect_calls == 1
    await client.disconnect()


async def test_disconnect_when_idle_does_nothing(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.disconnect()

    assert transport.connect_calls == 0
    assert transport.disconnect_calls == 0
    assert client.status is ConnectionStatus.DISCONNECTED


async def test_disconnect_cancels_connecting_client(transport: FakeTransport) -> None:
    transport.hang_reads.add(BATTERY_LEVEL_CHARACTERISTIC_UUID)
    client = make_client(transport, response_timeout_seconds=5.0)
    connect_task = asyncio.create_task(client.connect())
    await asyncio.sleep(0.05)
    await client.disconnect()

    with pytest.raises(DotConnectionError, match="cancelled"):
        await connect_task
    assert transport.disconnect_calls == 1


async def test_link_drop_ends_session(
    transport: FakeTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lost: list[Exception] = []
    done = asyncio.Event()

    async def on_lost(error: Exception) -> None:
        lost.append(error)
        done.set()

    client = make_client(transport, connection_lost_callback=on_lost)
    await client.connect()
    assert client.ready
    with caplog.at_level(logging.WARNING):
        transport.drop()
        await done.wait()

    assert lost
    assert isinstance(lost[0], DotConnectionError)
    assert client.status is ConnectionStatus.DISCONNECTED
    assert transport.disconnect_calls == 1
    assert "DOT session failed" in caplog.text
    await client.disconnect()


async def test_reconnect_after_lost_session(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    transport.drop()
    await asyncio.sleep(0)

    await client.connect()

    assert client.ready
    assert client.state.battery_level == 100
    assert transport.connect_calls == 2
    await client.disconnect()


async def test_cancelled_connect_task_reraises(transport: FakeTransport) -> None:
    transport.hang_reads.add(BATTERY_LEVEL_CHARACTERISTIC_UUID)
    client = make_client(transport, response_timeout_seconds=5.0)
    connect_task = asyncio.create_task(client.connect())
    await asyncio.sleep(0.05)
    connect_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await connect_task
    assert transport.disconnect_calls == 1


async def test_notification_after_disconnect_is_ignored(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    await client.connect()
    await client.disconnect()

    transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")

    assert client.state.battery_level == 100


async def test_worker_logs_processing_error(
    transport: FakeTransport,
    connected_client: FlitsmeisterDotClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(
        _client: FlitsmeisterDotClient, _characteristic: str, _payload: bytes
    ) -> tuple[DotState, None]:
        raise RuntimeError("decode bug")

    monkeypatch.setattr(FlitsmeisterDotClient, "_decode", broken)
    with caplog.at_level(logging.ERROR):
        transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")
        await drain(connected_client)

    assert "DOT notification processing failed" in caplog.text
    assert connected_client.ready


async def test_cancelled_recovery_marks_closing(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    transport.drop()
    await asyncio.sleep(0)
    recovery = client._recovery_task
    assert recovery is not None
    recovery.cancel()
    with pytest.raises(asyncio.CancelledError):
        await recovery

    assert client.status is ConnectionStatus.DISCONNECTED
    await client.disconnect()

    assert client.status is ConnectionStatus.DISCONNECTED
    assert transport.disconnect_calls >= 1


async def test_disconnect_during_recovery_skips_callback(
    transport: FakeTransport,
) -> None:
    lost: list[Exception] = []

    async def on_lost(error: Exception) -> None:
        lost.append(error)

    client = make_client(transport, connection_lost_callback=on_lost)
    await client.connect()
    transport.drop()
    await client.disconnect()

    assert lost == []
    assert client.status is ConnectionStatus.DISCONNECTED
    assert transport.disconnect_calls == 1


async def test_teardown_survives_stop_notify_failure(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    await client.connect()
    transport.fail_stop_notify = OSError("stop failed")

    await client.disconnect()

    assert transport.disconnect_calls == 1
    assert client.status is ConnectionStatus.DISCONNECTED


async def test_reconnect_resets_state(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    assert client.state.battery_level == 100
    await client.disconnect()

    transport.reads[BATTERY_LEVEL_CHARACTERISTIC_UUID] = b"\x32"
    await client.connect()

    assert client.state.battery_level == 50
    await client.disconnect()


async def test_sync_update_callback(transport: FakeTransport) -> None:
    updates: list[DotUpdate] = []

    def collect(update: DotUpdate) -> None:
        updates.append(update)

    async with make_client(transport, update_callback=collect):
        transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")
        await asyncio.sleep(0.05)

    assert updates[-1].state.battery_level == 50


async def test_failing_update_callback_is_logged(
    transport: FakeTransport,
    connected_client: FlitsmeisterDotClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing(_update: DotUpdate) -> None:
        raise RuntimeError("boom")

    connected_client.update_callback = failing
    with caplog.at_level(logging.ERROR):
        transport.notify(BATTERY_LEVEL_CHARACTERISTIC_UUID, b"\x32")
        await drain(connected_client)

    assert connected_client.state.battery_level == 50
    assert "DOT update callback failed" in caplog.text


async def test_failing_connection_lost_callback_is_logged(
    transport: FakeTransport, caplog: pytest.LogCaptureFixture
) -> None:
    def failing(_error: Exception) -> None:
        raise RuntimeError("boom")

    client = make_client(transport, connection_lost_callback=failing)
    await client.connect()
    with caplog.at_level(logging.ERROR):
        transport.drop()
        await asyncio.sleep(0.05)

    assert "DOT connection lost callback failed" in caplog.text
    await client.disconnect()


async def test_state_starts_empty(transport: FakeTransport) -> None:
    client = make_client(transport)

    assert client.state == DotState()
    assert client.status is ConnectionStatus.DISCONNECTED
    assert not client.connected
    assert not client.ready


async def test_play_animation_writes_the_packet(transport: FakeTransport) -> None:
    client = make_client(transport)
    async with client:
        await client.play_animation(animations.speed_trap())

    assert transport.writes == [bytes.fromhex("01ff00284a030c200100")]
    assert transport.write_characteristics == [ANIMATION_CHARACTERISTIC_UUID]
    assert transport.responses == [True]


async def test_play_animation_skips_duplicate_progression(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    async with client:
        await client.play_animation(
            animations.progress(color=DotColor.SPEED_TRAP, fraction=0.5)
        )
        await client.play_animation(
            animations.progress(color=DotColor.SPEED_TRAP, fraction=0.5)
        )
        await client.play_animation(animations.speed_trap())
        await client.play_animation(animations.speed_trap())

    assert len(transport.writes) == 3


async def test_play_animation_needs_a_ready_session(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)

    with pytest.raises(DotNotReadyError, match="not ready"):
        await client.play_animation(animations.fade_out())

    assert transport.writes == []


async def test_failed_write_ends_the_session(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    transport.fail_writes = True

    with pytest.raises(DotConnectionError, match="Writing animation"):
        await client.play_animation(animations.fade_out())
    await asyncio.sleep(0)
    with pytest.raises(DotConnectionError, match="session failed"):
        await client.play_animation(animations.fade_out())
    await client.disconnect()


async def test_set_volume_writes_and_mirrors(transport: FakeTransport) -> None:
    client = make_client(transport)
    async with client:
        await client.set_volume(Volume.HARD)

        assert client.state.volume is Volume.HARD

    assert transport.writes == [b"\x03"]
    assert transport.write_characteristics == [VOLUME_CHARACTERISTIC_UUID]


async def test_set_brightness_writes_and_reads_back(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    async with client:
        await client.set_brightness(Brightness.BRIGHTNESS_50)

        assert client.state.brightness is Brightness.BRIGHTNESS_100

    assert transport.writes == [b"\x32"]
    assert transport.write_characteristics == [BRIGHTNESS_CHARACTERISTIC_UUID]
    assert transport.read_characteristics.count(BRIGHTNESS_CHARACTERISTIC_UUID) == 1


async def test_set_led_orientation_writes_and_reads_back(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    async with client:
        await client.set_led_orientation(LedOrientation.UPSIDE_DOWN)

        assert client.state.led_orientation is LedOrientation.NORMAL

    assert transport.writes == [b"\x01"]
    assert transport.write_characteristics == [LED_ROTATION_CHARACTERISTIC_UUID]
    assert transport.read_characteristics.count(LED_ROTATION_CHARACTERISTIC_UUID) == 1


async def test_set_speech_language_writes_and_mirrors(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    async with client:
        await client.set_speech_language(SpeechLanguage.GERMAN)

        assert client.state.speech_language is SpeechLanguage.GERMAN

    assert transport.writes == [b"\x02"]
    assert transport.write_characteristics == [SPEECH_LANGUAGE_CHARACTERISTIC_UUID]


async def test_read_settings_fills_the_state(transport: FakeTransport) -> None:
    client = make_client(transport)
    async with client:
        assert client.state.brightness is None
        assert client.state.led_orientation is None

        await client.read_settings()
        state = client.state

        assert state.brightness is Brightness.BRIGHTNESS_100
        assert state.led_orientation is LedOrientation.NORMAL


async def test_malformed_settings_read_raises(transport: FakeTransport) -> None:
    transport.reads[BRIGHTNESS_CHARACTERISTIC_UUID] = b""
    client = make_client(transport)
    async with client:
        with pytest.raises(DotProtocolError, match="1 byte"):
            await client.read_settings()


async def test_failed_read_back_ends_the_session(transport: FakeTransport) -> None:
    client = make_client(transport)
    await client.connect()
    transport.fail_read = OSError("link lost")

    with pytest.raises(DotConnectionError, match="Reading the DOT failed"):
        await client.set_brightness(Brightness.BRIGHTNESS_50)
    await asyncio.sleep(0)
    with pytest.raises(DotConnectionError, match="session failed"):
        await client.set_brightness(Brightness.BRIGHTNESS_50)
    await client.disconnect()


async def test_short_press_resolves(transport: FakeTransport) -> None:
    actions: list[ButtonAction] = []

    async def collect(update: DotUpdate) -> None:
        if update.button is not None:
            actions.append(update.button.action)

    client = make_client(transport, update_callback=collect)
    async with client:
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x01\x00")
        await drain(client)
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x02\x00")
        await drain(client)

    assert actions == [
        ButtonAction.PUSHED,
        ButtonAction.RELEASED,
        ButtonAction.SHORT_PRESS,
    ]


async def test_long_press_resolves_at_the_threshold(
    transport: FakeTransport,
) -> None:
    actions: list[ButtonAction] = []

    async def collect(update: DotUpdate) -> None:
        if update.button is not None:
            actions.append(update.button.action)

    client = make_client(transport, update_callback=collect, long_press_seconds=0.05)
    async with client:
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x00\x01")
        await drain(client)
        await asyncio.sleep(0.1)
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x00\x02")
        await drain(client)

    assert actions == [
        ButtonAction.PUSHED,
        ButtonAction.LONG_PRESS,
        ButtonAction.RELEASED,
    ]


async def test_release_without_push_only_releases(
    transport: FakeTransport,
) -> None:
    actions: list[ButtonAction] = []

    async def collect(update: DotUpdate) -> None:
        if update.button is not None:
            actions.append(update.button.action)

    client = make_client(transport, update_callback=collect)
    async with client:
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x02\x00")
        await drain(client)

    assert actions == [ButtonAction.RELEASED]


async def test_press_timers_stop_at_disconnect(transport: FakeTransport) -> None:
    actions: list[ButtonAction] = []

    async def collect(update: DotUpdate) -> None:
        if update.button is not None:
            actions.append(update.button.action)

    client = make_client(transport, update_callback=collect, long_press_seconds=0.05)
    await client.connect()
    transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x01\x00")
    await drain(client)
    await client.disconnect()
    await asyncio.sleep(0.1)

    assert actions == [ButtonAction.PUSHED]


async def test_second_push_cancels_the_first_timer(transport: FakeTransport) -> None:
    actions: list[ButtonAction] = []

    async def collect(update: DotUpdate) -> None:
        if update.button is not None:
            actions.append(update.button.action)

    client = make_client(transport, update_callback=collect, long_press_seconds=0.1)
    async with client:
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x01\x00")
        await drain(client)
        await asyncio.sleep(0.05)
        transport.notify(BUTTON_EVENTS_CHARACTERISTIC_UUID, b"\x01\x00")
        await drain(client)
        await asyncio.sleep(0.2)

    assert actions == [
        ButtonAction.PUSHED,
        ButtonAction.PUSHED,
        ButtonAction.LONG_PRESS,
    ]


async def test_duplicate_animation_still_needs_a_ready_session(
    transport: FakeTransport,
) -> None:
    client = make_client(transport)
    await client.connect()
    await client.play_animation(
        animations.progress(color=DotColor.SPEED_TRAP, fraction=0.5)
    )
    await client.disconnect()

    with pytest.raises(DotNotReadyError, match="not ready"):
        await client.play_animation(
            animations.progress(color=DotColor.SPEED_TRAP, fraction=0.5)
        )


async def test_sync_connection_lost_callback(transport: FakeTransport) -> None:
    lost: list[Exception] = []
    done = asyncio.Event()

    def on_lost(error: Exception) -> None:
        lost.append(error)
        done.set()

    client = make_client(transport, connection_lost_callback=on_lost)
    await client.connect()
    transport.drop()
    await done.wait()

    assert lost
    await client.disconnect()


def test_invalid_long_press_timing(transport: FakeTransport) -> None:
    for value in (True, "1", float("nan"), 0, -1):
        with pytest.raises(DotValidationError, match="long_press_seconds"):
            FlitsmeisterDotClient(transport, long_press_seconds=value)  # type: ignore[arg-type]
