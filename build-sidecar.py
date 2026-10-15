# -*- coding: utf-8 -*-
"""
Python 后端 Sidecar 构建脚本
使用 PyInstaller 将 server/main.py 打包为 Tauri 所需的独立二进制文件
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

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

    print(f"=== 开始构建 Sidecar: {output_name}{exe_suffix} ===")

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
        "--collect-all", "playwright",
        str(SERVER_MAIN),
    ]

    print("执行命令:", " ".join(cmd))
    res = subprocess.run(cmd, check=True)
    if res.returncode == 0:
        print(f"=== 构建完成: {BINARIES_DIR / (output_name + exe_suffix)} ===")
    else:
        print("=== 构建失败 ===")
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
