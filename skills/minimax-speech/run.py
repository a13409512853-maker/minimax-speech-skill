#!/usr/bin/env python3
"""Run the skill with its private Python environment when installed."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    environment = ROOT / ".venv"
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not executable.is_file():
        executable = Path(sys.executable)
    result = subprocess.run([str(executable), "-X", "utf8",
                             str(ROOT / "scripts/minimax_speech.py"), *sys.argv[1:]])
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
