"""USB transport: the FTDI FT232R on USART3, 1,500,000 baud, 8N1, no flow control.

Needs pyserial, which is imported when the port opens. Install it with:

    pip install 'movetrics-fdt[serial]'

The settings are in docs/02-transports.md section 2.1, and the default rate is HP_DEFAULT_BAUD_RATE
(the firmware). Blocking reads and writes run in worker threads through asyncio.to_thread, so the
event loop is never blocked.

pyserial asserts DTR and RTS when it opens a port unless they were cleared first, and this transport clears both
before the port opens. The Android override never sets either line
(android:app/src/main/java/com/movetrics/fdt/android/NoModemControlFtdiPort.java:9, 16-26), and
fdt:docs/architecture.md:44 says opening a port may affect modem lines. The bench effect is UNVERIFIED
(doc 02 item U5), so the first hardware run must check for reset-like behaviour.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any, Final

from .errors import TransportError
from .transport import Transport

DEFAULT_BAUDRATE: Final = 1_500_000  # HP_DEFAULT_BAUD_RATE, the firmware
READ_TIMEOUT_S: Final = 0.05  # the reader wakes this often, so close() is noticed quickly
WRITE_TIMEOUT_S: Final = 2.0

_INSTALL_HINT: Final = (
    "SerialTransport needs pyserial. Install it with: pip install 'movetrics-fdt[serial]'"
)


def _import_pyserial() -> Any:
    """Import pyserial on first use. The core package never imports it."""
    try:
        import serial
    except ImportError as error:
        raise ImportError(_INSTALL_HINT) from error
    return serial


class SerialTransport(Transport):
    """A USB serial link to the controller. FdtClient opens and closes it.

    port is the device name, for example /dev/ttyUSB0 on Linux or COM3 on Windows. The constructor does not
    touch the port, so a missing pyserial is reported by open(), not here.
    """

    def __init__(self, port: str, baudrate: int = DEFAULT_BAUDRATE) -> None:
        if not port:
            raise ValueError("port must name a serial device, for example /dev/ttyUSB0 or COM3")
        if baudrate <= 0:
            raise ValueError(f"baudrate must be positive, got {baudrate}")
        self._port = port
        self._baudrate = baudrate
        self._device: Any = None
        self._errors: tuple[type[BaseException], ...] = (OSError,)
        self._closing = False

    @property
    def port(self) -> str:
        """The device name given to the constructor."""
        return self._port

    @property
    def baudrate(self) -> int:
        """The line rate in bits per second."""
        return self._baudrate

    async def open(self) -> None:
        if self._device is not None:
            raise TransportError(f"{self._port} is already open")
        serial = _import_pyserial()
        device = serial.Serial(
            port=None,
            baudrate=self._baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=READ_TIMEOUT_S,
            write_timeout=WRITE_TIMEOUT_S,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        # DTR and RTS are cleared before the port opens. pyserial starts both at True and applies them when the port
        # opens (serialutil.py SerialBase.__init__, serialposix.py open()), so without these two lines both would be
        # asserted. The Android override never sets either line
        # (android:app/src/main/java/com/movetrics/fdt/android/NoModemControlFtdiPort.java:9, 16-26).
        # fdt:docs/architecture.md:44 says opening a port may affect modem lines. The bench effect is UNVERIFIED
        # (doc 02 item U5).
        device.dtr = False
        device.rts = False
        device.port = self._port
        try:
            await asyncio.to_thread(device.open)
        except (serial.SerialException, OSError) as error:
            raise TransportError(f"cannot open {self._port}: {error}") from error
        self._errors = (serial.SerialException, OSError)
        self._closing = False
        self._device = device

    async def write(self, data: bytes) -> None:
        device = self._require_open()
        payload = bytes(data)
        try:
            await asyncio.to_thread(device.write, payload)
        except self._errors as error:
            raise TransportError(f"write to {self._port} failed: {error}") from error

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._read_chunks()

    async def close(self) -> None:
        device, self._device = self._device, None
        if device is None:
            return
        self._closing = True
        with contextlib.suppress(*self._errors):
            await asyncio.to_thread(device.close)

    async def _read_chunks(self) -> AsyncIterator[bytes]:
        if self._device is None and self._closing:
            return  # closed: the iterator ends, as the Transport contract says
        device = self._require_open()
        while True:
            chunk = await asyncio.to_thread(self._read_once, device)
            if chunk is None:
                return
            if chunk:
                yield chunk

    def _read_once(self, device: Any) -> bytes | None:
        """Runs in a worker thread. Returns b"" on a quiet timeout and None once the port has been closed."""
        try:
            data: bytes = device.read(1)
            if data:
                waiting = int(device.in_waiting)
                if waiting:
                    data += device.read(waiting)
            return data
        except self._errors as error:
            if self._closing:
                return None
            raise TransportError(f"read from {self._port} failed: {error}") from error

    def _require_open(self) -> Any:
        if self._device is None:
            raise TransportError(f"{self._port} is not open; call open() first")
        return self._device
