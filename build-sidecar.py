# -*- coding: utf-8 -*-
"""
Python Backend Sidecar Builder
Uses PyInstaller to bundle server/main.py into a standalone binary for Tauri
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

# Ensure stdout and stderr use UTF-8 on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parent
SERVER_MAIN = ROOT_DIR / "server" / "main.py"
BINARIES_DIR = ROOT_DIR / "src-tauri" / "binaries"

def get_target_triple():
    machine = platform.machine().lower()
    system = platform.system().lower()

    if system == "windows":
        return "x86_64-pc-windows-msvc"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        return "x86_64-apple-darwin"
    elif system == "linux":
        if machine in ("arm64", "aarch64"):
            return "aarch64-unknown-linux-gnu"
        return "x86_64-unknown-linux-gnu"
    return f"{machine}-{system}"

def main():
    target = get_target_triple()
    is_windows = platform.system().lower() == "windows"
    exe_suffix = ".exe" if is_windows else ""
    output_name = f"server-{target}"

    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Building Sidecar: {output_name}{exe_suffix} ===")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        output_name,
        "--distpath",
        str(BINARIES_DIR),
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols",
        "--hidden-import", "uvicorn.protocols.http",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.lifespan",
        "--hidden-import", "uvicorn.lifespan.on",
        str(SERVER_MAIN),
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, check=True)
    if res.returncode == 0:
        print(f"=== Build successful: {BINARIES_DIR / (output_name + exe_suffix)} ===")
    else:
        print("=== Build failed ===")
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
