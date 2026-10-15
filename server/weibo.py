import html
import os
import re
from typing import TypedDict

import httpx

from models import CrawlResponse, Post

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
