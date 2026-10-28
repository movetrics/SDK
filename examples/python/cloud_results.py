"""Pull your Movetrics Cloud results and one recording's raw samples into Python.

    export MOVETRICS_TOKEN=mvt_...      (Cloud: Account > Access tokens; never put it in the script)
    python3 cloud_results.py --since 2026-10-01

Prints one line per result with its method and version, then the channels of the newest recording. Add
pandas yourself if you want a DataFrame: pandas.DataFrame(cloud.results()).
"""

from __future__ import annotations

import argparse
import os
import sys

from movetrics_fdt import CloudClient, CloudError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read results and samples from the Movetrics Cloud API.")
    parser.add_argument("--since", help="ISO date, for example 2026-10-01")
    parser.add_argument("--base-url", default="https://beta.movetrics.com/api/v1")
    args = parser.parse_args(argv)
    token = os.environ.get("MOVETRICS_TOKEN", "")
    try:
        cloud = CloudClient(token, args.base_url)
        print("reading as:", cloud.me()["workspace"])
        for row in cloud.results(since=args.since):
            print(row["recorded_at"][:10], row["movement"], row["label"], row["value"], row["unit"],
                  f'({row["method"]} {row["method_version"]}, engine {row["engine_version"]})')
        newest = next(cloud.recordings(since=args.since), None)
        if newest:
            samples = cloud.samples(newest["id"])
            print(newest["id"], f'{len(samples["time_s"])} samples:', ", ".join(samples["channels"]))
    except (CloudError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
