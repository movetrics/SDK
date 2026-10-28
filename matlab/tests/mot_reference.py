"""Write Python's write_mot for a Studio -channels.csv, as the reference for tests/run_tests.m.

    python3 mot_reference.py STUDIO_CHANNELS_CSV OUT_MOT

Uses the SDK in sdk/python (not installed): the plate samples are the Studio columns, which are already in the plate
frame (docs/19), and write_mot runs with its defaults (no resampling, 20 N threshold).
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "python"))

from movetrics_fdt.files import read_studio_csv  # noqa: E402
from movetrics_fdt.writers import Recording, write_mot  # noqa: E402


def main() -> None:
    csv_path, out_path = sys.argv[1], sys.argv[2]
    studio = read_studio_csv(csv_path, details=False)
    columns = studio.columns
    plates = {}
    for plate in (1, 2):
        plates[plate] = {
            "fx": columns[f"p{plate}_ForceX"], "fy": columns[f"p{plate}_ForceY"], "fz": columns[f"p{plate}_ForceZ"],
            "mx": columns[f"p{plate}_MomentX"], "my": columns[f"p{plate}_MomentY"], "mz": columns[f"p{plate}_MomentZ"],
        }
    recording = Recording(studio.sample_rate_hz, studio.time_s, plates)
    write_mot(recording, out_path)


if __name__ == "__main__":
    main()
