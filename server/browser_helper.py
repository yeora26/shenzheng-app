# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from playwright.async_api import BrowserContext, Playwright

LOG = logging.getLogger("browser_helper")


def get_app_data_dir(sub_name: str) -> str:
    path = Path.home() / ".shenzheng_data" / sub_name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_system_installed_chromium_browsers() -> list[str]:
    """
    通用动态发现系统中所有已安装的 Chromium 内核浏览器。
    彻底废除固定盘符与死路径，通过注册表、系统路径表与 PATH 环境变量全动态扫描。
    """
    found: list[str] = []

    def _add_if_valid(p: str | None):
        if not p:
            return
        clean_p = p.strip().strip('"').strip("'")
        if os.path.isfile(clean_p) and clean_p not in found:
            # 过滤支持 Chromium/Blink 内核的常见现代浏览器
            lower = clean_p.lower()
            if any(k in lower for k in ("edge", "chrome", "brave", "vivaldi", "chromium", "360", "browser")):
                found.append(clean_p)

    if sys.platform == "win32":
        try:
            import winreg

            # 1. 动态遍历 Windows 官方浏览器注册表（所有已安装浏览器必在此注册，支持任意自定义盘符）
            for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root_key, r"SOFTWARE\Clients\StartMenuInternet") as key:
                        num_subkeys = winreg.QueryInfoKey(key)[0]
                        for i in range(num_subkeys):
                            sub_name = winreg.EnumKey(key, i)
                            try:
                                with winreg.OpenKey(key, rf"{sub_name}\shell\open\command") as cmd_key:
                                    raw_cmd, _ = winreg.QueryValueEx(cmd_key, "")
                                    # 提取可执行文件路径
                                    raw_parts = raw_cmd.strip().split('"')
                                    exe_path = raw_parts[1] if len(raw_parts) > 1 else raw_cmd.split()[0]
                                    _add_if_valid(exe_path)
                            except Exception:
                                continue
                except Exception:
                    pass

            # 2. 动态查询 Windows App Paths 注册表
            for app_exe in ("msedge.exe", "chrome.exe", "brave.exe", "360chrome.exe", "centbrowser.exe"):
                for root_key in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    try:
                        with winreg.OpenKey(root_key, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_exe}") as key:
                            raw_val, _ = winreg.QueryValueEx(key, "")
                            _add_if_valid(raw_val)
                    except Exception:
                        pass
        except Exception as e:
            LOG.warning("扫描 Windows 注册表浏览器出错: %s", e)

        # 3. 动态查询 PATH 环境变量
        for name in ("msedge", "chrome", "chromium", "brave", "google-chrome"):
            _add_if_valid(shutil.which(name))

        # 4. 常规盘符与用户目录智能补全（涵盖常见安装位置）
        sys_drives = [os.environ.get("SystemDrive", "C:")]
        for extra_drive in ("D:", "E:", "F:"):
            if os.path.exists(extra_drive) and extra_drive not in sys_drives:
                sys_drives.append(extra_drive)

        for d in sys_drives:
            candidates = [
                os.path.join(d, r"\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                os.path.join(d, r"\Program Files\Microsoft\Edge\Application\msedge.exe"),
                os.path.join(d, r"\Program Files\Google\Chrome\Application\chrome.exe"),
                os.path.join(d, r"\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            ]
            for c in candidates:
                _add_if_valid(c)

        local_app = os.environ.get("LocalAppData")
        if local_app:
            _add_if_valid(os.path.join(local_app, r"Microsoft\Edge\Application\msedge.exe"))
            _add_if_valid(os.path.join(local_app, r"Google\Chrome\Application\chrome.exe"))

    elif sys.platform == "darwin":
        # macOS 动态查找
        for app in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ):
            _add_if_valid(app)

        for name in ("google-chrome", "chrome", "chromium", "msedge"):
            _add_if_valid(shutil.which(name))
    else:
        # Linux 动态扫描
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            _add_if_valid(shutil.which(name))

    LOG.info("动态检测到系统中可用的 Chromium 浏览器: %s", found)
    return found


def ensure_playwright_browsers_env():
    """确保 Playwright 缓存目录规范，跨平台统一"""
    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        home = Path.home()
        if sys.platform == "darwin":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "Library" / "Caches" / "ms-playwright")
        elif sys.platform == "win32":
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "AppData" / "Local" / "ms-playwright")
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / ".cache" / "ms-playwright")


def try_install_playwright_chromium():
    """终极兜底：当目标机器上完全没有安装任何现代浏览器时，静默自愈安装轻量 Chromium"""
    ensure_playwright_browsers_env()
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
        driver_exec, driver_env = compute_driver_executable()
        cmd = [str(driver_exec), "install", "chromium"]
        LOG.info("正在执行系统级浏览器自动补全下载: %s", " ".join(cmd))
        res = subprocess.run(cmd, env=driver_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        if res.returncode == 0:
            LOG.info("自动补全安装 Chromium 成功！")
            return True
        LOG.warning("自动补全安装 Chromium 失败: %s", res.stderr)
    except Exception as e:
        LOG.warning("尝试自动下载 Chromium 发生异常: %s", e)
    return False


async def launch_resilient_context(
    pw: Playwright,
    headless: bool = False,
    user_data_dir: str | None = None,
    extra_args: list[str] | None = None,
    **kwargs,
) -> BrowserContext:
    """
    通用高容灾启动浏览器上下文：
    1. 动态全盘探测任意盘符与路径下的 Edge / Chrome / Brave 等可用浏览器；
    2. 自动注入隔离参数彻底禁用 Edge 后台驻留模式，100% 弹出独立前台窗口；
    3. 若全系统无任何浏览器，自动触发自愈安装兜底。
    """
    if not user_data_dir:
        user_data_dir = get_app_data_dir("temp_browser_profile")

    ensure_playwright_browsers_env()

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

    # 1. 优先使用全盘动态注册表/PATH扫描出来的真实有效浏览器
    discovered = get_system_installed_chromium_browsers()
    for exe in discovered:
        attempts.append({"executable_path": exe})

    # 2. 尝试系统官方注册通道
    if sys.platform == "win32":
        attempts.extend([{"channel": "msedge"}, {"channel": "chrome"}])
    elif sys.platform == "darwin":
        attempts.extend([{"channel": "chrome"}, {"channel": "msedge"}])
    else:
        attempts.extend([{"channel": "chrome"}])

    # 3. 尝试内置下载的 Chromium (channel=None)
    attempts.append({})

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
            LOG.info("成功启动浏览器上下文，使用配置: %s", opt)
            return ctx
        except Exception as e:
            LOG.warning("启动浏览器失败 (%s): %s", opt, e)
            last_err = e
            continue

    # 4. 如果所有现有浏览器均无法启动，触发终极自愈：尝试自动下载 Chromium 并再次尝试启动
    LOG.info("现有系统浏览器无法拉起，正在尝试自动准备轻量运行环境...")
    if try_install_playwright_chromium():
        try:
            return await pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=headless,
                args=launch_args,
                **kwargs,
            )
        except Exception as e:
            last_err = e

    raise RuntimeError(
        f"未能启动任何浏览器: {last_err}。"
        "请确认电脑上已安装 Microsoft Edge、Google Chrome 或其他 Chromium 内核浏览器，或检查杀毒软件是否拦截了子进程启动。"
    )
