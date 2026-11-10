API reference
=============

Import every name on this page from ``flitsmeister_dot_ble``, the
preset functions from ``flitsmeister_dot_ble.animations``.

Client
------

.. autoclass:: flitsmeister_dot_ble.FlitsmeisterDotClient
   :members:
   :special-members: __init__

Timing defaults
---------------

Default values of the ``FlitsmeisterDotClient`` options, in seconds.

.. autodata:: flitsmeister_dot_ble.const.DEFAULT_RESPONSE_TIMEOUT_SECONDS

.. autodata:: flitsmeister_dot_ble.const.DEFAULT_LONG_PRESS_SECONDS

Animations
----------

.. automodule:: flitsmeister_dot_ble.animations
   :members:

Settings
--------

.. autoclass:: flitsmeister_dot_ble.Volume
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.Brightness
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.LedOrientation
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.SpeechLanguage
   :members:
   :undoc-members:

Transports
----------

.. autoclass:: flitsmeister_dot_ble.BleTransport
   :members:

.. autoclass:: flitsmeister_dot_ble.BleakTransport
   :members:
   :special-members: __init__

State
-----

.. autoclass:: flitsmeister_dot_ble.DotState
   :members:

.. autoclass:: flitsmeister_dot_ble.DotUpdate
   :members:

.. autoclass:: flitsmeister_dot_ble.ConnectionStatus
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.DotButton
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.ButtonAction
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.DotButtonEvent
   :members:

.. autoclass:: flitsmeister_dot_ble.ChargingState
   :members:
   :undoc-members:

.. autoclass:: flitsmeister_dot_ble.MotionStatus
   :members:
   :undoc-members:

Callbacks
---------

.. autodata:: flitsmeister_dot_ble.transport_types.NotificationCallback

.. autodata:: flitsmeister_dot_ble.transport_types.DisconnectedCallback

.. autodata:: flitsmeister_dot_ble.client.UpdateCallback

.. autodata:: flitsmeister_dot_ble.client.ConnectionLostCallback

Advertisements
--------------

.. autofunction:: flitsmeister_dot_ble.is_dot_advertisement

Exceptions
----------

.. autoclass:: flitsmeister_dot_ble.DotError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotConnectionError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotNotReadyError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotProtocolError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotRejectedError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotTimeoutError
   :members:
   :show-inheritance:

.. autoclass:: flitsmeister_dot_ble.DotValidationError
   :members:
   :show-inheritance:
