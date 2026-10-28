"""Exception types raised by movetrics_fdt."""

from __future__ import annotations


class FdtError(Exception):
    """Base class for every error raised by this package."""


class FrameError(FdtError):
    """A frame could not be built or parsed.

    reason is a short code such as crc_mismatch, bad_header or early_04_04_delimiter.
    would_be holds the frame that an encoder refused to send, when there is one.
    """

    def __init__(self, reason: str, message: str = "", *, would_be: bytes | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.would_be = would_be


class UnsupportedCommandError(FdtError):
    """The command is listed in NOT_IMPLEMENTED, so this package does not build it."""

    def __init__(self, command: int, reason: str) -> None:
        super().__init__(f"command 0x{command:02X} is not implemented by this client: {reason}")
        self.command = command
        self.reason = reason


class NackError(FdtError):
    """The controller refused a command with NACK."""

    def __init__(self, command: int, error_code: int, error_name: str) -> None:
        super().__init__(
            f"controller NACK {error_code} ({error_name}) for command 0x{command:02X}"
        )
        self.command = command
        self.error_code = error_code
        self.error_name = error_name


class ReplyTimeoutError(FdtError):
    """No reply arrived before the client's timeout."""


class TransportError(FdtError):
    """The byte link failed or was closed."""
