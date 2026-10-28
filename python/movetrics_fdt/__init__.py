"""Python reference client for the Movetrics FDT controller (F1-3D force plates).

The core modules use only the standard library. The USB and BLE transports import pyserial and bleak only
when they open a link, so install the extras you need: 'movetrics-fdt[serial]' or 'movetrics-fdt[ble]'.
See README.md in this directory.
"""

from .ble_transport import BleTransport
from .client import FdtClient, SyncMode
from .cloud import CloudClient, CloudError
from .commands import IMPLEMENTED, NOT_IMPLEMENTED, Command, OmittedCommand
from .files import StudioRecording, read_studio_c3d, read_studio_csv, read_studio_details
from .errors import (
    FdtError,
    FrameError,
    NackError,
    ReplyTimeoutError,
    TransportError,
    UnsupportedCommandError,
)
from .frames import AckReply, FirmwareVersionReply, NackReply, encode_host_frame
from .serial_transport import SerialTransport
from .tcp_transport import TcpTransport
from .status import Status, StatusRecord, parse_status
from .stream import EventFrame, StreamFrame, SyncModeReply
from .vocabulary import Event, Gap, Sample, SampleConverter, plate_cop
from .transport import Transport

__version__ = "0.3.0"

__all__ = [
    "IMPLEMENTED",
    "NOT_IMPLEMENTED",
    "AckReply",
    "BleTransport",
    "CloudClient",
    "CloudError",
    "Command",
    "FdtClient",
    "FdtError",
    "FirmwareVersionReply",
    "FrameError",
    "NackError",
    "NackReply",
    "OmittedCommand",
    "ReplyTimeoutError",
    "SerialTransport",
    "TcpTransport",
    "Status",
    "StatusRecord",
    "StreamFrame",
    "EventFrame",
    "SyncModeReply",
    "Event",
    "Gap",
    "Sample",
    "SampleConverter",
    "SyncMode",
    "plate_cop",
    "StudioRecording",
    "Transport",
    "TransportError",
    "UnsupportedCommandError",
    "__version__",
    "encode_host_frame",
    "parse_status",
    "read_studio_c3d",
    "read_studio_csv",
    "read_studio_details",
]
