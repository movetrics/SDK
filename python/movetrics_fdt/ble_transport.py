"""BLE transport: the Movetrics BLE bridge (ESP32-S3, Nordic UART service), through bleak.

Needs bleak, which is imported when the link opens:

    pip install 'movetrics-fdt[ble]'

The bridge is a byte relay (docs/02-transports.md section 2.5). open() connects, checks the three
characteristics, reads the status line and requires mode=UART (section 2.6, step 8), and subscribes to TX.
Only after that does it write, because the bridge refuses a command sent before the subscription
(the firmware:115-117). Commands are written with response, because the
RX characteristic accepts only write-with-response (MovetricsBridge.ino:224-226; section 2.7).

When a session that sent commands ends, the bridge writes STOP to the controller (MovetricsBridge.ino:99;
section 2.5). Whether that stops a stream on hardware is doc 02 item U8.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

from .errors import TransportError
from .transport import Transport

SERVICE_UUID: Final = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"  # BridgeConfig.h:25
RX_UUID: Final = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # BridgeConfig.h:26; commands to the controller
TX_UUID: Final = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # BridgeConfig.h:27; controller output (notify)
STATUS_UUID: Final = "52e528e4-f391-4f88-a43a-3d911f82e040"  # BridgeConfig.h:29; status line (read)
DEVICE_NAME: Final = "Movetrics-BLE"  # BridgeConfig.h:22

DEFAULT_CONNECT_TIMEOUT_S: Final = 20.0  # a choice of this SDK; not a firmware value
SCAN_TIMEOUT_S: Final = 10.0  # the default scan time of bleak's find_device_by_name
ATT_DEFAULT_MTU: Final = 23  # the default ATT MTU of the Bluetooth Core specification
_ATT_WRITE_OVERHEAD: Final = 3  # the bytes MTU - 3 that carry a write payload (BridgeConfig.h:34)

_ADDRESS = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_UUID = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")

_INSTALL_HINT: Final = "BleTransport needs bleak. Install it with: pip install 'movetrics-fdt[ble]'"


def _import_bleak() -> Any:
    """Import bleak on first use. The core package never imports it."""
    try:
        import bleak
    except ImportError as error:
        raise ImportError(_INSTALL_HINT) from error
    return bleak


def parse_status_line(text: str) -> dict[str, str]:
    """Split the bridge status line into its fields, for example v=1.3;fw=...;mode=UART;sub=1;mtu=247;...

    The firmware writes the line in MovetricsBridge.ino:170-186. Empty pieces are ignored. A piece with no
    '=' raises TransportError, because the device is then not a Movetrics bridge.
    """
    fields: dict[str, str] = {}
    for piece in text.split(";"):
        if not piece.strip():
            continue
        key, separator, value = piece.partition("=")
        if not separator or not key.strip():
            raise TransportError(f"not a Movetrics bridge status line: {text!r}")
        fields[key.strip()] = value.strip()
    if not fields:
        raise TransportError("the bridge returned an empty status line")
    return fields


def require_uart_mode(fields: Mapping[str, str]) -> None:
    """Raise TransportError unless the bridge reports mode=UART (doc 02 section 2.6, step 8).

    The version is not checked, because an older build reports v=1.0 (doc 02 section 2.6).
    """
    mode = fields.get("mode")
    if mode != "UART":
        raise TransportError(
            f"the bridge reports mode={mode!r}; this transport needs mode=UART (doc 02 section 2.6)"
        )


def _write_chunk_size(client: Any) -> int:
    """Largest payload for one write request: the negotiated MTU minus 3, or the default MTU minus 3."""
    mtu = getattr(client, "mtu_size", None) or ATT_DEFAULT_MTU
    return max(1, int(mtu) - _ATT_WRITE_OVERHEAD)


class BleTransport(Transport):
    """A BLE link to the bridge, found by its advertised name (Movetrics-BLE) or by its address.

    name_or_address is treated as an address when it has the form of a MAC address (AA:BB:CC:DD:EE:FF) or of a
    UUID (the form macOS uses for devices), and as a name otherwise. FdtClient opens and closes the link.
    After open(), bridge_status holds the parsed status line.

    Writes are split into pieces of the negotiated MTU minus 3 bytes. The bridge relays bytes in order, so
    the split does not change the byte stream. Every command this package sends fits in one piece.
    """

    def __init__(self, name_or_address: str, *, connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_S) -> None:
        if not name_or_address:
            raise ValueError("name_or_address must not be empty")
        if connect_timeout <= 0:
            raise ValueError(f"connect_timeout must be positive, got {connect_timeout}")
        self._target = name_or_address
        self._connect_timeout = connect_timeout
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inbox: asyncio.Queue[bytes | None] | None = None
        self._failure: str | None = None
        self._closing = False
        self._status: dict[str, str] = {}

    @property
    def target(self) -> str:
        """The name or address given to the constructor."""
        return self._target

    @property
    def bridge_status(self) -> dict[str, str]:
        """The fields of the status line read by open(), for example {'v': '1.3', 'mode': 'UART', ...}."""
        return dict(self._status)

    async def open(self) -> None:
        if self._client is not None:
            raise TransportError(f"the BLE link to {self._target} is already open")
        bleak = _import_bleak()
        self._closing = False
        self._failure = None
        self._loop = asyncio.get_running_loop()
        self._inbox = asyncio.Queue()
        device = await self._find(bleak)
        try:
            client = bleak.BleakClient(
                device,
                disconnected_callback=self._on_disconnected,
                timeout=self._connect_timeout,
            )
            await client.connect()
        except Exception as error:
            raise TransportError(f"could not connect to {self._target}: {error}") from error
        try:
            self._check_characteristics(client)
            raw = await client.read_gatt_char(STATUS_UUID)
            fields = parse_status_line(bytes(raw).decode("ascii", errors="replace"))
            require_uart_mode(fields)
            await client.start_notify(TX_UUID, self._on_notify)
        except BaseException as error:
            with contextlib.suppress(Exception):
                await client.disconnect()
            if isinstance(error, TransportError) or not isinstance(error, Exception):
                raise
            # bleak raises BleakError (an Exception, not an OSError) for GATT failures; callers see one type.
            raise TransportError(f"could not set up the bridge at {self._target}: {error}") from error
        self._status = fields
        self._client = client

    async def write(self, data: bytes) -> None:
        client = self._require_open()
        payload = bytes(data)
        chunk = _write_chunk_size(client)
        try:
            for offset in range(0, len(payload), chunk):
                await client.write_gatt_char(RX_UUID, payload[offset : offset + chunk], response=True)
        except Exception as error:
            raise TransportError(f"BLE write to {self._target} failed: {error}") from error

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._read_chunks()

    async def close(self) -> None:
        client, self._client = self._client, None
        self._closing = True
        if self._inbox is not None:
            self._inbox.put_nowait(None)
        if client is not None:
            with contextlib.suppress(Exception):
                if client.is_connected:
                    await client.disconnect()

    async def _find(self, bleak: Any) -> Any:
        if _ADDRESS.fullmatch(self._target) or _UUID.fullmatch(self._target):
            lookup = bleak.BleakScanner.find_device_by_address
        else:
            lookup = bleak.BleakScanner.find_device_by_name
        try:
            device = await lookup(self._target, timeout=SCAN_TIMEOUT_S)
        except Exception as error:
            raise TransportError(f"BLE scan for {self._target!r} failed: {error}") from error
        if device is None:
            raise TransportError(
                f"no BLE device named or addressed {self._target!r} was found within {SCAN_TIMEOUT_S:g} s"
            )
        return device

    def _check_characteristics(self, client: Any) -> None:
        services = client.services
        required = ((RX_UUID, "write"), (TX_UUID, "notify"), (STATUS_UUID, "read"))
        for uuid, property_name in required:
            characteristic = services.get_characteristic(uuid)
            if characteristic is None:
                raise TransportError(f"{self._target} has no characteristic {uuid}: not a Movetrics bridge")
            if property_name not in characteristic.properties:
                raise TransportError(
                    f"characteristic {uuid} of {self._target} does not offer {property_name!r}"
                )

    async def _read_chunks(self) -> AsyncIterator[bytes]:
        inbox = self._inbox
        if inbox is None:
            raise TransportError(f"the BLE link to {self._target} is not open; call open() first")
        while True:
            chunk = await inbox.get()
            if chunk is None:
                inbox.put_nowait(None)  # keep the marker for any other reader
                if self._failure is not None:
                    raise TransportError(self._failure)
                return
            yield chunk

    def _on_notify(self, _characteristic: object, data: bytearray) -> None:
        # bleak may call this from a backend thread, so the queue is written on the event loop.
        self._post(bytes(data), None)

    def _on_disconnected(self, _client: object) -> None:
        self._post(None, f"the BLE link to {self._target} dropped")

    def _post(self, item: bytes | None, failure: str | None) -> None:
        loop, inbox = self._loop, self._inbox
        if loop is None or inbox is None:
            return
        try:
            loop.call_soon_threadsafe(self._deliver, inbox, item, failure)
        except RuntimeError:
            return  # the event loop has closed, so no reader is waiting for this callback

    def _deliver(self, inbox: asyncio.Queue[bytes | None], item: bytes | None, failure: str | None) -> None:
        if self._closing:
            return
        if failure is not None and self._failure is None:
            self._failure = failure
        inbox.put_nowait(item)

    def _require_open(self) -> Any:
        if self._client is None:
            raise TransportError(f"the BLE link to {self._target} is not open; call open() first")
        return self._client
