# -*- coding: utf-8 -*-
"""
小红书 (xiaohongshu.com) 爬虫模块
基于 Playwright + 反爬特征抹除 + 接口拦截
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError

try:
    from models import CrawlResponse, Post
    from browser_helper import launch_resilient_context
except ImportError:
    from server.models import CrawlResponse, Post
    from server.browser_helper import launch_resilient_context

LOG = logging.getLogger("xhs")

class CrawlError(Exception):
    """小红书抓取业务异常"""
    pass


# 默认持久化 Profile 目录（保存在用户主目录 .shenzheng_data/xhs_profile，避免打包后在临时目录丢失）
def get_default_profile_dir() -> str:
    profile_dir = Path.home() / ".shenzheng_data" / "xhs_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)

DEFAULT_USER_DATA_DIR = get_default_profile_dir()

FIXED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1680, "height": 1050},
    {"width": 1600, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1512, "height": 982},
    {"width": 1280, "height": 800},
]

BASE = "https://www.xiaohongshu.com"
USER_POSTED_API = "/api/sns/web/v1/user_posted"
SEARCH_USER_TYPE = "54"
CST = timezone(timedelta(hours=8))

_STEALTH_JS = r"""
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  try { delete Object.getPrototypeOf(navigator).webdriver; } catch (e) {}

  Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
  Object.defineProperty(navigator, 'platform',  { get: () => 'Win32' });
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });

  const fakePlugin = (name, filename, desc) => ({
    name, filename, description: desc, length: 1,
    0: { type: 'application/pdf', suffixes: 'pdf', description: desc, enabledPlugin: null },
  });
  const plugins = [
    fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Chrome PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
    fakePlugin('Chromium PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format'),
  ];
  Object.defineProperty(navigator, 'plugins', { get: () => plugins });

  if (!window.chrome) { window.chrome = {}; }
  if (!window.chrome.runtime) { window.chrome.runtime = {}; }
  if (!window.chrome.app) {
    window.chrome.app = { isInstalled: false, InstallState: { DISABLED: 'disabled' }, RunningState: {} };
  }

  const origQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (origQuery) {
    window.navigator.permissions.query = (params) =>
      params && params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission, onchange: null })
        : origQuery.call(window.navigator.permissions, params);
  }

  try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (p) {
      if (p === 37445) return 'Intel Inc.';
      if (p === 37446) return 'Intel Iris OpenGL Engine';
      return getParameter.call(this, p);
    };
  } catch (e) {}

  Error.stackTraceLimit = 50;
  window.addEventListener('error', () => {}, true);
})();
"""


def _random_viewport() -> dict:
    return random.choice(VIEWPORTS)


class XiaohongshuScraper:
    def __init__(
        self,
        headless: bool = False,
        max_notes: int = 20,
        fetch_detail: bool = False,
        user_data_dir: str = DEFAULT_USER_DATA_DIR,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.max_notes = max_notes
        self.fetch_detail = fetch_detail
        self.cooldown_range = (1.5, 3.5)

        self._pw = None
        self.browser = None
        self.context = None
        self.page = None

        self._captured: dict[str, dict] = {}
        self._notes_order: list[str] = []
        self._page_count = 0
        self._profile_nick = ""

    async def _random_delay(self, lo: float = 0.4, hi: float = 1.6):
        await asyncio.sleep(random.uniform(lo, hi))

    async def page_cooldown(self, lo: float | None = None, hi: float | None = None):
        lo = lo if lo is not None else self.cooldown_range[0]
        hi = hi if hi is not None else self.cooldown_range[1]
        await asyncio.sleep(random.uniform(lo, hi))

    async def _human_scroll(self, steps: int = 5, settle: float = 1.0):
        for _ in range(steps):
            delta = random.randint(500, 1200)
            await self.page.mouse.wheel(0, delta)
            await self._random_delay(0.3, 0.9)
            if random.random() < 0.10:
                await self.page.mouse.wheel(0, -random.randint(80, 200))
                await self._random_delay(0.2, 0.5)
        await asyncio.sleep(settle)

    async def _safe_goto(self, url: str, retries: int = 3, wait: str = "domcontentloaded"):
        delay = 1.5
        for attempt in range(1, retries + 1):
            try:
                resp = await self.page.goto(url, wait_until=wait, timeout=40000)
                if resp is None or resp.status < 400:
                    return resp
                LOG.warning("goto %s -> HTTP %s (attempt %d)", url, resp.status, attempt)
            except PWTimeoutError:
                LOG.warning("goto 超时 (attempt %d): %s", attempt, url)
            except Exception as e:
                LOG.warning("goto 错误 (attempt %d): %s", attempt, e)
            if attempt < retries:
                await asyncio.sleep(delay)
                delay *= 2
        raise CrawlError(f"页面访问失败: {url}")

    async def _install_guards(self):
        await self.context.add_init_script(_STEALTH_JS)
        await self.page.add_init_script(_STEALTH_JS)
        try:
            await self.page.evaluate(_STEALTH_JS)
        except Exception:
            pass
        self.page.on("response", self._on_response)

    async def _on_response(self, response):
        if USER_POSTED_API not in response.url:
            return
        try:
            data = await response.json()
        except Exception:
            return
        notes = (data or {}).get("data", {}).get("notes") or []
        for item in notes:
            self._capture_note(item)

    def _capture_note(self, item):
        if not isinstance(item, dict):
            return
        card = item.get("note_card") or item.get("noteCard") or item
        nid = (item.get("note_id") or item.get("id")
               or card.get("noteId") or card.get("note_id"))
        if not nid or nid in self._captured:
            return
        user = card.get("user") or {}
        interact = card.get("interact_info") or card.get("interactInfo") or {}
        likes_raw = interact.get("liked_count") or interact.get("likedCount") or card.get("likes") or 0
        try:
            likes = int(likes_raw)
        except (TypeError, ValueError):
            likes = 0

        self._captured[nid] = {
            "post_id": str(nid),
            "username": (user.get("nickname") or user.get("nickName")
                         or user.get("nick_name") or ""),
            "content": (card.get("display_title") or card.get("displayTitle")
                        or card.get("desc") or "").strip(),
            "time": self._to_iso(card.get("time") or item.get("time")),
            "likes": likes,
            "_xsec_token": (item.get("xsec_token") or item.get("xsecToken")
                            or card.get("xsecToken") or card.get("xsec_token") or ""),
        }
        self._notes_order.append(nid)

    @staticmethod
    def _to_iso(ts) -> str:
        if ts in (None, "", 0):
            return ""
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            return str(ts)
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=CST).strftime("%Y-%m-%d %H:%M:%S")

    async def launch(self):
        if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
            home = Path.home()
            if sys.platform == "darwin":
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "Library" / "Caches" / "ms-playwright")
            elif sys.platform == "win32":
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "AppData" / "Local" / "ms-playwright")
            else:
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(home / ".cache" / "ms-playwright")

        self._pw = await async_playwright().start()
        vp = _random_viewport()
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-gpu",
            "--lang=zh-CN",
        ]
        ctx_kwargs = dict(
            user_agent=FIXED_UA,
            viewport=vp,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
            },
        )

        os.makedirs(self.user_data_dir, exist_ok=True)
        try:
            self.context = await launch_resilient_context(
                pw=self._pw,
                headless=self.headless,
                user_data_dir=self.user_data_dir,
                extra_args=launch_args,
                **ctx_kwargs,
            )
        except Exception as e:
            raise CrawlError(f"未能启动小红书浏览器环境: {e}")

        self.browser = self.context
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()
        await self._install_guards()

    async def close(self):
        try:
            if self.context:
                await self.context.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def _is_logged_in(self) -> bool:
        # 核心判断标准：检查 Cookie 中是否存在有效的 web_session 凭据
        try:
            cookies = await self.context.cookies()
            for c in cookies:
                if c.get("name") == "web_session" and len(c.get("value", "")) > 10:
                    return True
        except Exception:
            pass

        # 辅助判断：检测是否有个人中心头像或个人主页链接
        try:
            avatar_count = await self.page.locator(".avatar-wrapper, .user-avatar, img.avatar, [class*='avatar']").count()
            if avatar_count > 0:
                mask_count = await self.page.locator(".login-container, .qrcode-box, [class*='login-box']").count()
                if mask_count == 0:
                    return True
        except Exception:
            pass
        return False

    async def login(self) -> bool:
        await self._safe_goto(BASE + "/explore")
        await self._random_delay(1.0, 2.0)
        if await self._is_logged_in():
            LOG.info("检测到已登录，无需重复登录")
            return True

        # 如果未登录且页面未自动弹出登录二维码，主动寻找并点击登录按钮
        try:
            login_btn = self.page.locator("button:has-text('登录'), a:has-text('登录'), div:has-text('登录')").first
            if await login_btn.is_visible(timeout=2000):
                await login_btn.click()
        except Exception:
            pass

        LOG.info("请在弹出的浏览器中扫码或输入手机号登录小红书...")
        waited = 0
        last_logged = False
        while waited < 300:
            await asyncio.sleep(1.5)
            waited += 1.5
            try:
                if await self._is_logged_in():
                    last_logged = True
                    LOG.info("检测到小红书登录成功！正在保存登录态并自动关闭窗口...")
                    try:
                        await self.page.evaluate("""() => {
                            const tip = document.createElement('div');
                            tip.innerText = '小红书登录成功！凭证保存中，窗口即将自动关闭...';
                            tip.style.position = 'fixed';
                            tip.style.top = '24px';
                            tip.style.left = '50%';
                            tip.style.transform = 'translateX(-50%)';
                            tip.style.backgroundColor = '#10b981';
                            tip.style.color = '#ffffff';
                            tip.style.padding = '12px 28px';
                            tip.style.fontSize = '18px';
                            tip.style.fontWeight = 'bold';
                            tip.style.borderRadius = '8px';
                            tip.style.boxShadow = '0 6px 20px rgba(0,0,0,0.2)';
                            tip.style.zIndex = '9999999';
                            document.body.appendChild(tip);
                        }""")
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                # 若用户在登录成功后关闭了浏览器
                if last_logged:
                    return True
                break
        LOG.warning("等待登录超时或窗口被关闭")
        return last_logged

    @staticmethod
    def _looks_like_profile_url(text: str) -> bool:
        return "xiaohongshu.com/user/profile" in text

    @staticmethod
    def _looks_like_user_id(text: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-fA-F]{24}", text.strip()))

    async def _has_login_wall(self) -> bool:
        if await self._is_logged_in():
            return False
        try:
            wall = await self.page.locator(".login-container, .qrcode-box, [class*='login-modal']").first.is_visible(timeout=1000)
            if wall:
                return True
        except Exception:
            pass
        return False

    async def _grab_user_link(self, keyword: str) -> str | None:
        links = await self.page.eval_on_selector_all(
            "a[href*='/user/profile/']",
            "els => els.map(e => ({href: e.getAttribute('href'), text: (e.innerText||'').trim()}))",
        )
        if not links:
            return None
        best = None
        for it in links:
            if keyword and (keyword in it["text"] or keyword in (it["href"] or "")):
                best = it["href"]
                break
        href = best or links[0]["href"]
        if href.startswith("http"):
            return href
        return BASE + href

    async def resolve_profile_url(self, target: str) -> str:
        target = target.strip()
        if self._looks_like_profile_url(target):
            return target
        if self._looks_like_user_id(target):
            return f"{BASE}/user/profile/{target}"

        import urllib.parse
        kw = urllib.parse.quote(target)
        await self._safe_goto(f"{BASE}/search_result?keyword={kw}&type={SEARCH_USER_TYPE}")
        await self.page_cooldown(2.0, 3.5)
        try:
            await self.page.wait_for_selector("a[href*='/user/profile/']", timeout=8000)
        except PWTimeoutError:
            pass
        href = await self._grab_user_link(target)

        if not href:
            if await self._has_login_wall():
                raise CrawlError("小红书需要登录：请先执行 `uv run server/xiaohongshu.py --login` 完成扫码登录")
            raise CrawlError(f"未找到小红书用户『{target}』，请确认昵称/小红书号是否正确")

        return href

    async def scrape_profile(self, profile_url: str) -> tuple[str, list[dict]]:
        await self._safe_goto(profile_url)
        await self.page_cooldown(2.0, 3.5)
        await self._harvest_initial_state()

        stagnant = 0
        last_count = len(self._captured)
        while True:
            if self.max_notes and len(self._captured) >= self.max_notes:
                break
            await self._human_scroll(steps=random.randint(3, 6))
            self._page_count += 1
            await self._harvest_initial_state()
            cur = len(self._captured)
            if cur == last_count:
                stagnant += 1
                if stagnant >= 2:
                    break
            else:
                stagnant = 0
                last_count = cur
            await self.page_cooldown()

        account_name = self._profile_nick or "小红书用户"
        notes = [self._captured[nid] for nid in self._notes_order]
        if self.max_notes:
            notes = notes[: self.max_notes]
        return account_name, notes

    async def _harvest_initial_state(self):
        try:
            data = await self.page.evaluate("""() => {
                const unwrap = (x, d=0) => (x && x.__v_isRef && d < 12) ? unwrap(x._value, d+1) : x;
                const s = window.__INITIAL_STATE__ || {};
                const u = unwrap(s.user) || {};
                const upd = unwrap(u.userPageData) || {};
                const basic = unwrap(upd.basicInfo) || {};
                const notes = unwrap(upd.notes) || unwrap(u.notes) || [];
                const flat = [];
                const walk = (arr) => {
                    if (!Array.isArray(arr)) return;
                    for (const x of arr) {
                        if (Array.isArray(x)) walk(x);
                        else if (x && typeof x === 'object') flat.push(x);
                    }
                };
                walk(notes);
                return {
                    nickname: basic.nickname || basic.nickName || basic.name || '',
                    notes: flat,
                };
            }""")
        except Exception:
            return
        if not data:
            return
        if data.get("nickname"):
            self._profile_nick = data["nickname"]
        for it in data.get("notes", []):
            self._capture_note(it)


async def crawl_xiaohongshu(
    account: str,
    limit: int = 20,
    headless: bool = True,
) -> CrawlResponse:
    """提供给 FastAPI 调用的统一接口函数"""
    # 允许通过环境变量覆盖 headless 状态（例如调试时设为 0）
    env_headless = os.getenv("XHS_HEADLESS")
    if env_headless is not None:
        headless = env_headless.lower() in ("true", "1")

    scraper = XiaohongshuScraper(
        headless=headless,
        max_notes=limit,
    )
    await scraper.launch()
    try:
        profile_url = await scraper.resolve_profile_url(account)
        nick, raw_notes = await scraper.scrape_profile(profile_url)
        
        posts = [
            Post(
                time=n.get("time") or "",
                likes=n.get("likes") or 0,
                content=n.get("content") or "",
            )
            for n in raw_notes
        ]
        return CrawlResponse(
            platform="小红书",
            account=nick or account,
            posts=posts,
        )
    finally:
        await scraper.close()


async def interactive_login() -> bool:
    """拉起有头浏览器供用户扫码登录小红书，自动保存登录态"""
    scraper = XiaohongshuScraper(headless=False)
    await scraper.launch()
    try:
        return await scraper.login()
    finally:
        await scraper.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小红书登录与测试工具")
    parser.add_argument("--login", action="store_true", help="打开浏览器进行扫码登录并永久保存登录态")
    parser.add_argument("--search", type=str, help="搜索并抓取指定用户的小红书内容")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.login:
        async def do_login():
            s = XiaohongshuScraper(headless=False)
            await s.launch()
            try:
                await s.login()
            finally:
                await s.close()
        asyncio.run(do_login())
    elif args.search:
        async def do_search():
            res = await crawl_xiaohongshu(args.search, limit=5, headless=False)
            print(f"成功抓取用户: {res.account}, 帖子数量: {len(res.posts)}")
            for p in res.posts:
                print(f"[{p.time}] 赞 {p.likes}: {p.content[:60]}")
        asyncio.run(do_search())
    else:
        parser.print_help()
