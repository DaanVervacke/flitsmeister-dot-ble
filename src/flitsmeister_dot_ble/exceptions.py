"""Exceptions raised by the DOT client.

Every exception derives from ``DotError``. ``DotTimeoutError`` is also a
``TimeoutError`` and ``DotValidationError`` is also a ``ValueError``.
"""

__all__ = [
    "DotConnectionError",
    "DotError",
    "DotNotReadyError",
    "DotProtocolError",
    "DotRejectedError",
    "DotTimeoutError",
    "DotValidationError",
]


class DotError(Exception):
    """Base class for every error this library raises.

    Catch it to handle any DOT failure in one place.
    """


class DotConnectionError(DotError):
    """The session failed, or the transport dropped the link.

    When a transport error caused it, that error is chained as
    ``__cause__``.
    """


class DotTimeoutError(DotError, TimeoutError):
    """The DOT did not answer before the timeout."""


class DotProtocolError(DotError):
    """A payload is malformed or holds an unknown value."""


class DotRejectedError(DotError):
    """The DOT refused a write with a GATT error.

    The link stays up and the session stays ``READY``. The GATT error is
    chained as ``__cause__``.
    """


class DotValidationError(DotError, ValueError):
    """An argument is outside the supported range or has the wrong type."""


class DotNotReadyError(DotError):
    """A write or read method ran before the session is ``READY``."""
