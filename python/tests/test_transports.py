"""The USB and BLE transports, without hardware: pyserial and bleak are replaced by fakes.

Also checks the import rules: the core modules use only the standard library, and the two transports import
pyserial and bleak only inside functions, when a link opens.
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
import time
import types
import unittest
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest import mock

from movetrics_fdt.ble_transport import (
    RX_UUID,
    STATUS_UUID,
    TX_UUID,
    BleTransport,
    parse_status_line,
    require_uart_mode,
)
from movetrics_fdt.errors import TransportError
from movetrics_fdt.serial_transport import DEFAULT_BAUDRATE, SerialTransport

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PACKAGE_ROOT / "movetrics_fdt"
THIRD_PARTY_BY_FILE = {"files.py": {"ezc3d"}, "writers.py": {"ezc3d", "numpy"}, "lsl.py": {"pylsl"}, "serial_transport.py": {"serial"}, "ble_transport.py": {"bleak"}}
GOOD_STATUS = "v=1.3;fw=1.3.1.0;mode=UART;sub=0;mtu=23;lastFault=0"


def _imported_roots(path: Path, *, inside_functions: bool) -> set[str]:
    """Top-level names of the absolute imports in path, either outside or inside function bodies."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()

    def visit(node: ast.AST, in_function: bool) -> None:
        for child in ast.iter_child_nodes(node):
            nested = in_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if nested == inside_functions:
                if isinstance(child, ast.Import):
                    roots.update(alias.name.split(".")[0] for alias in child.names)
                elif isinstance(child, ast.ImportFrom) and child.level == 0 and child.module:
                    roots.add(child.module.split(".")[0])
            visit(child, nested)

    visit(tree, False)
    return roots


async def _drain(transport: AsyncIterator[bytes] | Any) -> list[bytes]:
    return [chunk async for chunk in transport]


async def _take(transport: AsyncIterator[bytes] | Any, count: int) -> list[bytes]:
    taken: list[bytes] = []
    async for chunk in transport:
        taken.append(chunk)
        if len(taken) == count:
            break
    return taken


class ImportRuleTests(unittest.TestCase):
    def test_every_module_imports_only_the_standard_library_and_its_own_extra(self) -> None:
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            with self.subTest(module=path.name):
                roots = _imported_roots(path, inside_functions=False) | _imported_roots(path, inside_functions=True)
                allowed = THIRD_PARTY_BY_FILE.get(path.name, set())
                self.assertEqual(roots - set(sys.stdlib_module_names) - allowed, set())

    def test_transports_import_their_extra_only_inside_functions(self) -> None:
        for file_name, extra in THIRD_PARTY_BY_FILE.items():
            with self.subTest(module=file_name):
                path = PACKAGE_DIR / file_name
                self.assertEqual(_imported_roots(path, inside_functions=False) & extra, set())
                self.assertEqual(_imported_roots(path, inside_functions=True) & extra, extra)

    def test_importing_the_package_loads_neither_pyserial_nor_bleak(self) -> None:
        code = (
            "import sys, movetrics_fdt, movetrics_fdt.client, movetrics_fdt.ble_transport, "
            "movetrics_fdt.serial_transport\n"
            "print(sorted(name for name in ('serial', 'bleak') if name in sys.modules))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PACKAGE_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        self.assertEqual(completed.stdout.strip(), "[]")


class StatusLineTests(unittest.TestCase):
    def test_parses_the_status_line_the_firmware_writes(self) -> None:
        line = (
            "v=1.3;fw=1.3.1.0;mode=UART;sub=1;mtu=247;lastFault=0;cmd=0;uart=0;ble=0;discard=0;"
            "queued=0;high=0;retry=0;stop=0;mbufwait=0;ota=none;trial=0"
        )
        fields = parse_status_line(line)
        self.assertEqual((fields["v"], fields["mode"], fields["sub"], fields["trial"]), ("1.3", "UART", "1", "0"))

    def test_a_piece_without_an_equals_sign_is_refused(self) -> None:
        with self.assertRaises(TransportError):
            parse_status_line("garbage")

    def test_an_empty_status_line_is_refused(self) -> None:
        with self.assertRaises(TransportError):
            parse_status_line("   ")

    def test_mode_uart_is_required(self) -> None:
        with self.assertRaises(TransportError) as raised:
            require_uart_mode({"v": "1.3", "mode": "ECHO"})
        self.assertIn("mode='ECHO'", str(raised.exception))
        with self.assertRaises(TransportError):
            require_uart_mode({"v": "1.3"})

    def test_older_version_string_is_accepted_when_mode_is_uart(self) -> None:
        require_uart_mode({"v": "1.0", "mode": "UART"})


class FakeSerialError(OSError):
    """Stands in for serial.SerialException."""


class FakeSerialPort:
    """Stands in for serial.Serial. It records its settings and the bytes written, and serves inbox.

    events lists, in order, every port, dtr and rts assignment and the open call. lines_at_open is the (dtr, rts)
    pair that open() saw.
    """

    created: list[FakeSerialPort] = []
    open_error: Exception | None = None

    def __init__(self, **settings: Any) -> None:
        self.settings = settings
        self._port: str | None = settings.get("port")
        self.is_open = False
        self.inbox = bytearray()
        self.written: list[bytes] = []
        self.events: list[tuple[str, object]] = []
        self.lines_at_open: tuple[bool, bool] | None = None
        self._dtr = True  # pyserial's defaults: SerialBase.__init__ sets both lines to True
        self._rts = True
        FakeSerialPort.created.append(self)

    @property
    def port(self) -> str | None:
        return self._port

    @port.setter
    def port(self, value: str | None) -> None:
        self.events.append(("port", value))
        self._port = value

    @property
    def dtr(self) -> bool:
        return self._dtr

    @dtr.setter
    def dtr(self, value: bool) -> None:
        self.events.append(("dtr", value))
        self._dtr = value

    @property
    def rts(self) -> bool:
        return self._rts

    @rts.setter
    def rts(self, value: bool) -> None:
        self.events.append(("rts", value))
        self._rts = value

    @property
    def in_waiting(self) -> int:
        return len(self.inbox)

    def open(self) -> None:
        self.events.append(("open", None))
        self.lines_at_open = (self._dtr, self._rts)
        if FakeSerialPort.open_error is not None:
            raise FakeSerialPort.open_error
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def read(self, size: int = 1) -> bytes:
        if not self.is_open:
            raise FakeSerialError("port is not open")
        if not self.inbox:
            time.sleep(0.005)  # a quiet port: pyserial waits for its timeout here
            return b""
        data = bytes(self.inbox[:size])
        del self.inbox[:size]
        return data

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise FakeSerialError("port is not open")
        self.written.append(bytes(data))
        return len(data)


def fake_serial_module() -> types.ModuleType:
    module = types.ModuleType("serial")
    module.Serial = FakeSerialPort  # type: ignore[attr-defined]
    module.SerialException = FakeSerialError  # type: ignore[attr-defined]
    module.EIGHTBITS = 8  # type: ignore[attr-defined]
    module.PARITY_NONE = "N"  # type: ignore[attr-defined]
    module.STOPBITS_ONE = 1  # type: ignore[attr-defined]
    return module


class SerialTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeSerialPort.created = []
        FakeSerialPort.open_error = None
        patcher = mock.patch.dict(sys.modules, {"serial": fake_serial_module()})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_rate_is_the_firmware_default(self) -> None:
        self.assertEqual(DEFAULT_BAUDRATE, 1_500_000)

    def test_constructor_rejects_an_empty_port_and_a_zero_rate(self) -> None:
        with self.assertRaises(ValueError):
            SerialTransport("")
        with self.assertRaises(ValueError):
            SerialTransport("/dev/ttyUSB0", baudrate=0)

    async def test_open_uses_1500000_8n1_without_flow_control(self) -> None:
        transport = SerialTransport("/dev/ttyUSB0")
        await transport.open()
        try:
            device = FakeSerialPort.created[-1]
            self.assertEqual(device.port, "/dev/ttyUSB0")
            self.assertTrue(device.is_open)
            self.assertEqual(device.settings["baudrate"], 1_500_000)
            self.assertEqual(device.settings["bytesize"], 8)
            self.assertEqual(device.settings["parity"], "N")
            self.assertEqual(device.settings["stopbits"], 1)
            for flag in ("xonxoff", "rtscts", "dsrdtr"):
                self.assertIs(device.settings[flag], False, flag)
        finally:
            await transport.close()

    async def test_open_clears_dtr_and_rts_before_the_port_is_opened(self) -> None:
        transport = SerialTransport("/dev/ttyUSB0")
        await transport.open()
        try:
            device = FakeSerialPort.created[-1]
            self.assertIsNone(device.settings["port"])  # serial.Serial() is built with no port
            self.assertEqual(device.lines_at_open, (False, False))
            self.assertEqual((device.dtr, device.rts), (False, False))
            self.assertEqual(
                device.events,
                [("dtr", False), ("rts", False), ("port", "/dev/ttyUSB0"), ("open", None)],
            )
        finally:
            await transport.close()

    async def test_writes_and_reads_bytes_and_ends_when_closed(self) -> None:
        transport = SerialTransport("/dev/ttyUSB0")
        await transport.open()
        device = FakeSerialPort.created[-1]
        await transport.write(b"\xfe\xed\x00")
        self.assertEqual(device.written, [b"\xfe\xed\x00"])
        device.inbox.extend(b"\xbe\xef\x01")
        first = await asyncio.wait_for(_take(transport, 1), 2.0)
        self.assertEqual(first, [b"\xbe\xef\x01"])
        await transport.close()
        self.assertEqual(await asyncio.wait_for(_drain(transport), 2.0), [])
        self.assertFalse(device.is_open)

    async def test_missing_pyserial_names_the_extra_to_install(self) -> None:
        with mock.patch.dict(sys.modules, {"serial": None}):
            with self.assertRaises(ImportError) as raised:
                await SerialTransport("/dev/ttyUSB0").open()
        self.assertIn("movetrics-fdt[serial]", str(raised.exception))

    async def test_a_port_that_cannot_be_opened_is_a_transport_error(self) -> None:
        FakeSerialPort.open_error = FakeSerialError("no such device")
        with self.assertRaises(TransportError) as raised:
            await SerialTransport("/dev/ttyNOPE").open()
        self.assertIn("no such device", str(raised.exception))

    async def test_write_before_open_is_refused(self) -> None:
        with self.assertRaises(TransportError):
            await SerialTransport("/dev/ttyUSB0").write(b"\x00")


class FakeCharacteristic:
    def __init__(self, uuid: str, properties: list[str]) -> None:
        self.uuid = uuid
        self.properties = properties


class FakeServices:
    def __init__(self, characteristics: list[FakeCharacteristic]) -> None:
        self._by_uuid = {characteristic.uuid: characteristic for characteristic in characteristics}

    def get_characteristic(self, specifier: str) -> FakeCharacteristic | None:
        return self._by_uuid.get(specifier)


class FakeDevice:
    def __init__(self, name: str, address: str) -> None:
        self.name = name
        self.address = address


class FakeBleakClient:
    """Stands in for bleak.BleakClient. It records each call in order; the class attributes set the scenario."""

    instances: list[FakeBleakClient] = []
    status_text = GOOD_STATUS
    characteristics: list[FakeCharacteristic] = []
    connect_error: Exception | None = None
    read_error: Exception | None = None
    services_error: Exception | None = None
    mtu = 23

    def __init__(self, device: object, *, disconnected_callback: Any = None, timeout: float = 10.0) -> None:
        self.device = device
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.calls: list[tuple[Any, ...]] = []
        self.notify_callback: Any = None
        self.is_connected = False
        self.mtu_size = FakeBleakClient.mtu
        FakeBleakClient.instances.append(self)

    @property
    def services(self) -> FakeServices:
        if FakeBleakClient.services_error is not None:
            raise FakeBleakClient.services_error
        return FakeServices(FakeBleakClient.characteristics)

    async def connect(self) -> None:
        if FakeBleakClient.connect_error is not None:
            raise FakeBleakClient.connect_error
        self.is_connected = True
        self.calls.append(("connect",))

    async def read_gatt_char(self, specifier: str) -> bytearray:
        self.calls.append(("read", specifier))
        if FakeBleakClient.read_error is not None:
            raise FakeBleakClient.read_error
        return bytearray(FakeBleakClient.status_text.encode("ascii"))

    async def start_notify(self, specifier: str, callback: Any) -> None:
        self.calls.append(("start_notify", specifier))
        self.notify_callback = callback

    async def write_gatt_char(self, specifier: str, data: bytes, response: bool = False) -> None:
        self.calls.append(("write", specifier, bytes(data), response))

    async def disconnect(self) -> None:
        self.calls.append(("disconnect",))
        self.is_connected = False


class FakeBleakScanner:
    found: dict[str, FakeDevice] = {}
    lookups: list[tuple[str, str]] = []

    @staticmethod
    async def find_device_by_name(name: str, timeout: float = 10.0) -> FakeDevice | None:
        FakeBleakScanner.lookups.append(("name", name))
        return FakeBleakScanner.found.get(name)

    @staticmethod
    async def find_device_by_address(address: str, timeout: float = 10.0) -> FakeDevice | None:
        FakeBleakScanner.lookups.append(("address", address))
        for device in FakeBleakScanner.found.values():
            if device.address == address:
                return device
        return None


def fake_bleak_module() -> types.ModuleType:
    module = types.ModuleType("bleak")
    module.BleakClient = FakeBleakClient  # type: ignore[attr-defined]
    module.BleakScanner = FakeBleakScanner  # type: ignore[attr-defined]
    return module


def standard_characteristics() -> list[FakeCharacteristic]:
    return [
        FakeCharacteristic(RX_UUID, ["write"]),
        FakeCharacteristic(TX_UUID, ["notify"]),
        FakeCharacteristic(STATUS_UUID, ["read"]),
    ]


class BleTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeBleakClient.instances = []
        FakeBleakClient.status_text = GOOD_STATUS
        FakeBleakClient.characteristics = standard_characteristics()
        FakeBleakClient.connect_error = None
        FakeBleakClient.read_error = None
        FakeBleakClient.services_error = None
        FakeBleakClient.mtu = 23
        FakeBleakScanner.found = {"Movetrics-BLE": FakeDevice("Movetrics-BLE", "AA:BB:CC:DD:EE:01")}
        FakeBleakScanner.lookups = []
        patcher = mock.patch.dict(sys.modules, {"bleak": fake_bleak_module()})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_open_reads_the_status_and_subscribes_before_any_write(self) -> None:
        transport = BleTransport("Movetrics-BLE")
        await transport.open()
        client = FakeBleakClient.instances[-1]
        self.assertEqual(client.calls, [("connect",), ("read", STATUS_UUID), ("start_notify", TX_UUID)])
        self.assertEqual(transport.bridge_status["mode"], "UART")
        await transport.write(b"\xfe\xed")
        self.assertEqual(client.calls[-1], ("write", RX_UUID, b"\xfe\xed", True))
        await transport.close()

    async def test_notifications_arrive_in_order_and_close_ends_the_iteration(self) -> None:
        transport = BleTransport("Movetrics-BLE")
        await transport.open()
        client = FakeBleakClient.instances[-1]
        client.notify_callback(None, bytearray(b"\xbe\xef"))
        client.notify_callback(None, bytearray(b"\x01\x02"))
        self.assertEqual(await asyncio.wait_for(_take(transport, 2), 2.0), [b"\xbe\xef", b"\x01\x02"])
        await transport.close()
        self.assertEqual(await asyncio.wait_for(_drain(transport), 2.0), [])
        self.assertIn(("disconnect",), client.calls)

    async def test_a_dropped_link_raises_in_the_reader(self) -> None:
        transport = BleTransport("Movetrics-BLE")
        await transport.open()
        client = FakeBleakClient.instances[-1]
        client.disconnected_callback(client)
        with self.assertRaises(TransportError) as raised:
            await asyncio.wait_for(_drain(transport), 2.0)
        self.assertIn("dropped", str(raised.exception))

    async def test_mode_other_than_uart_is_refused_and_the_link_is_dropped(self) -> None:
        FakeBleakClient.status_text = "v=1.3;fw=1.3.1.0;mode=ECHO;sub=0"
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("mode='ECHO'", str(raised.exception))
        client = FakeBleakClient.instances[-1]
        self.assertIn(("disconnect",), client.calls)
        self.assertNotIn(("start_notify", TX_UUID), client.calls)

    async def test_a_device_without_the_rx_characteristic_is_not_a_bridge(self) -> None:
        FakeBleakClient.characteristics = [c for c in standard_characteristics() if c.uuid != RX_UUID]
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("not a Movetrics bridge", str(raised.exception))

    async def test_rx_without_the_write_property_is_refused(self) -> None:
        FakeBleakClient.characteristics = [
            FakeCharacteristic(RX_UUID, ["notify"]),
            FakeCharacteristic(TX_UUID, ["notify"]),
            FakeCharacteristic(STATUS_UUID, ["read"]),
        ]
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("'write'", str(raised.exception))

    async def test_an_unknown_device_is_a_transport_error(self) -> None:
        with self.assertRaises(TransportError):
            await BleTransport("Nobody-Here").open()

    async def test_a_connect_failure_is_a_transport_error(self) -> None:
        FakeBleakClient.connect_error = OSError("link refused")
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("link refused", str(raised.exception))

    async def test_a_gatt_failure_after_connect_is_a_transport_error_and_the_link_is_dropped(self) -> None:
        FakeBleakClient.read_error = RuntimeError("characteristic read failed")
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("characteristic read failed", str(raised.exception))
        client = FakeBleakClient.instances[-1]
        self.assertIn(("disconnect",), client.calls)
        self.assertNotIn(("start_notify", TX_UUID), client.calls)

    async def test_service_discovery_failure_is_a_transport_error(self) -> None:
        FakeBleakClient.services_error = RuntimeError("Service Discovery has not been performed yet")
        with self.assertRaises(TransportError) as raised:
            await BleTransport("Movetrics-BLE").open()
        self.assertIn("Service Discovery", str(raised.exception))
        self.assertIn(("disconnect",), FakeBleakClient.instances[-1].calls)

    async def test_a_notification_after_the_event_loop_has_closed_is_dropped(self) -> None:
        transport = BleTransport("Movetrics-BLE")
        await transport.open()
        client = FakeBleakClient.instances[-1]
        await transport.close()
        closed_loop = asyncio.new_event_loop()
        closed_loop.close()
        transport._loop = closed_loop  # a late callback from bleak, after asyncio.run() has finished
        client.notify_callback(None, bytearray(b"\x00"))  # must not raise

    async def test_name_and_address_select_different_lookups(self) -> None:
        by_name = BleTransport("Movetrics-BLE")
        await by_name.open()
        await by_name.close()
        by_address = BleTransport("AA:BB:CC:DD:EE:01")
        await by_address.open()
        await by_address.close()
        self.assertEqual(
            FakeBleakScanner.lookups,
            [("name", "Movetrics-BLE"), ("address", "AA:BB:CC:DD:EE:01")],
        )

    async def test_long_writes_are_split_to_the_mtu_minus_three(self) -> None:
        FakeBleakClient.mtu = 23
        transport = BleTransport("Movetrics-BLE")
        await transport.open()
        await transport.write(bytes(range(45)))
        client = FakeBleakClient.instances[-1]
        writes = [call for call in client.calls if call[0] == "write"]
        self.assertEqual([len(call[2]) for call in writes], [20, 20, 5])
        self.assertTrue(all(call[3] is True for call in writes))
        self.assertEqual(b"".join(call[2] for call in writes), bytes(range(45)))
        await transport.close()

    async def test_missing_bleak_names_the_extra_to_install(self) -> None:
        with mock.patch.dict(sys.modules, {"bleak": None}):
            with self.assertRaises(ImportError) as raised:
                await BleTransport("Movetrics-BLE").open()
        self.assertIn("movetrics-fdt[ble]", str(raised.exception))

    async def test_write_before_open_is_refused(self) -> None:
        with self.assertRaises(TransportError):
            await BleTransport("Movetrics-BLE").write(b"\x00")


if __name__ == "__main__":
    unittest.main()
