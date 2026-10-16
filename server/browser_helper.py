# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from playwright.async_api import BrowserContext, Playwright

LOG = logging.getLogger("browser_helper")


def get_app_data_dir(sub_name: str) -> str:
    path = Path.home() / ".shenzheng_data" / sub_name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def find_system_browser_executables() -> list[str]:
    """探测操作系统中真实存在的 Edge 和 Chrome 可执行文件路径"""
    executables = []
    if sys.platform == "win32":
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local_app = os.environ.get("LocalAppData", "")
        candidates = [
            os.path.join(prog_files_x86, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"Microsoft\Edge\Application\msedge.exe"),
            os.path.join(prog_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(prog_files_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app, r"Microsoft\Edge\Application\msedge.exe") if local_app else "",
            os.path.join(local_app, r"Google\Chrome\Application\chrome.exe") if local_app else "",
        ]
        for p in candidates:
            if p and os.path.isfile(p) and p not in executables:
                executables.append(p)
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
        for p in candidates:
            if os.path.isfile(p) and p not in executables:
                executables.append(p)
    return executables


async def launch_resilient_context(
    pw: Playwright,
    headless: bool = False,
    user_data_dir: str | None = None,
    extra_args: list[str] | None = None,
    **kwargs,
) -> BrowserContext:
    """
    以最大容灾能力启动浏览器上下文。
    彻底解决 Windows Edge 后台驻留模式导致无法拉起、以及 PyInstaller 单文件找不到 channel 的问题。
    """
    if not user_data_dir:
        user_data_dir = get_app_data_dir("temp_browser_profile")

    # 规范化浏览器缓存路径
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        home = Path.home()
        if sys.platform == "darwin":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "Library" / "Caches" / "ms-playwright")
        elif sys.platform == "win32":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "AppData" / "Local" / "ms-playwright")
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / ".cache" / "ms-playwright")

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeBackgroundMode",
        "--disable-infobars",
        "--lang=zh-CN",
    ]
    if extra_args:
        launch_args.extend(extra_args)

    attempts: list[dict] = []

    # 1. 优先通过系统实际存在的文件路径直接拉起（避开注册表查找失败）
    for exe in find_system_browser_executables():
        attempts.append({"executable_path": exe})

    # 2. 备选：通过 Playwright 官方通道识别
    if sys.platform == "win32":
        attempts.extend([{"channel": "msedge"}, {"channel": "chrome"}, {}])
    elif sys.platform == "darwin":
        attempts.extend([{"channel": "chrome"}, {"channel": "msedge"}, {}])
    else:
        attempts.extend([{"channel": "chrome"}, {}])

    last_err: Exception | None = None
    for opt in attempts:
        try:
            call_kwargs = dict(kwargs)
            call_kwargs.update(opt)
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                args=launch_args,
                **call_kwargs,
            )
            LOG.info("成功拉起浏览器上下文: %s", opt)
            return ctx
        except Exception as e:
            LOG.warning("尝试拉起浏览器失败 (%s): %s", opt, e)
            last_err = e
            continue

    raise RuntimeError(
        f"未能启动任何可用浏览器: {last_err}。"
        "请确认电脑上已安装 Microsoft Edge 浏览器或 Google Chrome 浏览器。"
    )
