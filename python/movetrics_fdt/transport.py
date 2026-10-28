"""The byte pipe between the client and the controller (USB serial or the BLE bridge)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class Transport(ABC):
    """A duplex byte link. Writes go to the controller, and received chunks come out of the async iterator.

    Chunk boundaries have no meaning: the client joins them. The iterator ends when the link closes.
    """

    async def open(self) -> None:
        """Prepare the link. FdtClient calls this on entry. The default does nothing."""

    @abstractmethod
    async def write(self, data: bytes) -> None:
        """Send bytes to the controller."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield received chunks until the link closes."""

    @abstractmethod
    async def close(self) -> None:
        """Release the link. Calling it again does nothing."""
