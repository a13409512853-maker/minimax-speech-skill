#!/usr/bin/env python3
"""Check public files for accidental secrets and optionally build a release ZIP."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = {"README.md", "AGENTS.md", "LICENSE", ".gitignore", "install.py",
          "skills", "tests", "tools", "docs", ".github", "RELEASE-MANIFEST.json"}
IGNORED = {".git", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}
FORBIDDEN_SUFFIX = {".dpapi", ".mp3", ".wav", ".flac", ".pcm", ".srt", ".vtt",
                    ".pyd", ".exe", ".dll"}
KEY = re.compile(rb"sk-(?:api-)?[A-Za-z0-9_-]{24,}")
USER_PATH = re.compile(rb"(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+|/[U]sers/[^/\s\"']+)")


def collect(root):
    result, problems = {}, []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORED for part in rel.parts) or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            problems.append(f"{rel.as_posix()}: symlink is not publishable")
            continue
        if not path.is_file():
            continue
        if rel.parts[0] not in PUBLIC:
            problems.append(f"{rel.as_posix()}: unexpected public file")
            continue
        if (path.name.startswith(".env") or path.suffix.lower() in FORBIDDEN_SUFFIX
                or path.name in {"runtime.json", "voices.json"}
                or (path.name.startswith("credentials.") and path.suffix != ".py")):
            problems.append(f"{rel.as_posix()}: local/private artifact")
            continue
        data = path.read_bytes()
        if KEY.search(data):
            problems.append(f"{rel.as_posix()}: credential-like value")
        if USER_PATH.search(data):
            problems.append(f"{rel.as_posix()}: personal absolute path")
        result[rel.as_posix()] = data
    manifest = result.pop("RELEASE-MANIFEST.json", None)
    if manifest:
        expected = json.loads(manifest)["files"]
        actual = {name: hashlib.sha256(data).hexdigest() for name, data in result.items()}
        if expected != actual:
            problems.append("RELEASE-MANIFEST.json: file hashes differ from release")
    required = {"README.md", "AGENTS.md", "LICENSE", ".gitignore", "install.py",
                "skills/minimax-speech/SKILL.md", "skills/minimax-speech/scripts/credentials.py"}
    for missing in sorted(required - result.keys()):
        problems.append(missing + ": required file missing")
    if problems:
        raise ValueError("\n".join(problems))
    return result


def build(root, destination):
    entries = collect(root)
    manifest = {"version": "1.0.0",
                "files": {name: hashlib.sha256(data).hexdigest()
                          for name, data in entries.items()}}
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError("Release ZIP already exists; choose a new filename.")
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries.items():
                archive.writestr("minimax-speech-skill/" + name, data)
            archive.writestr("minimax-speech-skill/RELEASE-MANIFEST.json",
                             json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(destination.suffix + ".sha256").write_text(
            digest + "  " + destination.name + "\n", encoding="ascii")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    manifest = build(ROOT, args.zip)
    print(json.dumps({"release_check": "passed", "public_file_count": len(manifest["files"]),
                      "zip": str(args.zip) if args.zip else None}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print("RELEASE CHECK FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
