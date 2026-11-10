"""Drive the DOT library against a real device, read-only by default.

With ``--controls`` the script plays every animation preset and cycles
the settings once. The flag needs the local config file as
confirmation, because the flag changes the settings of a real device.
"""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from flitsmeister_dot_ble import (
    Brightness,
    DotColor,
    DotUpdate,
    FlitsmeisterDotClient,
    LedOrientation,
    Volume,
    __version__,
    animations,
)
from flitsmeister_dot_ble.transport_types import BleTransport

from scripts import _dot_common as common

_LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).resolve().with_name("drive_dot_client.local.json")


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Settings for one client run."""

    proxy: str | None
    noise_psk: str | None
    address: str | None
    output: Path | None
    scan_seconds: float
    duration: float
    pause_seconds: float
    controls: bool


def print_update(update: DotUpdate) -> None:
    """Print one update as a JSON line."""
    record = {
        "status": update.status.value,
        "characteristic": update.characteristic,
        "button": None
        if update.button is None
        else {
            "button": update.button.button.value,
            "action": update.button.action.name,
        },
        "state": common.state_record(update.state),
    }
    sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")


async def tour(client: FlitsmeisterDotClient, pause_seconds: float) -> None:
    """Play every preset and cycle the settings once."""
    await client.play_animation(animations.startup())
    await asyncio.sleep(1)
    presets = (
        animations.speed_trap(),
        animations.speed_cam(),
        animations.traffic_camera(),
        animations.avg_speed_check_start(),
        animations.avg_speed_check_end(),
        animations.traffic_jam_start(),
        animations.traffic_jam_end(),
        animations.police_hotspot(),
        animations.roadworks(),
        animations.ambulance(),
        animations.fire_truck(),
        animations.police(),
        animations.emergency_vehicle(),
        animations.railway_crossing(),
        animations.wrong_way_driving(),
        animations.wrong_way_driver(),
        animations.reporting(),
        animations.updating(),
    )
    for preset in presets:
        await client.play_animation(preset)
        await asyncio.sleep(pause_seconds)
    await client.play_animation(
        animations.incident(speech=animations.DotSound.SPEECH_ACCIDENT)
    )
    await asyncio.sleep(pause_seconds)
    await client.play_animation(
        animations.lane_closure(speech=animations.DotSound.SPEECH_LANE_CLOSED)
    )
    await asyncio.sleep(pause_seconds)
    for fraction in (0.25, 0.5, 0.75):
        await client.play_animation(
            animations.progress(color=DotColor.SPEED_TRAP, fraction=fraction)
        )
        await asyncio.sleep(max(pause_seconds, 0.2))
    await client.play_animation(animations.overspeed(fraction=0.75))
    await asyncio.sleep(pause_seconds)
    await client.play_animation(animations.brightness_sample())
    await asyncio.sleep(max(pause_seconds, 0.2))
    await client.play_animation(animations.orientation_sample())
    await asyncio.sleep(max(pause_seconds, 0.2))
    await client.play_animation(animations.fade_out_without_cut_off())
    await asyncio.sleep(pause_seconds)
    await client.play_animation(animations.fade_out())
    for volume in (Volume.SILENT, Volume.LOW, Volume.NORMAL, Volume.HARD):
        await client.set_volume(volume)
        await asyncio.sleep(max(pause_seconds, 0.1))
    await client.set_volume(Volume.NORMAL)
    await client.set_brightness(Brightness.BRIGHTNESS_10)
    await asyncio.sleep(max(pause_seconds, 0.1))
    await client.set_brightness(Brightness.BRIGHTNESS_100)
    await client.set_led_orientation(LedOrientation.UPSIDE_DOWN)
    await asyncio.sleep(max(pause_seconds, 0.1))
    await client.set_led_orientation(LedOrientation.NORMAL)


async def run(config: RunConfig, transport: BleTransport) -> None:
    """Connect, print every update and run the tour when requested."""
    async with FlitsmeisterDotClient(transport, update_callback=print_update) as client:
        if config.controls:
            await tour(client, config.pause_seconds)
        await asyncio.sleep(config.duration)
        _LOGGER.info("Final state %s", common.state_record(client.state))


async def connect_and_run(config: RunConfig) -> None:
    """Scan for the DOT and run the client against it."""
    with common.CaptureWriter(config.output) as writer:
        await common.run_with_dot(
            proxy=config.proxy,
            noise_psk=config.noise_psk,
            address=config.address,
            scan_seconds=config.scan_seconds,
            wrap=partial(common.CaptureTransport, capture=writer),
            body=partial(run, config),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--proxy")
    parser.add_argument("--noise-psk")
    parser.add_argument("--address")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--scan-seconds", type=float, default=60.0)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--pause-seconds", type=float, default=2.0)
    parser.add_argument(
        "--controls",
        action="store_true",
        help="Play every preset and cycle the settings, needs the config file",
    )
    return parser


def config_from_args(argv: Sequence[str] | None = None) -> RunConfig:
    """Parse the command line and fill the unset options from the config file.

    Raises:
        SystemExit: ``--controls`` was given without a config file, or
            the config file is not valid JSON or not a JSON object.
    """
    args = _parser().parse_args(argv)
    try:
        file_config = common.load_config(args.config)
    except ValueError as err:
        sys.stderr.write(f"{err}\n")
        raise SystemExit(2) from err
    if args.controls and not file_config:
        sys.stderr.write(
            f"--controls needs the local config file, create {args.config}\n"
        )
        raise SystemExit(2)
    return RunConfig(
        proxy=args.proxy or file_config.get("proxy"),
        noise_psk=args.noise_psk or file_config.get("noise_psk"),
        address=args.address or file_config.get("address"),
        output=args.output,
        scan_seconds=args.scan_seconds,
        duration=args.duration,
        pause_seconds=args.pause_seconds,
        controls=args.controls,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, run the client and return the exit code."""
    config = config_from_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(connect_and_run(config))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted\n")
        return 1
    except Exception as err:
        _LOGGER.warning("Drive failed: %s", err, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
