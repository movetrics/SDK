# Python examples

Two scripts that use the reference client in `../../python`. They send only GET_STATUS, START_STREAM and
STOP_STREAM. They do not send KEEP_ALIVE, and they do not send any write, calibration, firmware or reset command.

They have not been run against a controller in this SDK. The checks here are `python3 -m py_compile` on each
script, and the package's own tests, which use a fake controller.

## Setup

From this directory, install the package in editable mode with the extra for your link:

    python3 -m pip install -e "../../python[serial]"   # USB, needs pyserial
    python3 -m pip install -e "../../python[ble]"      # BLE bridge, needs bleak

Python 3.10 or newer is required.

## read_stream.py: USB serial

    python3 read_stream.py /dev/ttyUSB0 --seconds 5 --show 10

Reads GET_STATUS, prints the serial settings the controller reports, starts the stream, prints the first
frames, and stops the stream after the given time. The first two frames of a stream carry timeStamp 0 and are
marked as placeholders. Port names: `/dev/ttyUSB0` or similar on Linux, `COM3` or similar on Windows. The
settings are 1,500,000 baud, 8N1, no flow control.

Stream values are wire integers. The vectors do not define their physical units.

## ble_status.py: BLE bridge

    python3 ble_status.py Movetrics-BLE
    python3 ble_status.py AA:BB:CC:DD:EE:FF

Connects to the bridge by advertised name or by address, prints the bridge status line, and prints one line
per GET_STATUS record. The transport refuses a bridge whose status line does not say `mode=UART`
(`../../docs/02-transports.md` section 2.6). A session that sent commands ends with the bridge writing STOP to the
controller (`../../docs/02-transports.md` section 2.5). Whether that stops a stream on hardware is item U8 there.

## Errors

Both scripts print the error and exit with status 1 for a client error, a missing extra, or an OS error.
Ctrl+C exits with status 130.
