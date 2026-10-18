#!/usr/bin/env python3
"""Install MiniMax Speech Skill, then report or start local credential setup."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parent
NAME = "minimax-speech"
SOURCE = ROOT / "skills" / NAME


def files(root):
    return {str(p.relative_to(root)).replace("\\", "/"):
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not any(
                x in {".venv", "__pycache__"} for x in p.relative_to(root).parts)}


def install(destination):
    if any(p.is_symlink() for p in SOURCE.rglob("*")):
        raise RuntimeError("Source symlinks are not supported.")
    if destination.is_symlink():
        raise RuntimeError("Destination is a symlink; inspect it before installing.")
    expected = files(SOURCE)
    if destination.exists():
        if not destination.is_dir() or files(destination) != expected:
            raise RuntimeError("Destination already exists with different files. "
                               "Keep a backup, inspect changes, then choose a new --dest. "
                               "No files were overwritten.")
        return "already_installed"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".minimax-install-", dir=destination.parent) as name:
        staged = Path(name) / NAME
        shutil.copytree(SOURCE, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
        if files(staged) != expected:
            raise RuntimeError("Install copy verification failed.")
        # rename refuses an existing nonempty destination instead of merging files.
        staged.rename(destination)
    return "installed"


def setup_runtime(destination):
    environment = destination / ".venv"
    executable = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if environment.is_symlink():
        raise RuntimeError("Runtime path is a symlink; inspect it before installing.")
    if not executable.is_file():
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(executable), "-m", "pip", "install", "--disable-pip-version-check",
                    "-r", str(destination / "requirements.txt")], check=True,
                   stdout=sys.stderr, stderr=sys.stderr)


def local_status(destination, no_deps):
    command = [sys.executable, "-X", "utf8", str(destination / "run.py"), "onboard", "--json"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")
    if result.returncode not in {0, 2, 3}:
        raise RuntimeError("Installed onboarding command failed; run <skill>/run.py onboard.")
    status = json.loads(result.stdout)
    status["runtime_dependencies"] = "skipped" if no_deps else "installed"
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument("--dest", type=Path, help="Parent skills folder; minimax-speech is appended")
    parser.add_argument("--no-deps", action="store_true",
                        help="Skip private venv and dependencies; HTTP/DPAPI still work on Windows")
    parser.add_argument("--non-interactive", action="store_true", help="Report setup state; never prompt")
    parser.add_argument("--json", action="store_true", help="JSON output; implies non-interactive")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required.")
    parent = args.dest or Path.home() / (".agents" if args.agent == "codex" else ".claude") / "skills"
    destination = parent.expanduser().absolute() / NAME
    result = install(destination)
    if not args.no_deps:
        setup_runtime(destination)
    setup = local_status(destination, args.no_deps)
    record = {"installation": result, "skill_directory": str(destination.resolve()),
              "credential": setup,
              "next_action": {
                  "ready": "ready_for_user_requested_generation",
                  "missing": "ask_user_to_configure_own_official_api_key",
                  "unavailable": "repair_local_credential_store",
              }[setup["status"]],
              "generation_performed": False}
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print("Skill installed: " + str(destination))
        print("Credential: " + setup["status"])
        if setup["status"] != "ready":
            print(setup.get("prompt") or setup.get("error"))
            print("Register: " + setup["registration_url"])
            print("Create API key: " + setup["api_key_url"])
            print("Tutorial: " + str(destination / "references/setup.md"))
        if not args.non_interactive and sys.stdin.isatty() and setup["status"] == "missing":
            print("Enter your own key below. Ctrl+C leaves setup pending.")
            code = subprocess.call([sys.executable, str(destination / "run.py"), "configure"])
            if code:
                print("Skill is installed; credential setup remains pending.")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print("INSTALL ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nSetup interrupted; no generation submitted.", file=sys.stderr)
        raise SystemExit(130)
