# flitsmeister-dot-ble

[![Check](https://github.com/DaanVervacke/flitsmeister-dot-ble/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/flitsmeister-dot-ble/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Async Python library for the Flitsmeister DOT, the dashboard device that
warns drivers about speed cameras and hazards. It reads the battery,
charging, motion and button state, plays animations and changes the
settings over Bluetooth Low Energy. Requires Python >= 3.14.

> Unofficial and not endorsed by Flitsmeister. A firmware update can
> break it.

## Install

```bash
uv add flitsmeister-dot-ble
```

## Usage

```python
import asyncio

from bleak import BleakScanner

from flitsmeister_dot_ble import BleakTransport, FlitsmeisterDotClient, animations


async def main() -> None:
    device = await BleakScanner.find_device_by_address("AA:BB:CC:DD:EE:FF")
    if device is None:
        raise SystemExit("Flitsmeister DOT not found")
    async with FlitsmeisterDotClient(BleakTransport(device)) as client:
        print(client.state)
        await client.play_animation(animations.speed_trap())


asyncio.run(main())
```

In Home Assistant, pass the `BLEDevice` from
`bluetooth.async_ble_device_from_address` instead of scanning.
`is_dot_advertisement(name, service_uuids)` tells whether an
advertisement comes from a DOT.

## How it works

- `connect()` subscribes to the device, reads the device information
  and returns once the session is ready.
- Every decoded value updates `client.state` and goes to the optional
  `update_callback` as a `DotUpdate`.
- Button events arrive as `PUSHED` and `RELEASED`. The client adds
  `SHORT_PRESS` and `LONG_PRESS` based on `long_press_seconds`.
- When the link drops, `client.status` becomes `DISCONNECTED` and the
  optional `connection_lost_callback` receives the exception. Call
  `connect()` again to reconnect.
- The client takes a `BleTransport`, so tests can pass a fake transport
  instead of Bluetooth hardware.

| Option | Default | Meaning |
| --- | --- | --- |
| `response_timeout_seconds` | 10 | limit for every transport call after connecting |
| `long_press_seconds` | 1.0 | hold time before a `LONG_PRESS` event |

## Animations

The `animations` module has a preset for every alert the Flitsmeister
app shows, such as `speed_trap()`, `traffic_jam_start()` and
`progress(color=..., fraction=...)`. `DotAnimation` builds custom packets.

## Settings

| Method | Values |
| --- | --- |
| `set_volume` | `Volume.SILENT`, `LOW`, `NORMAL`, `HARD` |
| `set_brightness` | `Brightness.BRIGHTNESS_10` to `BRIGHTNESS_100` in steps of 10 |
| `set_led_orientation` | `LedOrientation.NORMAL`, `UPSIDE_DOWN` |
| `read_settings` | reads brightness and orientation into the state |

The speech language is read-only and available as
`state.speech_language`.

## Errors

Every error derives from `DotError`.

| Error | Raised when |
| --- | --- |
| `DotNotReadyError` | a method runs before the session is ready |
| `DotConnectionError` | the transport fails, the link drops or a call times out after connecting |
| `DotTimeoutError` | the DOT does not answer during `connect()`, also when the link dropped silently |
| `DotRejectedError` | the DOT refuses a write or a read and the session stays ready |
| `DotProtocolError` | the DOT sends a malformed value |
| `DotValidationError` | an argument is out of range |

## More

- [API reference](https://flitsmeister-dot-ble.readthedocs.io/)
- [PROTOCOL.md](PROTOCOL.md) for the wire format
- [CONTRIBUTING.md](CONTRIBUTING.md) for development and the hardware scripts
