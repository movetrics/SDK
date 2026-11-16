"""NOKOV SDK client (experimental): the layouts, the conversions, and the library in a child process.

The layout and conversion tests need nothing. The library tests run when MOVETRICS_NOKOV_SDK names NOKOV's
libnokov_sdk.so (from github.com/NOKOV-MOCAP/mocap_nokov, deps/nokov_sdk/lib/x64); they need no XINGYING server.
"""

import ctypes
import ctypes.util
import os
import time
import unittest
from ctypes import POINTER, c_char_p, cast, sizeof

from movetrics_fdt import nokov_sdk
from movetrics_fdt.nokov_sdk import (NokovClient, NokovSdkError, _DataDescriptions, _ForcePlateDescription, _ForcePlates,
                                     _Frame, _MarkerSetDescription, _RigidBodyDescription, _ServerDescription,
                                     _SkeletonDescription, _descriptions_from_c, _force_plates_from_c, _frame_from_c,
                                     _server_from_c, _test_frame, _text, check_library, library_path)

LIBRARY = os.environ.get(nokov_sdk.ENV_LIBRARY, "")
SIXTY_FOUR_BIT = sizeof(ctypes.c_void_p) == 8

# Compiled from NOKOV's NokovSDKTypes.h 1.3.0.12 with g++ on x86-64 (sizeof and offsetof in a probe program).
HEADER_SIZES = {"_ForcePlateData": 28, "_ForcePlates": 232, "_ForcePlateDescription": 8584, "_Frame": 152208,
                "_RigidBodyData": 72, "_Marker": 24, "_MarkerSetData": 272, "_SkeletonData": 16, "_DataDescription": 16,
                "_DataDescriptions": 3208, "_ServerDescription": 525, "_RigidBodyDescription": 292,
                "_SkeletonDescription": 58664, "_MarkerSetDescription": 272}
HEADER_OFFSETS = {
    ("_ForcePlates", "nForcePlates"): 4, ("_ForcePlates", "ForcePlates"): 8,
    ("_ForcePlateDescription", "fCalMat"): 76, ("_ForcePlateDescription", "fCorners"): 332,
    ("_ForcePlateDescription", "iPlateType"): 380, ("_ForcePlateDescription", "szChannelNames"): 392,
    ("_Frame", "nOtherMarkers"): 54408, ("_Frame", "OtherMarkers"): 54416, ("_Frame", "nRigidBodies"): 54424,
    ("_Frame", "RigidBodies"): 54432, ("_Frame", "nSkeletons"): 126432, ("_Frame", "nLabeledMarkers"): 128040,
    ("_Frame", "LabeledMarkers"): 128044, ("_Frame", "nAnalogdatas"): 152044, ("_Frame", "Analogdata"): 152048,
    ("_Frame", "fLatency"): 152176, ("_Frame", "Timecode"): 152180, ("_Frame", "iTimeStamp"): 152192,
    ("_Frame", "params"): 152200, ("_RigidBodyData", "Markers"): 40, ("_RigidBodyData", "MeanError"): 64,
    ("_RigidBodyData", "params"): 68, ("_DataDescription", "Data"): 8, ("_DataDescriptions", "arrDataDescriptions"): 8,
}


@unittest.skipUnless(SIXTY_FOUR_BIT, "the header offsets were compiled for 64-bit")
class LayoutTests(unittest.TestCase):
    def test_sizes_and_offsets_match_the_compiled_header(self):
        for name, size in HEADER_SIZES.items():
            self.assertEqual(sizeof(getattr(nokov_sdk, name)), size, name)
        for (name, member), offset in HEADER_OFFSETS.items():
            self.assertEqual(getattr(getattr(nokov_sdk, name), member).offset, offset, f"{name}.{member}")


class ConversionTests(unittest.TestCase):
    def test_a_frame_with_every_part(self):
        frame, keep = _test_frame()
        item = _frame_from_c(frame, 12.5)
        self.assertEqual((item.frame, item.arrival, item.timestamp, item.timecode, item.timecode_subframe, item.params),
                         (4242, 12.5, 1234567890123, 123456, 7, 3))
        self.assertAlmostEqual(item.latency, 0.0125, places=6)
        self.assertEqual(item.marker_sets, (("set0", ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))),))
        self.assertEqual(item.unlabeled_markers, ((7.0, 8.0, 9.0),))
        body = item.rigid_bodies[0]
        self.assertEqual((body.id, body.position, body.quaternion, body.mean_error, body.params),
                         (11, (1.5, 2.5, 3.5), (0.125, 0.25, 0.375, 0.875), 0.5, 5))
        self.assertEqual((body.markers, body.marker_ids, body.marker_sizes),
                         (((10.0, 11.0, 12.0), (13.0, 14.0, 15.0)), (21, 22), (14.0, 15.0)))
        skeleton = item.skeletons[0]
        self.assertEqual((skeleton.id, [bone.id for bone in skeleton.bones], skeleton.bones[1].position[0]), (30, [31, 32], 32.5))
        self.assertEqual([(m.id, m.x, m.size, m.params) for m in item.labeled_markers], [(41, 1.0, 9.0, 1), (42, 4.0, 9.5, 2)])
        self.assertEqual(item.analog, (1.25, 2.5, 3.75))
        self.assertEqual(item.clamped, ())
        del keep

    def test_counts_beyond_the_header_limits_are_clamped_and_said(self):
        frame = _Frame()
        frame.nLabeledMarkers, frame.nAnalogdatas, frame.nRigidBodies, frame.nOtherMarkers = 5000, 40, -3, 7  # no array
        item = _frame_from_c(frame, 0.0)
        self.assertEqual((len(item.labeled_markers), len(item.analog), item.rigid_bodies, item.unlabeled_markers),
                         (1000, 32, (), ()))
        self.assertEqual(item.clamped, ("rigid bodies: -3 read as 0", "labeled markers: 5000 read as 1000, the header's limit",
                                        "analog values: 40 read as 32, the header's limit"))
        plates = _ForcePlates()
        plates.iFrame, plates.nForcePlates = 9, 12
        self.assertEqual(len(_force_plates_from_c(plates, 0.0).plates), 8)
        self.assertEqual(_force_plates_from_c(plates, 0.0).clamped, ("force plates: 12 read as 8, the header's limit",))

    def test_force_plates(self):
        plates = _ForcePlates()
        plates.iFrame, plates.nForcePlates = 77, 2
        for index, plate in enumerate(plates.ForcePlates[:2]):
            plate.Fxyz[:] = [1.0 + index, -2.0, 750.0]
            plate.xyz[:] = [100.0, 200.0 + index, 0.0]
            plate.Mfree = 0.25
        item = _force_plates_from_c(plates, 3.0)
        self.assertEqual((item.frame, item.arrival, len(item.plates)), (77, 3.0, 2))
        self.assertEqual((item.plates[1].index, item.plates[1].force, item.plates[1].point, item.plates[1].free_moment),
                         (1, (2.0, -2.0, 750.0), (100.0, 201.0, 0.0), 0.25))

    def test_descriptions_and_server(self):
        keep = []
        plate = _ForcePlateDescription()
        plate.ID, plate.scale, plate.fWidth, plate.fLength = 1, 1, 400.0, 600.0
        plate.Position[:] = [0.0, 300.0, 0.0]
        plate.Orientation[0][0] = plate.Orientation[1][1] = plate.Orientation[2][2] = 1.0
        plate.fCalMat[0][0], plate.fCalMat[7][7] = 2.5, 8.0
        plate.fCorners[0][:] = [200.0, 300.0, 0.0]
        plate.iPlateType, plate.iChannelDataType, plate.nChannels = 2, 0, 2
        plate.szChannelNames[0].value, plate.szChannelNames[1].value = b"Fx", "测力台1 Fz".encode("gbk")
        body = _RigidBodyDescription()
        body.szName, body.ID, body.parentID, body.offsety, body.qw = "刚体1".encode("utf-8"), 3, -1, 12.0, 1.0
        names = (c_char_p * 2)(b"LASI", b"RASI")
        markers = _MarkerSetDescription()
        markers.szName, markers.nMarkers, markers.szMarkerNames = b"all", 2, cast(names, POINTER(c_char_p))
        skeleton = _SkeletonDescription()
        skeleton.szName, skeleton.skeletonID, skeleton.nRigidBodies = b"body", 5, 1
        skeleton.RigidBodies[0].szName, skeleton.RigidBodies[0].ID = b"pelvis", 1
        descriptions = _DataDescriptions()
        descriptions.nDataDescriptions = 5
        for index, (kind, member, value) in enumerate([
                (nokov_sdk.DESCRIPTOR_MARKERSET, "MarkerSetDescription", markers),
                (nokov_sdk.DESCRIPTOR_RIGIDBODY, "RigidBodyDescription", body),
                (nokov_sdk.DESCRIPTOR_SKELETON, "SkeletonDescription", skeleton),
                (nokov_sdk.DESCRIPTOR_FORCEPLATE, "ForcePlateDescription", plate),
                (nokov_sdk.DESCRIPTOR_MARKERSET_EX, "MarkerSetData", None)]):
            descriptions.arrDataDescriptions[index].type = kind
            if value is not None:
                setattr(descriptions.arrDataDescriptions[index].Data, member, ctypes.pointer(value))
        keep += [names, markers, body, skeleton, plate]
        item = _descriptions_from_c(descriptions)
        self.assertEqual(item.marker_sets[0].name, "all")
        self.assertEqual(item.marker_sets[0].marker_names, ("LASI", "RASI"))
        self.assertEqual((item.rigid_bodies[0].name, item.rigid_bodies[0].id, item.rigid_bodies[0].parent_id,
                          item.rigid_bodies[0].offset), ("刚体1", 3, -1, (0.0, 12.0, 0.0)))
        self.assertEqual((item.skeletons[0].name, item.skeletons[0].id, item.skeletons[0].bones[0].name), ("body", 5, "pelvis"))
        fp = item.force_plates[0]
        self.assertEqual((fp.id, fp.width, fp.length, fp.position, fp.plate_type, fp.channel_data_type),
                         (1, 400.0, 600.0, (0.0, 300.0, 0.0), 2, 0))
        self.assertEqual((fp.calibration_matrix[0][0], fp.calibration_matrix[7][7], fp.corners[0], fp.orientation[1]),
                         (2.5, 8.0, (200.0, 300.0, 0.0), (0.0, 1.0, 0.0)))
        self.assertEqual(fp.channel_names, ("Fx", "测力台1 Fz"))  # GBK, as from Chinese Windows
        self.assertEqual(item.other_types, (nokov_sdk.DESCRIPTOR_MARKERSET_EX,))
        server = _ServerDescription()
        server.HostPresent, server.szHostComputerName, server.szHostApp = True, b"MOCAP-PC", b"XINGYING"
        server.HostComputerAddress[:], server.HostAppVersion[:], server.NokovSDKVersion[:] = [10, 1, 1, 198], [4, 7, 0, 0], [1, 3, 0, 12]
        self.assertEqual(_server_from_c(server), nokov_sdk.NokovServer(True, "MOCAP-PC", "10.1.1.198", "XINGYING", "4.7.0.0", "1.3.0.12"))

    def test_text(self):
        self.assertEqual(_text("跳跃".encode("utf-8")), "跳跃")
        self.assertEqual(_text("跳跃".encode("gbk")), "跳跃")
        self.assertEqual(_text(b"ab\0cd"), "ab")
        self.assertEqual(_text(None), "")
        self.assertEqual(_text(b"\xff\xfe\xfd"), "���")

    def test_a_missing_or_foreign_library_is_refused_plainly(self):
        saved = os.environ.pop(nokov_sdk.ENV_LIBRARY, None)
        try:
            with self.assertRaisesRegex(NokovSdkError, "MOVETRICS_NOKOV_SDK"):
                library_path()
            with self.assertRaisesRegex(NokovSdkError, "MOVETRICS_NOKOV_SDK"):
                NokovClient("10.1.1.198")
        finally:
            if saved is not None:
                os.environ[nokov_sdk.ENV_LIBRARY] = saved
        with self.assertRaisesRegex(NokovSdkError, "cannot load"):
            check_library(os.path.join(os.path.dirname(__file__), "no-such-library.so"))
        libc = ctypes.util.find_library("c") if os.name == "posix" else None
        if libc:
            with self.assertRaisesRegex(NokovSdkError, "does not export CreateClient"):
                check_library(libc)


@unittest.skipUnless(LIBRARY, "set MOVETRICS_NOKOV_SDK to NOKOV's libnokov_sdk.so (github.com/NOKOV-MOCAP/mocap_nokov)")
class LibraryTests(unittest.TestCase):
    def test_version_and_layout(self):
        library = check_library(LIBRARY)
        self.assertTrue(library.layout_ok, library.layout_problems)
        self.assertIn(library.version, nokov_sdk.KNOWN_VERSIONS)

    def test_no_server_is_refused_within_the_librarys_timeout_and_cleans_up(self):
        client = NokovClient("127.0.0.1", library=LIBRARY, connect_timeout_s=30, verbosity=nokov_sdk.VERBOSITY_DEBUG)
        started = time.monotonic()
        with self.assertRaisesRegex(NokovSdkError, r"Initialize\('127.0.0.1'\) returned 15"):
            client.open()
        self.assertLess(time.monotonic() - started, 20)
        self.assertIsNone(client._process)  # the child was joined
        self.assertTrue(client.library.layout_ok)
        self.assertTrue(any("Connection refused" in message.text for message in client.messages))
        client.close()  # closing again is harmless


if __name__ == "__main__":
    unittest.main()
