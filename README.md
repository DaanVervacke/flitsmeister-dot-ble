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

`FlitsmeisterDotClient` takes this keyword-only option, in seconds:

| Option | Default | Meaning |
| --- | --- | --- |
| `response_timeout_seconds` | 10 | limit for every transport call after the transport connect |

An invalid timing raises `DotValidationError`.

`DotState` holds the battery level in percent, the charging state, the
motion status and the device information. The serial number is kept both
as the raw hex bytes and as the UUID string the Flitsmeister app shows.
Both derive from the same read, the app hashes the raw bytes with MD5
into a version 3 UUID.

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

- Animation writes with the full preset catalog from the Flitsmeister app
- Short and long press resolution on the button events
- Volume, brightness, LED rotation and speech language settings
- A drive script that triggers every preset against a real DOT
