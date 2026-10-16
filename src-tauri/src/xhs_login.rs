//! 小红书扫码登录：在内置 WebView 窗口中打开小红书，登录成功后返回 Cookie。
//!
//! 小红书会给未登录的访客也下发 `web_session`，因此不能只看 Cookie，
//! 还要在页面里确认登录状态（页面状态中的 loggedIn，或侧边栏出现「我」的主页链接）。

use tauri::{AppHandle, Runtime};

use crate::login_window::{join_cookies, sleep, LoginWindow, TIMEOUT_SECS};

const WINDOW_LABEL: &str = "xhs-login";
const LOGIN_URL: &str = "https://www.xiaohongshu.com/explore";
const COOKIE_URLS: &[&str] = &["https://www.xiaohongshu.com/", "https://edith.xiaohongshu.com/"];

/// 页面内的登录判断（同步表达式）
const LOGGED_IN_JS: &str = r#"(() => {
  const unwrap = (x, d = 0) => (x && x.__v_isRef && d < 12) ? unwrap(x._value, d + 1) : x;
  const user = unwrap((window.__INITIAL_STATE__ || {}).user) || {};
  if (unwrap(user.loggedIn) === true) return true;
  const me = document.querySelector('.side-bar a[href*="/user/profile/"]');
  const loginBtn = document.querySelector('#login-btn, .login-btn, .login-container');
  return !!me && !loginBtn;
})()"#;

/// 打开小红书扫码窗口，等待用户登录成功后返回 Cookie 字符串
#[tauri::command]
pub async fn xhs_login<R: Runtime>(app: AppHandle<R>) -> Result<String, String> {
  let win = LoginWindow::open(&app, WINDOW_LABEL, "小红书扫码登录", LOGIN_URL)?;

  let mut waited_ms = 0u64;
  let result = loop {
    sleep(1500).await;
    waited_ms += 1500;

    if !win.is_open() {
      break Err("登录窗口已被关闭，未完成登录".to_string());
    }
    if waited_ms >= TIMEOUT_SECS * 1000 {
      break Err("等待扫码登录超时".to_string());
    }

    let has_session = win
      .cookies(COOKIE_URLS)
      .get("web_session")
      .is_some_and(|v| v.len() > 10);
    if !has_session || !win.eval_bool(LOGGED_IN_JS).await {
      continue;
    }

    // 稍等片刻，确保登录后下发的 Cookie 全部写入
    sleep(1500).await;
    break Ok(join_cookies(&win.cookies(COOKIE_URLS)));
  };

  win.close();
  result
}
