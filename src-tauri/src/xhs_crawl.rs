//! 小红书抓取：在不可见的内置 WebView 窗口中打开用户主页，读取页面数据中的笔记。
//! 窗口与扫码登录共用同一份 Cookie 存储，因此只要在设置中扫码登录过即可抓取。

use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Runtime, Url};

use crate::login_window::{sleep, LoginWindow};

const WINDOW_LABEL: &str = "xhs-crawl";
const BASE: &str = "https://www.xiaohongshu.com";
/// 搜索结果中「用户」分类
const SEARCH_USER_TYPE: &str = "54";

#[derive(Serialize)]
pub struct Post {
  time: String,
  likes: i64,
  content: String,
}

#[derive(Serialize)]
pub struct CrawlResponse {
  platform: String,
  account: String,
  posts: Vec<Post>,
}

#[derive(Deserialize)]
struct Note {
  id: String,
  time: String,
  likes: i64,
  content: String,
}

#[derive(Deserialize, Default)]
struct Harvest {
  nickname: String,
  notes: Vec<Note>,
}

/// 从页面状态 __INITIAL_STATE__ 中读取主页昵称与笔记列表（随滚动加载会持续追加）
const HARVEST_JS: &str = r#"(() => {
  const unwrap = (x, d = 0) => (x && x.__v_isRef && d < 12) ? unwrap(x._value, d + 1) : x;
  const s = window.__INITIAL_STATE__ || {};
  const u = unwrap(s.user) || {};
  const upd = unwrap(u.userPageData) || {};
  const basic = unwrap(upd.basicInfo) || {};
  const flat = [];
  const walk = (arr) => {
    arr = unwrap(arr);
    if (!Array.isArray(arr)) return;
    for (let x of arr) {
      x = unwrap(x);
      if (Array.isArray(x)) walk(x);
      else if (x && typeof x === 'object') flat.push(x);
    }
  };
  walk(unwrap(upd.notes) || unwrap(u.notes) || []);

  const parseLikes = (v) => {
    if (typeof v === 'number') return Math.round(v);
    const t = String(v || '').trim();
    const n = parseFloat(t);
    if (isNaN(n)) return 0;
    if (t.includes('万')) return Math.round(n * 10000);
    if (t.includes('亿')) return Math.round(n * 100000000);
    return Math.round(n);
  };
  const fmtTime = (ts) => {
    if (!ts) return '';
    const n = Number(ts);
    if (isNaN(n)) return String(ts);
    const ms = n > 1e12 ? n : n * 1000;
    const iso = new Date(ms + 8 * 3600 * 1000).toISOString();
    return iso.slice(0, 10) + ' ' + iso.slice(11, 19);
  };

  const notes = flat.map((item) => {
    const card = unwrap(item.noteCard || item.note_card) || item;
    const id = item.noteId || item.note_id || item.id || card.noteId || card.note_id || '';
    const it = unwrap(card.interactInfo || card.interact_info) || {};
    return {
      id: String(id),
      time: fmtTime(card.time || item.time),
      likes: parseLikes(it.likedCount ?? it.liked_count ?? card.likes ?? 0),
      content: String(card.displayTitle || card.display_title || card.desc || '').trim(),
    };
  }).filter((n) => n.id);

  return { nickname: String(basic.nickname || basic.nickName || basic.name || ''), notes };
})()"#;

const LOGIN_WALL_JS: &str =
  r#"document.querySelector('.login-container, .qrcode-box, [class*="login-modal"]')"#;

const SCROLL_JS: &str = r#"(() => {
  window.scrollBy(0, 700 + Math.floor(Math.random() * 600));
  return true;
})()"#;

/// 在搜索结果中找到与关键词最匹配的用户主页链接（排除侧边栏里自己的主页）
fn find_user_link_js(keyword: &str) -> String {
  let kw = serde_json::to_string(keyword).unwrap_or_else(|_| "\"\"".into());
  format!(
    r#"(() => {{
  const kw = {kw};
  const links = [...document.querySelectorAll("a[href*='/user/profile/']")]
    .filter((e) => !e.closest('.side-bar'))
    .map((e) => ({{ href: e.getAttribute('href') || '', text: (e.innerText || '').trim() }}));
  if (!links.length) return null;
  const best = links.find((l) => kw && (l.text.includes(kw) || l.href.includes(kw))) || links[0];
  return best.href.startsWith('http') ? best.href : location.origin + best.href;
}})()"#
  )
}

fn looks_like_user_id(s: &str) -> bool {
  s.len() == 24 && s.chars().all(|c| c.is_ascii_hexdigit())
}

async fn resolve_profile_url<R: Runtime>(
  win: &LoginWindow<R>,
  account: &str,
) -> Result<String, String> {
  if account.contains("xiaohongshu.com/user/profile") {
    return Ok(account.to_string());
  }
  if looks_like_user_id(account) {
    return Ok(format!("{BASE}/user/profile/{account}"));
  }

  let mut search = Url::parse(&format!("{BASE}/search_result")).map_err(|e| e.to_string())?;
  search
    .query_pairs_mut()
    .append_pair("keyword", account)
    .append_pair("type", SEARCH_USER_TYPE);
  win.navigate(search.as_str());

  let js = find_user_link_js(account);
  for _ in 0..12 {
    sleep(1000).await;
    if let Some(Some(href)) = win
      .eval_json(&js)
      .await
      .and_then(|res| serde_json::from_str::<Option<String>>(&res).ok())
    {
      return Ok(href);
    }
  }

  if win.eval_bool(LOGIN_WALL_JS).await {
    return Err("小红书需要登录：请先在「设置」中点击小红书「扫码自动获取」完成登录".into());
  }
  Err(format!("未找到小红书用户『{account}』，请确认昵称/小红书号是否正确"))
}

async fn harvest<R: Runtime>(win: &LoginWindow<R>) -> Harvest {
  win
    .eval_json(HARVEST_JS)
    .await
    .and_then(|res| serde_json::from_str(&res).ok())
    .unwrap_or_default()
}

/// 抓取指定小红书用户最近的笔记
#[tauri::command]
pub async fn xhs_crawl<R: Runtime>(
  app: AppHandle<R>,
  account: String,
  limit: usize,
) -> Result<CrawlResponse, String> {
  let account = account.trim().to_string();
  if account.is_empty() {
    return Err("请输入账号昵称或 ID".into());
  }
  let limit = limit.clamp(1, 100);

  // 先打开首页让站点下发基础 Cookie，再进行搜索
  let win = LoginWindow::open_hidden(&app, WINDOW_LABEL, "小红书抓取", &format!("{BASE}/explore"))?;
  sleep(2000).await;

  let result = async {
    let profile_url = resolve_profile_url(&win, &account).await?;
    win.navigate(&profile_url);
    sleep(2500).await;

    let mut seen = HashSet::new();
    let mut posts = Vec::new();
    let mut nickname = String::new();
    let mut stagnant = 0;
    let max_rounds = limit / 10 + 6;

    for _ in 0..max_rounds {
      let page = harvest(&win).await;
      if !page.nickname.is_empty() {
        nickname = page.nickname;
      }
      let before = posts.len();
      for n in page.notes {
        if posts.len() >= limit {
          break;
        }
        if seen.insert(n.id) {
          posts.push(Post { time: n.time, likes: n.likes, content: n.content });
        }
      }
      if posts.len() >= limit {
        break;
      }
      if posts.len() == before {
        stagnant += 1;
        if stagnant >= 3 {
          break;
        }
      } else {
        stagnant = 0;
      }
      for _ in 0..4 {
        win.eval_bool(SCROLL_JS).await;
        sleep(500).await;
      }
      sleep(1500).await;
    }

    if posts.is_empty() {
      if win.eval_bool(LOGIN_WALL_JS).await {
        return Err("小红书需要登录：请先在「设置」中点击小红书「扫码自动获取」完成登录".to_string());
      }
      return Err("该用户暂无公开笔记，或页面访问受限".to_string());
    }
    Ok(CrawlResponse {
      platform: "小红书".into(),
      account: if nickname.is_empty() { account.clone() } else { nickname },
      posts,
    })
  }
  .await;

  win.close();
  result
}
