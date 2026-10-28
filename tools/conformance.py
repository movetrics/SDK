#!/usr/bin/env python3
"""Run every client's test suite and write the conformance matrix (CONFORMANCE.md).

A client conforms to a vector file when its test suite reads that file and the suite passes. The matrix says, for
each shared file (vectors/*.json, the sync-event goldens, the K5 C3D fixture), which clients do, and what was
not run here (for example Kotlin, which needs the Android SDK). It never marks a file passed for a client whose
tests do not read it.

    python3 tools/conformance.py [--android PATH] [--write]

--write rewrites CONFORMANCE.md; without it the matrix is printed. Exit 1 when a suite that ran failed.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SDK = Path(__file__).resolve().parent.parent
SHARED = sorted(p.name for p in (SDK / "vectors").glob("*.json")) + ["sync_events.json", "k5_c3d_cop.json"]


def run(command: list[str], cwd: Path, timeout: int = 900) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    return done.returncode == 0, (done.stdout + done.stderr)[-4000:]


def files_read(test_dir: Path, patterns: tuple[str, ...]) -> set[str]:
    """Shared file names that a client's tests name (exact file name, so 'status' alone does not count)."""
    text = "\n".join(p.read_text(errors="ignore") for pattern in patterns for p in test_dir.rglob(pattern))
    found = {name for name in SHARED if name in text}
    # The Python byte-vector tests load every file listed in tests/support.py VECTOR_FILES.
    if "VECTOR_FILES" in text:
        support = (test_dir / "support.py").read_text()
        found |= {name for name in SHARED if name in support}
    return found


def python_client() -> dict:
    ok, log = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], SDK / "python")
    summary = re.findall(r"^(Ran \d+ tests.*|OK.*|FAILED.*)$", log, re.M)
    return {"name": "Python", "ran": True, "ok": ok, "summary": " ".join(summary[-2:]),
            "reads": files_read(SDK / "python" / "tests", ("*.py",))}


def typescript_client() -> dict:
    if not shutil.which("npm"):
        return {"name": "TypeScript", "ran": False, "why": "npm not installed", "reads": set()}
    ok, log = run(["npm", "test", "--silent"], SDK / "ts")
    passed = re.findall(r"^# pass (\d+)", log, re.M)
    failed = re.findall(r"^# fail (\d+)", log, re.M)
    return {"name": "TypeScript", "ran": True, "ok": ok,
            "summary": f"{passed[-1] if passed else '?'} pass, {failed[-1] if failed else '?'} fail",
            "reads": files_read(SDK / "ts" / "test", ("*.ts",))}


def matlab_client() -> dict:
    octave = shutil.which("octave") or shutil.which("octave-cli")
    if not octave:
        return {"name": "MATLAB (Octave)", "ran": False, "why": "GNU Octave not installed", "reads": set()}
    ok, log = run([octave, "--no-gui", "--quiet", "--eval", "run tests/run_tests.m"], SDK / "matlab")
    passed = re.findall(r"(\d+) checks passed", log)
    return {"name": "MATLAB (Octave)", "ran": True, "ok": ok and bool(passed),
            "summary": f"{passed[-1]} checks" if passed else log.strip().splitlines()[-1:] or "no output",
            "reads": files_read(SDK / "matlab" / "tests", ("*.m",))}


def kotlin_client(android: Path | None) -> dict:
    name = "Kotlin (Android fdt-core)"
    if android is None or not (android / "fdt-core").is_dir():
        return {"name": name, "ran": False, "why": "android checkout not given (--android)", "reads": set()}
    reads = files_read(android / "fdt-core" / "src" / "test", ("*.kt",))
    if not (os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")):
        return {"name": name, "ran": False, "why": "no Android SDK here; run where it is installed "
                "(./gradlew :fdt-core:testDebugUnitTest)", "reads": reads}
    ok, log = run(["./gradlew", ":fdt-core:testDebugUnitTest", "--console=plain"], android, timeout=1800)
    return {"name": name, "ran": True, "ok": ok, "summary": "BUILD SUCCESSFUL" if ok else "failed", "reads": reads}


def matrix(clients: list[dict]) -> str:
    today = datetime.date.today().isoformat()
    lines = [
        "# Conformance matrix",
        "",
        f"Written by `tools/conformance.py` on {today}. A client conforms to a file when its tests read the file "
        "and pass. \"not wired\" means the client's tests do not read that file yet: it may still decode those "
        "bytes, but nothing checks it against the shared vectors.",
        "",
        "| Client | Suite | Result |",
        "|---|---|---|",
    ]
    for c in clients:
        result = ("passed" if c["ok"] else "FAILED") + f" ({c['summary']})" if c["ran"] else f"not run: {c['why']}"
        lines.append(f"| {c['name']} | {'ran here' if c['ran'] else '-'} | {result} |")
    lines += ["", "| File | " + " | ".join(c["name"] for c in clients) + " |",
              "|---|" + "---|" * len(clients)]
    for name in SHARED:
        cells = []
        for c in clients:
            if name not in c["reads"]:
                cells.append("not wired")
            elif not c["ran"]:
                cells.append("wired, not run here")
            else:
                cells.append("pass" if c["ok"] else "FAIL")
        lines.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines += ["", "Simulated and recorded bytes only; no row here was run against a real FDT."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--android", type=Path, help="path to a the Movetrics firmware repository (private) checkout")
    parser.add_argument("--write", action="store_true", help="rewrite CONFORMANCE.md")
    args = parser.parse_args()
    clients = [python_client(), typescript_client(), matlab_client(), kotlin_client(args.android)]
    text = matrix(clients)
    if args.write:
        (SDK / "CONFORMANCE.md").write_text(text)
    print(text)
    return 1 if any(c["ran"] and not c["ok"] for c in clients) else 0


if __name__ == "__main__":
    sys.exit(main())
