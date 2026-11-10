"""Python library for the Flitsmeister DOT BLE device."""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _version

from . import animations
from .animations import (
    DotAnimation,
    DotAnimationType,
    DotColor,
    DotEnd,
    DotSound,
)
from .client import ConnectionLostCallback, FlitsmeisterDotClient, UpdateCallback
from .const import DEFAULT_LONG_PRESS_SECONDS, DEFAULT_RESPONSE_TIMEOUT_SECONDS
from .exceptions import (
    DotConnectionError,
    DotError,
    DotNotReadyError,
    DotProtocolError,
    DotRejectedError,
    DotTimeoutError,
    DotValidationError,
)
from .models import (
    Brightness,
    ButtonAction,
    ChargingState,
    ConnectionStatus,
    DotButton,
    DotButtonEvent,
    DotState,
    DotUpdate,
    LedOrientation,
    MotionStatus,
    SpeechLanguage,
    Volume,
)
from .protocol import is_dot_advertisement
from .transport import BleakTransport
from .transport_types import BleTransport, DisconnectedCallback, NotificationCallback

try:
    __version__ = _version("flitsmeister-dot-ble")
except _PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "DEFAULT_LONG_PRESS_SECONDS",
    "DEFAULT_RESPONSE_TIMEOUT_SECONDS",
    "BleTransport",
    "BleakTransport",
    "Brightness",
    "ButtonAction",
    "ChargingState",
    "ConnectionLostCallback",
    "ConnectionStatus",
    "DisconnectedCallback",
    "DotAnimation",
    "DotAnimationType",
    "DotButton",
    "DotButtonEvent",
    "DotColor",
    "DotConnectionError",
    "DotEnd",
    "DotError",
    "DotNotReadyError",
    "DotProtocolError",
    "DotRejectedError",
    "DotSound",
    "DotState",
    "DotTimeoutError",
    "DotUpdate",
    "DotValidationError",
    "FlitsmeisterDotClient",
    "LedOrientation",
    "MotionStatus",
    "NotificationCallback",
    "SpeechLanguage",
    "UpdateCallback",
    "Volume",
    "__version__",
    "animations",
    "is_dot_advertisement",
]
