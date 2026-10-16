//! 微博扫码登录：在内置 WebView 窗口中打开微博登录页，登录成功后返回 Cookie。

use std::collections::BTreeMap;

use tauri::{AppHandle, Runtime, Url};

use crate::login_window::{join_cookies, sleep, LoginWindow, TIMEOUT_SECS};

const WINDOW_LABEL: &str = "weibo-login";
const LOGIN_URL: &str =
  "https://passport.weibo.com/sso/signin?entry=miniblog&source=miniblog&url=https%3A%2F%2Fweibo.com";

/// 读取 Cookie 的域名，按优先级从低到高排列（后者覆盖前者的同名 Cookie）
const COOKIE_URLS: &[&str] = &[
  "https://passport.weibo.com/",
  "https://weibo.com/",
  "https://m.weibo.cn/",
];

fn sub_value(cookies: &BTreeMap<String, String>) -> Option<String> {
  cookies.get("SUB").filter(|v| v.len() > 10).cloned()
}

fn is_logged_in_url(url: &Url) -> bool {
  let host = url.host_str().unwrap_or("");
  let path = url.path();
  host.ends_with("weibo.com")
    && !host.starts_with("passport.")
    && !path.contains("signin")
    && !path.contains("login")
}

/// 该接口返回当前会话的登录状态，形如 {"data":{"login":true,...},"ok":1}
const LOGIN_STATE_URL: &str = "https://m.weibo.cn/api/config";
const LOGIN_STATE_JS: &str = r#"(() => {
  const text = (document.body && document.body.innerText) || '';
  if (!/"login"\s*:/.test(text)) return null;
  return /"login"\s*:\s*true/.test(text);
})()"#;

/// 查询窗口中已有的微博会话是否仍然有效；无法判断时返回 None
async fn existing_session_valid<R: Runtime>(win: &LoginWindow<R>) -> Option<bool> {
  for _ in 0..8 {
    sleep(1000).await;
    if !win.is_open() {
      return None;
    }
    match win.eval_json(LOGIN_STATE_JS).await.as_deref().map(str::trim) {
      Some("true") => return Some(true),
      Some("false") => return Some(false),
      _ => continue,
    }
  }
  None
}

/// 打开微博扫码窗口，等待用户登录成功后返回 Cookie 字符串
#[tauri::command]
pub async fn weibo_login<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
  let win = LoginWindow::open(&app, WINDOW_LABEL, "微博扫码登录", LOGIN_STATE_URL)?;

  // 内置 WebView 会保留上次的登录态：若仍然有效，直接提取 Cookie，无需重新扫码
  if existing_session_valid(&win).await == Some(true) {
    let cookies = win.cookies(COOKIE_URLS);
    if sub_value(&cookies).is_some() {
      win.close();
      return Ok(join_cookies(&cookies));
    }
  }
  if !win.is_open() {
    return Err("登录窗口已被关闭，未完成登录".to_string());
  }
  win.navigate(LOGIN_URL);

  // 记录此时已有的（已失效的）SUB，避免把旧登录态当作登录成功
  sleep(800).await;
  let initial_sub = sub_value(&win.cookies(COOKIE_URLS));

  let mut waited_ms = 0u64;
  let result = loop {
    sleep(1000).await;
    waited_ms += 1000;

    if !win.is_open() {
      break Err("登录窗口已被关闭，未完成登录".to_string());
    }
    if waited_ms >= TIMEOUT_SECS * 1000 {
      break Err("等待扫码登录超时".to_string());
    }

    let cookies = win.cookies(COOKIE_URLS);
    let Some(sub) = sub_value(&cookies) else { continue };
    let redirected_home = win.url().map(|u| is_logged_in_url(&u)).unwrap_or(false);
    if initial_sub.as_deref() == Some(sub.as_str()) && !redirected_home {
      continue;
    }

    // 登录成功：访问一次 m.weibo.cn，让 SSO 下发移动端接口所需的 Cookie
    win.navigate("https://m.weibo.cn/");
    for _ in 0..6 {
      sleep(1000).await;
      if !win.is_open() {
        break;
      }
      if win.url().is_some_and(|u| u.host_str() == Some("m.weibo.cn")) {
        sleep(1500).await;
        break;
      }
    }

    let mut final_cookies = cookies;
    if win.is_open() {
      final_cookies.extend(win.cookies(COOKIE_URLS));
    }
    break Ok(join_cookies(&final_cookies));
  };

  win.close();
  result
}
