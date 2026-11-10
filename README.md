# flitsmeister-dot-ble

[![Check](https://github.com/DaanVervacke/flitsmeister-dot-ble/actions/workflows/check.yml/badge.svg)](https://github.com/DaanVervacke/flitsmeister-dot-ble/actions/workflows/check.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Async Python library for the Flitsmeister DOT, the dashboard device that
warns drivers about speed cameras and hazards. Requires Python >= 3.14.

> Unofficial and reverse-engineered. Not endorsed by Flitsmeister. It can
> break when the firmware changes.

The protocol facts come from a decompilation of the Flitsmeister Android
app 15.1.1 and from the Dot firmware 1.0.14 bundled inside it. The wire
notes live in `PROTOCOL.md`.

## Install

```bash
uv add flitsmeister-dot-ble
```

## Usage

`FlitsmeisterDotClient` accepts an injected `BleTransport`. Tests can use
a fake transport without Bluetooth hardware.

```python
import asyncio

from bleak import BleakScanner

from flitsmeister_dot_ble import BleakTransport, FlitsmeisterDotClient


async def main() -> None:
    device = await BleakScanner.find_device_by_address("AA:BB:CC:DD:EE:FF")
    if device is None:
        raise SystemExit("Flitsmeister DOT not found")
    async with FlitsmeisterDotClient(BleakTransport(device)) as client:
        print(client.state)


asyncio.run(main())
```

Inside Home Assistant, pass the `BLEDevice` from
`bluetooth.async_ble_device_from_address` instead of scanning.
`BleakTransport` connects through
`bleak_retry_connector.establish_connection`, which sets its own timeout
for each attempt and retries a failed attempt.

`is_dot_advertisement(name, service_uuids)` returns True for the DOT
service UUID or the device name `FM DOT`.

`connect()` subscribes to the button, battery, charging and motion
characteristics, reads the device information, and returns once the
session is ready. Every decoded value updates `client.state` and is
passed to the optional `update_callback` as a `DotUpdate`. Button pushes
and releases arrive as `DotButtonEvent` values on the update. A
notification that fails to decode is logged as a warning and dropped,
the session stays up. A malformed value read during `connect()` raises
`DotProtocolError` and fails the connect.

`FlitsmeisterDotClient` takes these keyword-only options:

| Option | Default | Meaning |
| --- | --- | --- |
| `response_timeout_seconds` | 10 | limit for every transport call after the transport connect |
| `long_press_seconds` | 1.0 | seconds a button must be held before a `LONG_PRESS` event |

An invalid timing raises `DotValidationError`.

`DotState` holds the battery level in percent, the charging state, the
motion status and the device information. The serial number is kept both
as the raw hex bytes and as the UUID string the Flitsmeister app shows.
Both derive from the same read, the app hashes the raw bytes with MD5
into a version 3 UUID. The four settings mirror the last written value,
brightness and LED orientation are read back from the device, volume and
speech language are tracked locally after a write.

## Animations

`play_animation` writes one `DotAnimation` to the device. Build one with
the preset functions in the `animations` submodule, every named
animation the Flitsmeister app ships is there:

```python
from flitsmeister_dot_ble import animations

await client.play_animation(animations.speed_trap())
await client.play_animation(animations.progress(animations.DotColor.DANGER, 0.5))
```

The presets cover the alert catalog, speed trap, speed camera, average
speed check, traffic jam, police hotspot, roadworks, incidents, lane
closures, the emergency vehicles, railway crossings, both wrong way
alerts, approach progress, overspeed, the reporting hold, startup,
updating and both fade outs. `rateable=True`, the default, lets a
button press rate the alert on the device, like the app does. The
`DotAnimation` dataclass also builds custom packets: the type, color,
LED count, both sounds and the end behavior are all fields, and
`to_bytes` validates and encodes them.

A progression top to bottom animation that equals the last one played
is skipped, so repeated progress updates do not spam the device.

## Settings

| Method | Values |
| --- | --- |
| `set_volume` | `Volume.SILENT`, `LOW`, `NORMAL`, `HARD` |
| `set_brightness` | `Brightness.BRIGHTNESS_10` to `BRIGHTNESS_100` in steps of 10 |
| `set_led_orientation` | `LedOrientation.NORMAL`, `UPSIDE_DOWN` |
| `set_speech_language` | `SpeechLanguage.ENGLISH`, `DUTCH`, `GERMAN`, `FRENCH` |

Brightness and LED orientation are read back into the state after the
write. `read_settings` reads both without writing, the Flitsmeister app
reads them only after a write, so `connect()` leaves them unset. Every
method raises `DotNotReadyError` before the session is ready and
`DotConnectionError` after a failed session or a failed write.

## Buttons

Every button indication reaches the `update_callback` as a
`DotButtonEvent` with the raw `PUSHED` or `RELEASED` action. The client
also resolves the hold time: a release before `long_press_seconds`
emits an extra `SHORT_PRESS`, holding past it emits a `LONG_PRESS`
while the button is still down. The Flitsmeister app files a speed
trap report for a long press on the red button and a dangerous
situation report for the blue one, what happens after that is up to
the caller.

## Connection loss

The client detects a dropped link through the disconnect callback of the
transport. The DOT sends no traffic while it sleeps, so there is no
keepalive. When a session fails:

- `client.status` becomes `ConnectionStatus.DISCONNECTED`
- an optional `connection_lost_callback` receives the exception

Call `connect()` again to start a new session.

## Logging

The library logs under the `flitsmeister_dot_ble` logger. Dropped
notifications and session failures log as warnings. A failing update or
connection lost callback logs as an error with its traceback, as does a
notification that fails to process. Transport errors during teardown log
at debug level.

## Probe

`scripts/probe_dot.py` talks to a real DOT and captures traffic:

```bash
uv run python -m scripts.probe_dot --output capture.jsonl
```

It scans for the device name `FM DOT` or the DOT service UUID, connects
read-only, subscribes, reads the device information and records every
payload as newline-delimited JSON: `{"t": seconds, "dir": "rx" | "tx" |
"read", "chr": uuid, "hex": payload}`. The serial number is replaced
with a fixed fake value before anything is written or logged. Use
`--show-identities` to log real Bluetooth addresses, `--address` to pick
a device, `--scan-seconds` and `--capture-seconds` to tune the run, and
`--list-advertisements` to only scan. The `DOT_PROXY`, `DOT_NOISE_PSK`
and `DOT_DEVICE_ADDRESS` environment variables preset the matching
flags, and `--proxy` routes the scan and the connection through an
ESPHome Bluetooth proxy.

## Drive

`scripts/drive_dot_client.py` drives the library against a real DOT:

```bash
uv run python -m scripts.drive_dot_client
```

Read-only by default it prints every update as a JSON line. With
`--controls` it plays every animation preset and cycles the settings
once. That flag needs the local config file
`scripts/drive_dot_client.local.json` as confirmation, because the
device in range is the real thing. The config file is a JSON object
holding `proxy`, `noise_psk` and `address`, command line arguments win
over it.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup, the check gate and
the code style rules.

## Protocol

| Direction | Characteristic | Meaning |
| --- | --- | --- |
| in | `27831002` | button event, 2 bytes, one per button with 1 pushed and 2 released |
| in | `2A19` | battery level in percent |
| in | `2BED` | charging state at byte 2, 0 consuming, 1 charging, 2 done |
| in | `27831580` | motion, 0 parked, any other value driving |
| in | `2A29`, `2A24`, `2A25`, `2A26`, `2A28` | manufacturer, model, serial, firmware revision, software revision |

All custom characteristics live under the service
`27831530-33ee-9b9c-124d-109d6b0c0a91`. `PROTOCOL.md` holds the full
wire format, including the animation packets that land in the library
next.

## Roadmap

- Validate the animation presets against a real DOT with the drive script
- A Home Assistant custom integration on top of this library
