"""Python library for the Flitsmeister DOT BLE device."""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

from .client import ConnectionLostCallback, FlitsmeisterDotClient, UpdateCallback
from .const import DEFAULT_RESPONSE_TIMEOUT_SECONDS
from .exceptions import (
    DotConnectionError,
    DotError,
    DotNotReadyError,
    DotProtocolError,
    DotTimeoutError,
    DotValidationError,
)
from .models import (
    ButtonAction,
    ChargingState,
    ConnectionStatus,
    DotButton,
    DotButtonEvent,
    DotState,
    DotUpdate,
    MotionStatus,
)
from .protocol import is_dot_advertisement
from .transport import BleakTransport
from .transport_types import BleTransport, DisconnectedCallback, NotificationCallback

try:
    __version__ = _version("flitsmeister-dot-ble")
except _PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "DEFAULT_RESPONSE_TIMEOUT_SECONDS",
    "BleTransport",
    "BleakTransport",
    "ButtonAction",
    "ChargingState",
    "ConnectionLostCallback",
    "ConnectionStatus",
    "DisconnectedCallback",
    "DotButton",
    "DotButtonEvent",
    "DotConnectionError",
    "DotError",
    "DotNotReadyError",
    "DotProtocolError",
    "DotState",
    "DotTimeoutError",
    "DotUpdate",
    "DotValidationError",
    "FlitsmeisterDotClient",
    "MotionStatus",
    "NotificationCallback",
    "UpdateCallback",
    "__version__",
    "is_dot_advertisement",
]
