"""NOKOV XINGYING through NOKOV's own SDK library, experimental: force plates, markers and rigid bodies in Python.

NOKOV publishes its Linux SDK library, libnokov_sdk.so for x64, aarch64 and armhf, inside its ROS repositories on
GitHub (github.com/NOKOV-MOCAP, mocap_nokov under BSD-3-Clause). This module does not include it: give it the path
of your copy, NokovClient(server, library="...") or the environment variable MOVETRICS_NOKOV_SDK (docs/24).

Every build of the library exports a flat C interface that no header declares (CreateClient, Initialize,
SetDataCallback, ...: the client handle first, then the arguments of the C++ method of the same name; 2 for a NULL
handle). This module calls it with ctypes, with the data layouts of NOKOV's published header NokovSDKTypes.h
(version 1.3.0.12) declared again here. Before it connects, it writes a frame with known values, lets the library
copy it (XingYing_CopyFrame) and reads every field back: a library whose layout differs is refused.

The library runs in a child process (multiprocessing, spawn): a crash in it ends that process, not yours, and its
network threads end with it. Call NokovClient from code under `if __name__ == "__main__":`, as spawn requires.
Frames and force-plate samples cross over as dataclasses through a bounded queue; when the queue is full they are
dropped and counted (NokovClient.dropped), never silently.

Nothing is converted: positions in millimetres as XINGYING sends them (NOKOV's own drivers scale by 0.001); force
plate forces in the unit set in XINGYING (Force Units: N, kgf or lbf; the stream does not say which); the force
plate's point and free moment as the library gives them, since the header defines neither their units nor their
frame. arrival is time.monotonic() when the library handed the item over.

Status: written from the header; run against NOKOV's GitHub builds 2.5.51.57 and 2.5.53.12 (x64) without a XINGYING
server: loading, version, the layout check, a connection attempt that fails within the library's timeout, and a
clean shutdown. Not yet run against XINGYING.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import queue as queue_module
import signal
import time
from collections import deque
from collections.abc import AsyncIterator, Iterator
from ctypes import (CDLL, CFUNCTYPE, POINTER, Structure, Union, byref, c_bool, c_char, c_char_p, c_float, c_int, c_long,
                    c_longlong, c_short, c_ubyte, c_uint, c_void_p, cast)
from dataclasses import dataclass, fields
from typing import Any

ENV_LIBRARY = "MOVETRICS_NOKOV_SDK"
KNOWN_VERSIONS = frozenset({"2.5.51.57", "2.5.53.12"})  # the builds in NOKOV's GitHub repositories, checked here
VERBOSITY_NONE, VERBOSITY_INFO, VERBOSITY_WARNING, VERBOSITY_ERROR, VERBOSITY_DEBUG = range(5)

# NokovSDKTypes.h 1.3.0.12: model limits and descriptor types.
MAX_MODELS = 200
MAX_RIGIDBODIES = 1000
MAX_NAMELENGTH = 256
MAX_MARKERS = 200
MAX_RBMARKERS = 20
MAX_SKELETONS = 100
MAX_SKELRIGIDBODIES = 200
MAX_LABELED_MARKERS = 1000
MAX_UNLABELED_MARKERS = 1000
MAX_FORCEPLATES = 8
MAX_ANALOG_CHANNELS = 32
DESCRIPTOR_MARKERSET, DESCRIPTOR_RIGIDBODY, DESCRIPTOR_SKELETON, DESCRIPTOR_FORCEPLATE, DESCRIPTOR_MARKERSET_EX = range(5)

_Point = c_float * 3  # MarkerData: x, y, z


class _Marker(Structure):  # sMarker
    _fields_ = [("ID", c_int), ("x", c_float), ("y", c_float), ("z", c_float), ("size", c_float), ("params", c_short)]


class _MarkerSetData(Structure):  # sMarkerSetData
    _fields_ = [("szName", c_char * MAX_NAMELENGTH), ("nMarkers", c_int), ("Markers", POINTER(_Point))]


class _RigidBodyData(Structure):  # sRigidBodyData
    _fields_ = [("ID", c_int), ("x", c_float), ("y", c_float), ("z", c_float), ("qx", c_float), ("qy", c_float),
                ("qz", c_float), ("qw", c_float), ("nMarkers", c_int), ("Markers", POINTER(_Point)),
                ("MarkerIDs", POINTER(c_int)), ("MarkerSizes", POINTER(c_float)), ("MeanError", c_float),
                ("params", c_short)]


class _SkeletonData(Structure):  # sSkeletonData
    _fields_ = [("skeletonID", c_int), ("nRigidBodies", c_int), ("RigidBodyData", POINTER(_RigidBodyData))]


class _Frame(Structure):  # sFrameOfMocapData
    _fields_ = [("iFrame", c_int), ("nMarkerSets", c_int), ("MocapData", _MarkerSetData * MAX_MODELS),
                ("nOtherMarkers", c_int), ("OtherMarkers", POINTER(_Point)),
                ("nRigidBodies", c_int), ("RigidBodies", _RigidBodyData * MAX_RIGIDBODIES),
                ("nSkeletons", c_int), ("Skeletons", _SkeletonData * MAX_SKELETONS),
                ("nLabeledMarkers", c_int), ("LabeledMarkers", _Marker * MAX_LABELED_MARKERS),
                ("nAnalogdatas", c_int), ("Analogdata", c_float * MAX_ANALOG_CHANNELS),
                ("fLatency", c_float), ("Timecode", c_uint), ("TimecodeSubframe", c_uint),
                ("iTimeStamp", c_longlong), ("params", c_short)]


class _ForcePlateData(Structure):  # sForcePlateData
    _fields_ = [("Fxyz", c_float * 3), ("xyz", c_float * 3), ("Mfree", c_float)]


class _ForcePlates(Structure):  # sForcePlates
    _fields_ = [("iFrame", c_int), ("nForcePlates", c_int), ("ForcePlates", _ForcePlateData * MAX_FORCEPLATES)]


class _ServerDescription(Structure):  # sServerDescription
    _fields_ = [("HostPresent", c_bool), ("szHostComputerName", c_char * MAX_NAMELENGTH),
                ("HostComputerAddress", c_ubyte * 4), ("szHostApp", c_char * MAX_NAMELENGTH),
                ("HostAppVersion", c_ubyte * 4), ("NokovSDKVersion", c_ubyte * 4)]


class _MarkerSetDescription(Structure):  # sMarkerSetDescription
    _fields_ = [("szName", c_char * MAX_NAMELENGTH), ("nMarkers", c_int), ("szMarkerNames", POINTER(c_char_p))]


class _RigidBodyDescription(Structure):  # sRigidBodyDescription
    _fields_ = [("szName", c_char * MAX_NAMELENGTH), ("ID", c_int), ("parentID", c_int), ("offsetx", c_float),
                ("offsety", c_float), ("offsetz", c_float), ("qx", c_float), ("qy", c_float), ("qz", c_float),
                ("qw", c_float)]


class _SkeletonDescription(Structure):  # sSkeletonDescription
    _fields_ = [("szName", c_char * MAX_NAMELENGTH), ("skeletonID", c_int), ("nRigidBodies", c_int),
                ("RigidBodies", _RigidBodyDescription * MAX_SKELRIGIDBODIES)]


class _ForcePlateDescription(Structure):  # sForcePlateDescription
    _fields_ = [("ID", c_int), ("scale", c_int), ("fWidth", c_float), ("fLength", c_float),
                ("Position", c_float * 3), ("Electrical", c_float * 3), ("Orientation", (c_float * 3) * 3),
                ("fCalMat", (c_float * 8) * 8), ("fCorners", (c_float * 3) * 4), ("iPlateType", c_int),
                ("iChannelDataType", c_int), ("nChannels", c_int),
                ("szChannelNames", (c_char * MAX_NAMELENGTH) * MAX_ANALOG_CHANNELS)]


class _DescriptionData(Union):
    _fields_ = [("MarkerSetDescription", POINTER(_MarkerSetDescription)),
                ("RigidBodyDescription", POINTER(_RigidBodyDescription)),
                ("SkeletonDescription", POINTER(_SkeletonDescription)),
                ("ForcePlateDescription", POINTER(_ForcePlateDescription)),
                ("MarkerSetData", POINTER(_MarkerSetData))]


class _DataDescription(Structure):  # sDataDescription
    _fields_ = [("type", c_int), ("Data", _DescriptionData)]


class _DataDescriptions(Structure):  # sDataDescriptions
    _fields_ = [("nDataDescriptions", c_int), ("arrDataDescriptions", _DataDescription * MAX_MODELS)]


_DATA_CALLBACK = CFUNCTYPE(None, POINTER(_Frame), c_void_p)
_FORCE_PLATE_CALLBACK = CFUNCTYPE(None, POINTER(_ForcePlates), c_void_p)
_MESSAGE_CALLBACK = CFUNCTYPE(None, c_int, c_char_p)


class NokovSdkError(RuntimeError):
    """The NOKOV library could not be found, loaded or checked, or it refused a call."""


# --- What comes out: plain, picklable dataclasses ------------------------------------------------------------------

Point = tuple[float, float, float]


@dataclass(frozen=True)
class NokovLibrary:
    path: str
    version: str  # XingYing_GetVersion
    known_version: bool  # one of KNOWN_VERSIONS
    layout_problems: tuple[str, ...]  # empty when the copy test read every field back

    @property
    def layout_ok(self) -> bool:
        return not self.layout_problems


@dataclass(frozen=True)
class NokovServer:
    host_present: bool
    host_name: str
    host_address: str
    app: str
    app_version: str
    sdk_version: str


@dataclass(frozen=True)
class NokovMarker:
    id: int
    x: float
    y: float
    z: float
    size: float
    params: int


@dataclass(frozen=True)
class NokovRigidBody:
    id: int
    position: Point
    quaternion: tuple[float, float, float, float]  # qx, qy, qz, qw
    mean_error: float
    params: int
    markers: tuple[Point, ...] = ()
    marker_ids: tuple[int, ...] = ()
    marker_sizes: tuple[float, ...] = ()


@dataclass(frozen=True)
class NokovSkeleton:
    id: int
    bones: tuple[NokovRigidBody, ...]


@dataclass(frozen=True)
class NokovFrame:
    """One sFrameOfMocapData. timestamp is the header's "FrameGroup timestamp" (unit not stated); latency and params
    are "host defined"."""

    frame: int
    arrival: float
    timestamp: int
    timecode: int
    timecode_subframe: int
    latency: float
    params: int
    marker_sets: tuple[tuple[str, tuple[Point, ...]], ...]
    unlabeled_markers: tuple[Point, ...]
    rigid_bodies: tuple[NokovRigidBody, ...]
    skeletons: tuple[NokovSkeleton, ...]
    labeled_markers: tuple[NokovMarker, ...]
    analog: tuple[float, ...]
    clamped: tuple[str, ...] = ()  # counts beyond the header's limits, read up to the limit


@dataclass(frozen=True)
class NokovForcePlate:
    index: int  # position in the frame's list, from 0; the descriptions come in the same order
    force: Point  # Fxyz, in XINGYING's Force Units
    point: Point  # xyz, as the library gives it
    free_moment: float  # Mfree


@dataclass(frozen=True)
class NokovForcePlates:
    frame: int
    arrival: float
    plates: tuple[NokovForcePlate, ...]
    clamped: tuple[str, ...] = ()


@dataclass(frozen=True)
class NokovMessage:
    level: int  # the library's message id; -1 for this module's own notes
    text: str
    arrival: float


@dataclass(frozen=True)
class NokovForcePlateDescription:
    id: int
    scale: int
    width: float
    length: float
    position: Point
    electrical: Point
    orientation: tuple[Point, Point, Point]
    calibration_matrix: tuple[tuple[float, ...], ...]  # 8 x 8, for raw analog voltages only
    corners: tuple[Point, ...]  # 4 corners in plate coordinates, clockwise from +x,+y (the C3D convention)
    plate_type: int  # the C3D force plate type
    channel_data_type: int  # 0 calibrated force data, 1 raw analog voltages
    channel_names: tuple[str, ...]


@dataclass(frozen=True)
class NokovRigidBodyDescription:
    name: str
    id: int
    parent_id: int
    offset: Point
    quaternion: tuple[float, float, float, float]


@dataclass(frozen=True)
class NokovSkeletonDescription:
    name: str
    id: int
    bones: tuple[NokovRigidBodyDescription, ...]


@dataclass(frozen=True)
class NokovMarkerSetDescription:
    name: str
    marker_names: tuple[str, ...]


@dataclass(frozen=True)
class NokovDescriptions:
    marker_sets: tuple[NokovMarkerSetDescription, ...] = ()
    rigid_bodies: tuple[NokovRigidBodyDescription, ...] = ()
    skeletons: tuple[NokovSkeletonDescription, ...] = ()
    force_plates: tuple[NokovForcePlateDescription, ...] = ()
    other_types: tuple[int, ...] = ()  # descriptor types this module does not read (4, MarkerSetEx, ...)
    clamped: tuple[str, ...] = ()


# --- From the library's structures to dataclasses ------------------------------------------------------------------

def _text(raw: bytes | None) -> str:
    """Names from XINGYING: UTF-8, else GBK (Chinese Windows), else UTF-8 with replacement characters."""
    if not raw:
        return ""
    raw = raw.split(b"\0", 1)[0]
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def _version(parts: Any) -> str:
    return ".".join(str(int(part)) for part in parts)


def _count(value: int, limit: int, what: str, clamped: list[str]) -> int:
    if value < 0:
        clamped.append(f"{what}: {value} read as 0")
        return 0
    if value > limit:
        clamped.append(f"{what}: {value} read as {limit}, the header's limit")
        return limit
    return value


def _point(values: Any) -> Point:
    return (float(values[0]), float(values[1]), float(values[2]))


def _points(pointer: Any, count: int) -> tuple[Point, ...]:
    if count <= 0 or not pointer:
        return ()
    return tuple(_point(pointer[i]) for i in range(count))


def _rigid_body(body: _RigidBodyData, where: str, clamped: list[str]) -> NokovRigidBody:
    count = _count(body.nMarkers, MAX_RBMARKERS, f"{where} markers", clamped)
    return NokovRigidBody(
        id=int(body.ID), position=(float(body.x), float(body.y), float(body.z)),
        quaternion=(float(body.qx), float(body.qy), float(body.qz), float(body.qw)),
        mean_error=float(body.MeanError), params=int(body.params), markers=_points(body.Markers, count),
        marker_ids=tuple(int(body.MarkerIDs[i]) for i in range(count)) if body.MarkerIDs else (),
        marker_sizes=tuple(float(body.MarkerSizes[i]) for i in range(count)) if body.MarkerSizes else ())


def _frame_from_c(frame: _Frame, arrival: float) -> NokovFrame:
    clamped: list[str] = []
    sets = []
    for index in range(_count(frame.nMarkerSets, MAX_MODELS, "marker sets", clamped)):
        data = frame.MocapData[index]
        count = _count(data.nMarkers, MAX_MARKERS, f"marker set {index} markers", clamped)
        sets.append((_text(data.szName), _points(data.Markers, count)))
    others = _points(frame.OtherMarkers, _count(frame.nOtherMarkers, MAX_UNLABELED_MARKERS, "unlabeled markers", clamped))
    bodies = tuple(_rigid_body(frame.RigidBodies[i], f"rigid body {i}", clamped)
                   for i in range(_count(frame.nRigidBodies, MAX_RIGIDBODIES, "rigid bodies", clamped)))
    skeletons = []
    for index in range(_count(frame.nSkeletons, MAX_SKELETONS, "skeletons", clamped)):
        skeleton = frame.Skeletons[index]
        count = _count(skeleton.nRigidBodies, MAX_SKELRIGIDBODIES, f"skeleton {index} bones", clamped)
        bones = tuple(_rigid_body(skeleton.RigidBodyData[i], f"skeleton {index} bone {i}", clamped)
                      for i in range(count)) if skeleton.RigidBodyData else ()
        skeletons.append(NokovSkeleton(int(skeleton.skeletonID), bones))
    labeled = tuple(NokovMarker(int(m.ID), float(m.x), float(m.y), float(m.z), float(m.size), int(m.params))
                    for m in (frame.LabeledMarkers[i] for i in
                              range(_count(frame.nLabeledMarkers, MAX_LABELED_MARKERS, "labeled markers", clamped))))
    analog = tuple(float(frame.Analogdata[i])
                   for i in range(_count(frame.nAnalogdatas, MAX_ANALOG_CHANNELS, "analog values", clamped)))
    return NokovFrame(frame=int(frame.iFrame), arrival=arrival, timestamp=int(frame.iTimeStamp),
                      timecode=int(frame.Timecode), timecode_subframe=int(frame.TimecodeSubframe),
                      latency=float(frame.fLatency), params=int(frame.params), marker_sets=tuple(sets),
                      unlabeled_markers=others, rigid_bodies=bodies, skeletons=tuple(skeletons),
                      labeled_markers=labeled, analog=analog, clamped=tuple(clamped))


def _force_plates_from_c(plates: _ForcePlates, arrival: float) -> NokovForcePlates:
    clamped: list[str] = []
    count = _count(plates.nForcePlates, MAX_FORCEPLATES, "force plates", clamped)
    return NokovForcePlates(
        frame=int(plates.iFrame), arrival=arrival, clamped=tuple(clamped),
        plates=tuple(NokovForcePlate(i, _point(plates.ForcePlates[i].Fxyz), _point(plates.ForcePlates[i].xyz),
                                     float(plates.ForcePlates[i].Mfree)) for i in range(count)))


def _server_from_c(server: _ServerDescription) -> NokovServer:
    return NokovServer(host_present=bool(server.HostPresent), host_name=_text(server.szHostComputerName),
                       host_address=_version(server.HostComputerAddress), app=_text(server.szHostApp),
                       app_version=_version(server.HostAppVersion), sdk_version=_version(server.NokovSDKVersion))


def _rigid_body_description(item: _RigidBodyDescription) -> NokovRigidBodyDescription:
    return NokovRigidBodyDescription(_text(item.szName), int(item.ID), int(item.parentID),
                                     (float(item.offsetx), float(item.offsety), float(item.offsetz)),
                                     (float(item.qx), float(item.qy), float(item.qz), float(item.qw)))


def _descriptions_from_c(descriptions: _DataDescriptions) -> NokovDescriptions:
    clamped: list[str] = []
    marker_sets, bodies, skeletons, plates, other = [], [], [], [], []
    for index in range(_count(descriptions.nDataDescriptions, MAX_MODELS, "descriptions", clamped)):
        item = descriptions.arrDataDescriptions[index]
        kind = int(item.type)
        if kind == DESCRIPTOR_MARKERSET and item.Data.MarkerSetDescription:
            description = item.Data.MarkerSetDescription.contents
            count = _count(description.nMarkers, MAX_MARKERS, f"description {index} marker names", clamped)
            names = tuple(_text(description.szMarkerNames[i]) for i in range(count)) if description.szMarkerNames else ()
            marker_sets.append(NokovMarkerSetDescription(_text(description.szName), names))
        elif kind == DESCRIPTOR_RIGIDBODY and item.Data.RigidBodyDescription:
            bodies.append(_rigid_body_description(item.Data.RigidBodyDescription.contents))
        elif kind == DESCRIPTOR_SKELETON and item.Data.SkeletonDescription:
            skeleton = item.Data.SkeletonDescription.contents
            count = _count(skeleton.nRigidBodies, MAX_SKELRIGIDBODIES, f"description {index} bones", clamped)
            skeletons.append(NokovSkeletonDescription(_text(skeleton.szName), int(skeleton.skeletonID),
                                                      tuple(_rigid_body_description(skeleton.RigidBodies[i])
                                                            for i in range(count))))
        elif kind == DESCRIPTOR_FORCEPLATE and item.Data.ForcePlateDescription:
            plate = item.Data.ForcePlateDescription.contents
            count = _count(plate.nChannels, MAX_ANALOG_CHANNELS, f"description {index} channels", clamped)
            plates.append(NokovForcePlateDescription(
                id=int(plate.ID), scale=int(plate.scale), width=float(plate.fWidth), length=float(plate.fLength),
                position=_point(plate.Position), electrical=_point(plate.Electrical),
                orientation=(_point(plate.Orientation[0]), _point(plate.Orientation[1]), _point(plate.Orientation[2])),
                calibration_matrix=tuple(tuple(float(v) for v in row) for row in plate.fCalMat),
                corners=tuple(_point(row) for row in plate.fCorners),
                plate_type=int(plate.iPlateType), channel_data_type=int(plate.iChannelDataType),
                channel_names=tuple(_text(plate.szChannelNames[i].value) for i in range(count))))
        else:
            other.append(kind)
    return NokovDescriptions(tuple(marker_sets), tuple(bodies), tuple(skeletons), tuple(plates), tuple(other),
                             tuple(clamped))


# --- The library -----------------------------------------------------------------------------------------------------

_REQUIRED = ("CreateClient", "DestroyClient", "Initialize", "Uninitialize", "SetVerbosityLevel", "SetMessageCallback",
             "SetDataCallback", "SetForcePlateCallback", "WaitForForcePlateInit", "GetServerDescription",
             "GetDataDescriptions", "FreeDataDescriptions", "XingYing_GetVersion", "XingYing_CopyFrame",
             "XingYing_FreeFrame")


def library_path(library: str | os.PathLike[str] | None = None) -> str:
    """The library to use: the argument, else MOVETRICS_NOKOV_SDK."""
    path = os.fspath(library) if library is not None else os.environ.get(ENV_LIBRARY, "")
    if not path:
        raise NokovSdkError(f"give the path of NOKOV's libnokov_sdk.so (library=..., or the {ENV_LIBRARY} "
                            "environment variable); it is in NOKOV's GitHub repositories, for example "
                            "mocap_nokov/deps/nokov_sdk/lib/x64/libnokov_sdk.so")
    return path


def _load(path: str) -> CDLL:
    try:
        lib = CDLL(path)
    except OSError as error:
        raise NokovSdkError(f"cannot load {path}: {error}") from None
    missing = [name for name in _REQUIRED if not hasattr(lib, name)]
    if missing:
        raise NokovSdkError(f"{path} does not export {', '.join(missing)}: not a NOKOV SDK library this module knows")
    handle = c_void_p
    lib.CreateClient.argtypes, lib.CreateClient.restype = [POINTER(c_void_p)], c_int
    lib.DestroyClient.argtypes, lib.DestroyClient.restype = [handle], c_int
    lib.Initialize.argtypes, lib.Initialize.restype = [handle, c_char_p], c_int
    lib.Uninitialize.argtypes, lib.Uninitialize.restype = [handle], c_int
    lib.SetVerbosityLevel.argtypes, lib.SetVerbosityLevel.restype = [handle, c_int], None  # the method returns void
    lib.SetMessageCallback.argtypes, lib.SetMessageCallback.restype = [handle, _MESSAGE_CALLBACK], c_int
    lib.SetDataCallback.argtypes, lib.SetDataCallback.restype = [handle, _DATA_CALLBACK, c_void_p], c_int
    lib.SetForcePlateCallback.argtypes = [handle, _FORCE_PLATE_CALLBACK, c_void_p]
    lib.SetForcePlateCallback.restype = c_int
    lib.WaitForForcePlateInit.argtypes, lib.WaitForForcePlateInit.restype = [handle, c_long], c_int
    lib.GetServerDescription.argtypes = [handle, POINTER(_ServerDescription)]
    lib.GetServerDescription.restype = c_int
    lib.GetDataDescriptions.argtypes = [handle, POINTER(POINTER(_DataDescriptions))]
    lib.GetDataDescriptions.restype = c_int
    lib.FreeDataDescriptions.argtypes = [handle, POINTER(_DataDescriptions)]
    lib.FreeDataDescriptions.restype = c_int
    lib.XingYing_GetVersion.argtypes, lib.XingYing_GetVersion.restype = [POINTER(c_ubyte)], None
    lib.XingYing_CopyFrame.argtypes = [POINTER(_Frame), POINTER(_Frame)]
    lib.XingYing_CopyFrame.restype = c_int
    lib.XingYing_FreeFrame.argtypes, lib.XingYing_FreeFrame.restype = [POINTER(_Frame)], c_int
    return lib


def _library_version(lib: CDLL) -> str:
    parts = (c_ubyte * 4)()
    lib.XingYing_GetVersion(parts)
    return _version(parts)


def _test_frame() -> tuple[_Frame, list[Any]]:
    """A frame with a known value in every field the conversion reads, and the arrays it points to."""
    frame, keep = _Frame(), []
    frame.iFrame, frame.nMarkerSets = 4242, 1
    points = (_Point * 2)(_Point(1, 2, 3), _Point(4, 5, 6))
    frame.MocapData[0].szName, frame.MocapData[0].nMarkers = b"set0", 2
    frame.MocapData[0].Markers = cast(points, POINTER(_Point))
    others = (_Point * 1)(_Point(7, 8, 9))
    frame.nOtherMarkers, frame.OtherMarkers = 1, cast(others, POINTER(_Point))
    frame.nRigidBodies = 1
    body = frame.RigidBodies[0]
    body.ID, body.x, body.y, body.z = 11, 1.5, 2.5, 3.5
    body.qx, body.qy, body.qz, body.qw, body.MeanError, body.params = 0.125, 0.25, 0.375, 0.875, 0.5, 5
    body_points = (_Point * 2)(_Point(10, 11, 12), _Point(13, 14, 15))
    ids, sizes = (c_int * 2)(21, 22), (c_float * 2)(14.0, 15.0)
    body.nMarkers, body.Markers = 2, cast(body_points, POINTER(_Point))
    body.MarkerIDs, body.MarkerSizes = cast(ids, POINTER(c_int)), cast(sizes, POINTER(c_float))
    bones = (_RigidBodyData * 2)()
    bones[0].ID, bones[0].x, bones[1].ID, bones[1].x, bones[1].qw = 31, 31.5, 32, 32.5, 1.0
    frame.nSkeletons = 1
    frame.Skeletons[0].skeletonID, frame.Skeletons[0].nRigidBodies = 30, 2
    frame.Skeletons[0].RigidBodyData = cast(bones, POINTER(_RigidBodyData))
    frame.nLabeledMarkers = 2
    frame.LabeledMarkers[0] = _Marker(41, 1.0, 2.0, 3.0, 9.0, 1)
    frame.LabeledMarkers[1] = _Marker(42, 4.0, 5.0, 6.0, 9.5, 2)
    frame.nAnalogdatas = 3
    for k in range(3):
        frame.Analogdata[k] = 1.25 * (k + 1)
    frame.fLatency, frame.Timecode, frame.TimecodeSubframe = 0.0125, 123456, 7
    frame.iTimeStamp, frame.params = 1234567890123, 3
    keep += [points, others, body_points, ids, sizes, bones]
    return frame, keep


def _layout_problems(lib: CDLL) -> list[str]:
    """Copy a known frame with the library's XingYing_CopyFrame and compare every field read back."""
    source, keep = _test_frame()
    copy = _Frame()
    code = lib.XingYing_CopyFrame(byref(source), byref(copy))
    if code != 0:
        return [f"XingYing_CopyFrame returned {code}"]
    try:
        wrote, read = _frame_from_c(source, 0.0), _frame_from_c(copy, 0.0)
        return [f"{item.name}: wrote {getattr(wrote, item.name)!r}, the library copied {getattr(read, item.name)!r}"
                for item in fields(NokovFrame) if getattr(wrote, item.name) != getattr(read, item.name)]
    finally:
        lib.XingYing_FreeFrame(byref(copy))
        keep.clear()  # the source frame's arrays were needed until here


def _describe_library(path: str) -> tuple[CDLL, NokovLibrary]:
    lib = _load(path)
    version = _library_version(lib)
    return lib, NokovLibrary(path, version, version in KNOWN_VERSIONS, tuple(_layout_problems(lib)))


# --- The child process -----------------------------------------------------------------------------------------------

def _check_worker(path: str, out: Any) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        out.put(("library", _describe_library(path)[1]))
    except NokovSdkError as error:
        out.put(("error", str(error), None))
    except Exception as error:  # pragma: no cover - reported, not raised, across the process boundary
        out.put(("error", f"checking {path} failed: {error!r}", None))


def _client_worker(path: str, server: str, out: Any, stop: Any, options: dict[str, Any]) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # the parent decides when to stop
    # The queue is flushed when this process exits, so the last messages (an error, "stopped") arrive; the parent
    # reads until then, and ends the process if it does not finish.
    dropped = {"frames": 0, "force_plates": 0, "messages": 0}

    def put(item: Any, kind: str) -> None:
        try:
            out.put_nowait(item)
        except queue_module.Full:
            dropped[kind] += 1

    try:
        lib, library = _describe_library(path)
    except NokovSdkError as error:
        out.put(("error", str(error), None))
        return
    except Exception as error:  # pragma: no cover
        out.put(("error", f"loading {path} failed: {error!r}", None))
        return
    if library.layout_problems:
        out.put(("error", "the library's data layout differs from NokovSDKTypes.h 1.3.0.12: "
                 + "; ".join(library.layout_problems), library))
        return
    handle = c_void_p()
    code = lib.CreateClient(byref(handle))
    if code != 0 or not handle.value:
        out.put(("error", f"CreateClient returned {code}", library))
        return

    # Called on the library's threads: copy, enqueue, and let nothing escape into the library.
    @_MESSAGE_CALLBACK
    def on_message(level: int, text: bytes | None) -> None:
        try:
            put(NokovMessage(int(level), _text(text), time.monotonic()), "messages")
        except BaseException:  # pragma: no cover
            pass

    @_DATA_CALLBACK
    def on_frame(pointer: Any, _user: Any) -> None:
        try:
            if pointer:
                put(_frame_from_c(pointer.contents, time.monotonic()), "frames")
        except BaseException as error:  # pragma: no cover
            try:
                put(NokovMessage(-1, f"a frame could not be read: {error!r}", time.monotonic()), "messages")
            except BaseException:
                pass

    @_FORCE_PLATE_CALLBACK
    def on_force_plates(pointer: Any, _user: Any) -> None:
        try:
            if pointer:
                put(_force_plates_from_c(pointer.contents, time.monotonic()), "force_plates")
        except BaseException as error:  # pragma: no cover
            try:
                put(NokovMessage(-1, f"force plates could not be read: {error!r}", time.monotonic()), "messages")
            except BaseException:
                pass

    try:
        lib.SetVerbosityLevel(handle, int(options["verbosity"]))
        lib.SetMessageCallback(handle, on_message)
        lib.SetDataCallback(handle, on_frame, None)
        lib.SetForcePlateCallback(handle, on_force_plates, None)
        started = time.monotonic()
        code = lib.Initialize(handle, server.encode("utf-8"))
        if code != 0:
            out.put(("error", f"Initialize({server!r}) returned {code} after {time.monotonic() - started:.1f} s: no "
                     "XINGYING broadcasting there? Switch on the SDK in XINGYING's data broadcast panel and use the "
                     "address it shows", library))
            return
        description = _ServerDescription()
        server_info = _server_from_c(description) if lib.GetServerDescription(handle, byref(description)) == 0 else None
        pointer = POINTER(_DataDescriptions)()
        descriptions = None
        if lib.GetDataDescriptions(handle, byref(pointer)) == 0 and pointer:
            try:
                descriptions = _descriptions_from_c(pointer.contents)
            finally:
                lib.FreeDataDescriptions(handle, pointer)
        waited = options.get("wait_force_plates_ms")
        force_plate_init = None if waited is None else int(lib.WaitForForcePlateInit(handle, int(waited)))
        out.put(("ready", library, server_info, descriptions, force_plate_init))
        stop.wait()
    finally:
        lib.Uninitialize(handle)  # before DestroyClient, which only frees the memory
        lib.DestroyClient(handle)
        try:
            out.put(("stopped", dict(dropped)), timeout=2)
        except queue_module.Full:  # pragma: no cover
            pass


def _context() -> Any:
    return multiprocessing.get_context("spawn")


def check_library(library: str | os.PathLike[str] | None = None, timeout_s: float = 30.0) -> NokovLibrary:
    """Load the library in a child process, read its version and run the layout check. Raises NokovSdkError when it
    cannot be loaded; a differing layout is reported in layout_problems, not raised."""
    path = library_path(library)
    context = _context()
    out = context.Queue()
    process = context.Process(target=_check_worker, args=(path, out), daemon=True, name="nokov-sdk-check")
    process.start()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                message = out.get(timeout=0.2)
                break
            except queue_module.Empty:
                if not process.is_alive():  # a crash in the library ends the child without an answer
                    raise NokovSdkError(f"loading {path} ended the checking process (exit code {process.exitcode})") from None
                if time.monotonic() > deadline:
                    raise NokovSdkError(f"checking {path} gave no answer within {timeout_s:g} s") from None
    finally:
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    if message[0] == "error":
        raise NokovSdkError(message[1])
    return message[1]


class NokovClient:
    """XINGYING's SDK stream through NOKOV's library, in a child process (experimental; see the module docstring).

        if __name__ == "__main__":
            with NokovClient("10.1.1.198", library="libnokov_sdk.so") as nokov:
                print(nokov.server, nokov.descriptions.force_plates)
                for item in nokov.items():          # NokovFrame, NokovForcePlates or NokovMessage
                    ...

    server is the address XINGYING broadcasts on (its data broadcast panel; 10.1.1.198 by default). The library's own
    Initialize gives up after about 5 s when nothing answers; connect_timeout_s bounds the whole start. verbosity is
    passed to the library: its error messages (why a connection failed) come from VERBOSITY_ERROR on."""

    def __init__(self, server: str, *, library: str | os.PathLike[str] | None = None, connect_timeout_s: float = 30.0,
                 queue_size: int = 4096, verbosity: int = VERBOSITY_ERROR, wait_force_plates_ms: int | None = None):
        self.server_address = server
        self.library_path = library_path(library)
        self.connect_timeout_s, self.queue_size = connect_timeout_s, queue_size
        self._options = {"verbosity": verbosity, "wait_force_plates_ms": wait_force_plates_ms}
        self.library: NokovLibrary | None = None
        self.server: NokovServer | None = None
        self.descriptions: NokovDescriptions | None = None
        self.force_plate_init: int | None = None  # WaitForForcePlateInit's result, when asked for
        self.messages: deque[NokovMessage] = deque(maxlen=200)  # the library's messages before the stream
        self.dropped: dict[str, int] = {}
        self._process: Any = None
        self._queue: Any = None
        self._stop: Any = None
        self._closed = False

    def __enter__(self) -> NokovClient:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> NokovClient:
        if self._process is not None:
            return self
        context = _context()
        self._queue, self._stop = context.Queue(maxsize=self.queue_size), context.Event()
        self._process = context.Process(target=_client_worker, daemon=True, name="nokov-sdk",
                                        args=(self.library_path, self.server_address, self._queue, self._stop,
                                              self._options))
        self._process.start()
        deadline = time.monotonic() + self.connect_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._end()
                raise NokovSdkError(f"no answer from the NOKOV library within {self.connect_timeout_s:g} s")
            try:
                message = self._queue.get(timeout=min(remaining, 0.5))
            except queue_module.Empty:
                if not self._process.is_alive():
                    code = self._process.exitcode
                    self._end()
                    raise NokovSdkError(f"the NOKOV library's process ended (exit code {code}) before connecting") from None
                continue
            if isinstance(message, NokovMessage):
                self.messages.append(message)
            elif message[0] == "ready":
                _, self.library, self.server, self.descriptions, self.force_plate_init = message
                return self
            elif message[0] == "error":
                self.library = message[2]
                self._end()
                said = [item.text.strip() for item in self.messages if item.level >= VERBOSITY_ERROR and item.text.strip()]
                raise NokovSdkError(message[1] + (f" (the library said: {said[-1]})" if said else ""))

    def get(self, timeout: float | None = None) -> NokovFrame | NokovForcePlates | NokovMessage | None:
        """The next item, or None when nothing came within timeout seconds."""
        if self._process is None:
            raise NokovSdkError("the client is not open")
        try:
            item = self._queue.get(timeout=timeout)
        except queue_module.Empty:
            if not self._process.is_alive():
                raise NokovSdkError(f"the NOKOV library's process ended (exit code {self._process.exitcode})") from None
            return None
        if isinstance(item, tuple):
            if item[0] == "stopped":
                self.dropped = item[1]
                return None
            raise NokovSdkError(str(item[1]))
        return item

    def items(self) -> Iterator[NokovFrame | NokovForcePlates | NokovMessage]:
        """Everything XINGYING sends, in arrival order, until close()."""
        while not self._closed and self._process is not None:
            item = self.get(timeout=0.5)
            if item is not None:
                yield item

    async def aitems(self) -> AsyncIterator[NokovFrame | NokovForcePlates | NokovMessage]:
        """items() for asyncio code; the waiting happens in a worker thread."""
        loop = asyncio.get_running_loop()
        while not self._closed and self._process is not None:
            item = await loop.run_in_executor(None, self.get, 0.5)
            if item is not None:
                yield item

    def close(self) -> None:
        """Stop the stream: Uninitialize and DestroyClient in the child, then end it."""
        if self._process is None:
            self._closed = True
            return
        self._stop.set()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                item = self._queue.get(timeout=0.2)
            except queue_module.Empty:
                if not self._process.is_alive():
                    break
                continue
            if isinstance(item, tuple) and item[0] == "stopped":
                self.dropped = item[1]
                break
        self._end()

    def _end(self) -> None:
        process, self._process = self._process, None
        self._closed = True
        if process is None:
            return
        if self._stop is not None:
            self._stop.set()
        process.join(timeout=5)
        if process.is_alive():  # pragma: no cover - a library that does not return from Uninitialize
            process.terminate()
            process.join(timeout=5)
        if self._queue is not None:
            self._queue.cancel_join_thread()
            self._queue.close()


__all__ = ["ENV_LIBRARY", "KNOWN_VERSIONS", "NokovClient", "NokovDescriptions", "NokovForcePlate",
           "NokovForcePlateDescription", "NokovForcePlates", "NokovFrame", "NokovLibrary", "NokovMarker",
           "NokovMarkerSetDescription", "NokovMessage", "NokovRigidBody", "NokovRigidBodyDescription", "NokovSdkError",
           "NokovServer", "NokovSkeleton", "NokovSkeletonDescription", "check_library", "library_path"]
