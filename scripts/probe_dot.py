"""Developer probe that logs DOT traffic without sending writes."""

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from flitsmeister_dot_ble import (
    DotConnectionError,
    FlitsmeisterDotClient,
    __version__,
)

from scripts import _dot_common as common

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    """Settings for one probe run."""

    proxy: str | None
    noise_psk: str | None
    address: str | None
    output: Path | None
    scan_seconds: float
    capture_seconds: float
    list_advertisements: bool
    show_identities: bool


async def list_advertisements(config: ProbeConfig) -> None:
    """Log every advertisement seen during the scan window."""
    async with common.open_scanner(config.proxy, config.noise_psk) as scan:
        sightings = await scan(config.scan_seconds)
    for sighting in sightings:
        address = (
            sighting.device.address if config.show_identities else "DEVICE_ADDRESS"
        )
        _LOGGER.info(
            "ADVERTISEMENT address=%s name=%s rssi=%s dot=%s service_uuids=%s",
            address,
            sighting.name,
            sighting.rssi,
            sighting.is_dot,
            list(sighting.service_uuids),
        )
    _LOGGER.info("Advertisement scan complete, unique devices=%d", len(sightings))


async def capture(config: ProbeConfig) -> None:
    """Connect read-only and log every payload for the capture window.

    Retries the scan and connect cycle, because the DOT sleeps its
    advertising off between motion events.
    """
    with common.CaptureWriter(config.output) as writer:
        async with common.open_scanner(config.proxy, config.noise_psk) as scan:
            for attempt in range(1, common.CONNECT_ATTEMPTS + 1):
                device = await common.find_dot(
                    scan, config.address, config.scan_seconds
                )
                try:
                    async with common.background_scanner(config.proxy is None):
                        transport = common.CaptureTransport(
                            common.make_transport(device, config.proxy), writer
                        )
                        async with FlitsmeisterDotClient(transport) as client:
                            _LOGGER.info(
                                "Connected manufacturer=%s model=%s firmware=%s"
                                " software=%s",
                                client.state.manufacturer_name,
                                client.state.model_number,
                                client.state.firmware_revision,
                                client.state.software_revision,
                            )
                            await asyncio.sleep(config.capture_seconds)
                except DotConnectionError:
                    if attempt == common.CONNECT_ATTEMPTS:
                        raise
                    _LOGGER.warning("Connect attempt %d failed, rescanning", attempt)
                else:
                    return


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--proxy", default=os.getenv("DOT_PROXY"))
    parser.add_argument("--noise-psk", default=os.getenv("DOT_NOISE_PSK"))
    parser.add_argument("--address", default=os.getenv("DOT_DEVICE_ADDRESS"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--scan-seconds", type=float, default=10.0)
    parser.add_argument("--capture-seconds", type=float, default=30.0)
    parser.add_argument(
        "--list-advertisements",
        action="store_true",
        help="List every advertisement and do not connect",
    )
    parser.add_argument(
        "--show-identities",
        action="store_true",
        help="Show real Bluetooth addresses in the log",
    )
    return parser


def config_from_args(argv: Sequence[str] | None = None) -> ProbeConfig:
    """Parse the command line into a probe config."""
    args = _parser().parse_args(argv)
    return ProbeConfig(
        proxy=args.proxy,
        noise_psk=args.noise_psk,
        address=args.address,
        output=args.output,
        scan_seconds=args.scan_seconds,
        capture_seconds=args.capture_seconds,
        list_advertisements=args.list_advertisements,
        show_identities=args.show_identities,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse argv, run the probe and return the exit code."""
    config = config_from_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    run = list_advertisements if config.list_advertisements else capture
    try:
        asyncio.run(run(config))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted\n")
        return 1
    except Exception as err:
        _LOGGER.warning("Probe failed: %s", err, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
