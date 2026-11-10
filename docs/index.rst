flitsmeister-dot-ble
====================

Async Python library for the Flitsmeister DOT over Bluetooth Low
Energy. Requires Python 3.14 or newer.

The library is unofficial and reverse-engineered. It is not endorsed by
Flitsmeister and can break when the firmware changes.

Install
-------

.. code-block:: bash

   uv add flitsmeister-dot-ble

Usage
-----

:class:`~flitsmeister_dot_ble.FlitsmeisterDotClient` takes a
:class:`~flitsmeister_dot_ble.BleTransport`.
:class:`~flitsmeister_dot_ble.BleakTransport` wraps a Bleak ``BLEDevice``.
Tests can pass a fake transport instead.

.. code-block:: python

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

``connect()`` returns once the client subscribed to the button,
battery, charging and motion characteristics and read the device
information. The session is then
:attr:`~flitsmeister_dot_ble.ConnectionStatus.READY`.
A transport failure during ``connect()`` raises
:class:`~flitsmeister_dot_ble.DotConnectionError`, a timeout raises
:class:`~flitsmeister_dot_ble.DotTimeoutError`.
Every decoded value updates ``client.state`` and is passed to the
optional ``update_callback`` as a :class:`~flitsmeister_dot_ble.DotUpdate`.
Button pushes and releases arrive as
:class:`~flitsmeister_dot_ble.DotButtonEvent` values on the update,
with resolved short and long presses.

The keyword-only options ``response_timeout_seconds`` and
``long_press_seconds`` tune the timing. The :doc:`api` lists their
defaults. An invalid timing raises
:class:`~flitsmeister_dot_ble.DotValidationError`.

Connection loss
---------------

The client detects a dropped link through the disconnect callback of the
transport. The DOT sends no traffic while it sleeps, so there is no
keepalive. When a session fails:

- ``client.status`` becomes ``DISCONNECTED``
- the optional ``connection_lost_callback`` receives the exception

Call ``connect()`` again to start a new session.

.. toctree::
   :maxdepth: 2

   api
