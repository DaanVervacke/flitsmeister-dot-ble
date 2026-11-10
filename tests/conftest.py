"""Shared fixtures for the DOT test suite."""

from collections.abc import AsyncIterator

import pytest
from flitsmeister_dot_ble import FlitsmeisterDotClient

from .helpers import FakeTransport, make_client


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
async def connected_client(
    transport: FakeTransport,
) -> AsyncIterator[FlitsmeisterDotClient]:
    client = make_client(transport)
    await client.connect()
    yield client
    await client.disconnect()
