from __future__ import annotations

import html
import os
import re
from typing import TypedDict

import httpx

try:
    from models import CrawlResponse, Post
    from browser_helper import launch_resilient_context, get_app_data_dir
except ImportError:
    from server.models import CrawlResponse, Post
    from server.browser_helper import launch_resilient_context, get_app_data_dir

BASE_URL = 'https://m.weibo.cn/api/container/getIndex'
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    ),
    'Referer': 'https://m.weibo.cn/',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json',
}
TAG_RE = re.compile(r'<[^>]+>')


class CrawlError(Exception):
    pass


class WeiboUser(TypedDict, total=False):
    id: int
    screen_name: str


class MBlog(TypedDict, total=False):
    created_at: str
    text: str
    attitudes_count: int


class Card(TypedDict, total=False):
    card_type: int
    card_group: list['Card']
    user: WeiboUser
    mblog: MBlog


class IndexData(TypedDict, total=False):
    cards: list[Card]


class IndexResponse(TypedDict, total=False):
    ok: int
    data: IndexData


async def _get_index(
    client: httpx.AsyncClient, containerid: str, cookie: str, page: int = 1
) -> IndexResponse:
    params = {'containerid': containerid}
    if page > 1:
        params['page'] = str(page)
    resp = await client.get(
        BASE_URL,
        params=params,
        headers={**HEADERS, 'Cookie': cookie},
        timeout=10,
    )
    if resp.status_code != 200:
        raise CrawlError(f'微博接口返回 HTTP {resp.status_code}')
    data: IndexResponse = resp.json()
    if data.get('ok') != 1:
        raise CrawlError('微博接口拒绝访问，请检查 WEIBO_COOKIE 是否有效')
    return data


def _clean_text(raw: str) -> str:
    return html.unescape(TAG_RE.sub('', raw)).strip()


async def _search_user(client: httpx.AsyncClient, account: str, cookie: str) -> WeiboUser:
    data = await _get_index(client, f'100103type=3&q={account}', cookie)
    users: list[WeiboUser] = []
    for card in data.get('data', {}).get('cards', []):
        for sub in card.get('card_group', []):
            user = sub.get('user')
            if user and user.get('id'):
                users.append(user)
    if not users:
        raise CrawlError(f'未找到用户「{account}」，请确认昵称准确或稍后重试')
    for user in users:
        if user.get('screen_name') == account:
            return user
    return users[0]


async def _fetch_posts(
    client: httpx.AsyncClient, uid: int, limit: int, cookie: str
) -> list[Post]:
    posts: list[Post] = []
    page = 1
    max_pages = (limit + 9) // 10 + 2  # 预估翻页上限，避免死循环
    while len(posts) < limit and page <= max_pages:
        try:
            data = await _get_index(client, f'107603{uid}', cookie, page=page)
        except CrawlError:
            break
        cards = data.get('data', {}).get('cards', [])
        added_in_page = 0
        for card in cards:
            blog = card.get('mblog')
            if not blog:
                continue
            posts.append(Post(
                time=blog.get('created_at', ''),
                likes=blog.get('attitudes_count', 0),
                content=_clean_text(blog.get('text', '')),
            ))
            added_in_page += 1
            if len(posts) >= limit:
                break
        if added_in_page == 0:
            break
        page += 1

    if not posts:
        raise CrawlError('该用户暂无公开微博，或接口访问受限')
    return posts[:limit]


def _get_cookie() -> str:
    cookie = os.environ.get('WEIBO_COOKIE', '').strip()
    if cookie:
        return cookie
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('WEIBO_COOKIE='):
                    return line.strip().split('=', 1)[1].strip()
    return ''


async def crawl_weibo(account: str, limit: int = 20, cookie: str | None = None) -> CrawlResponse:
    target_cookie = (cookie or '').strip() or _get_cookie()
    if not target_cookie:
        raise CrawlError(
            '未配置微博 Cookie 或已过期。请点击右上角「设置」填入最新有效 Cookie 后重试。'
        )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        user = await _search_user(client, account, target_cookie)
        posts = await _fetch_posts(client, user['id'], limit, target_cookie)
    return CrawlResponse(
        platform='微博',
        account=user.get('screen_name', account),
        posts=posts,
    )


async def weibo_interactive_login() -> str:
    """拉起有头浏览器供用户扫码登录微博，登录成功后自动提取并返回 Cookie 字符串"""
    import asyncio
    from playwright.async_api import async_playwright

    weibo_profile_dir = get_app_data_dir("weibo_profile")

    async with async_playwright() as p:
        try:
            context = await launch_resilient_context(
                pw=p,
                headless=False,
                user_data_dir=weibo_profile_dir,
                locale='zh-CN',
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                ),
            )
        except Exception as e:
            raise CrawlError(f"未能拉起微博扫码浏览器窗口: {e}")

        pages = context.pages
        page = pages[0] if pages else await context.new_page()
        # 打开微博官方统一扫码与登录页面
        login_url = 'https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&url=https%3A%2F%2Fweibo.com'
        try:
            await page.goto(login_url, wait_until='domcontentloaded', timeout=30000)
        except Exception:
            await page.goto('https://weibo.com/login.php', wait_until='domcontentloaded', timeout=30000)

        waited = 0
        cookie_str = ''
        while waited < 300:
            await asyncio.sleep(1.0)
            waited += 1.0
            try:
                # 聚合当前上下文与关键域名的所有 Cookie
                all_cookies = await context.cookies([
                    'https://weibo.com',
                    'https://m.weibo.cn',
                    'https://passport.weibo.com',
                    'https://sina.com.cn',
                ])
                if not all_cookies:
                    all_cookies = await context.cookies()

                # 检测是否生成了包含登录态的 SUB 核心凭证
                sub_cookie = next(
                    (c for c in all_cookies if c.get('name') == 'SUB' and len(c.get('value', '')) > 10),
                    None
                )

                cur_url = page.url
                is_redirected_home = ('weibo.com' in cur_url) and ('signin' not in cur_url) and ('login' not in cur_url)

                if sub_cookie or is_redirected_home:
                    cookie_map = {}
                    for c in all_cookies:
                        name = c.get('name')
                        val = c.get('value')
                        domain = c.get('domain', '')
                        if name and val and ('weibo' in domain or 'sina' in domain or not domain):
                            cookie_map[name] = val

                    # 尝试从当前页面直接读取 document.cookie 进行补充
                    try:
                        doc_cookie = await page.evaluate('document.cookie')
                        if doc_cookie:
                            for item in doc_cookie.split(';'):
                                if '=' in item:
                                    k, v = item.strip().split('=', 1)
                                    if k and v and k not in cookie_map:
                                        cookie_map[k] = v
                    except Exception:
                        pass

                    if 'SUB' in cookie_map:
                        cookie_str = '; '.join([f'{k}={v}' for k, v in cookie_map.items()])
                        # 在页面上注入提示信息并稍等保存
                        try:
                            await page.evaluate("""() => {
                                const tip = document.createElement('div');
                                tip.innerText = '微博登录成功！Cookie 提取中，窗口即将自动关闭...';
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
                        break
            except Exception:
                # 若用户在登录完成后关闭了窗口，只要已经提取到 cookie 则直接返回
                if cookie_str:
                    break
                break

        try:
            await context.close()
        except Exception:
            pass
        return cookie_str

