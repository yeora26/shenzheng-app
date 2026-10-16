//! 扫码登录窗口的通用能力：直接用 Tauri 自带的 WebView2（Windows）/ WKWebView（macOS）
//! 打开平台登录页，无需 Playwright、外部浏览器或 node 驱动，并从 WebView 的 Cookie 存储中读取 Cookie。

use std::collections::BTreeMap;
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, Runtime, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

/// 等待用户扫码的最长时间
pub const TIMEOUT_SECS: u64 = 300;

pub struct LoginWindow<R: Runtime> {
  app: AppHandle<R>,
  label: &'static str,
  win: WebviewWindow<R>,
}

impl<R: Runtime> LoginWindow<R> {
  /// 打开登录窗口；若同名窗口已存在则将其置前并返回错误
  pub fn open(
    app: &AppHandle<R>,
    label: &'static str,
    title: &str,
    url: &str,
  ) -> Result<Self, String> {
    if let Some(existing) = app.get_webview_window(label) {
      let _ = existing.set_focus();
      return Err(format!("{title}窗口已打开，请在该窗口中完成扫码"));
    }
    let url = Url::parse(url).map_err(|e| e.to_string())?;
    let win = WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))
      .title(title)
      .inner_size(1000.0, 760.0)
      .center()
      .build()
      .map_err(|e| format!("无法创建登录窗口: {e}"))?;
    Ok(Self { app: app.clone(), label, win })
  }

  pub fn is_open(&self) -> bool {
    self.app.get_webview_window(self.label).is_some()
  }

  pub fn url(&self) -> Option<Url> {
    self.win.url().ok()
  }

  pub fn navigate(&self, url: &str) {
    if let Ok(u) = Url::parse(url) {
      let _ = self.win.navigate(u);
    }
  }

  /// 读取指定站点的全部 Cookie（含 HttpOnly），后面的站点覆盖前面的同名 Cookie。
  /// 注意：Windows 上必须在异步命令中调用，否则会与 WebView2 死锁
  pub fn cookies(&self, urls: &[&str]) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    for u in urls {
      let Ok(url) = Url::parse(u) else { continue };
      if let Ok(cookies) = self.win.cookies_for_url(url) {
        for c in cookies {
          map.insert(c.name().to_string(), c.value().to_string());
        }
      }
    }
    map
  }

  /// 在页面中执行一段返回布尔值的同步 JS 表达式；页面未就绪或出错时返回 false
  pub async fn eval_bool(&self, js: &str) -> bool {
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();
    let tx = Mutex::new(Some(tx));
    let script = format!("(() => {{ try {{ return !!({js}); }} catch (e) {{ return false; }} }})()");
    let sent = self.win.eval_with_callback(script, move |res| {
      if let Some(tx) = tx.lock().unwrap().take() {
        let _ = tx.send(res);
      }
    });
    if sent.is_err() {
      return false;
    }
    matches!(
      tokio::time::timeout(Duration::from_secs(3), rx).await,
      Ok(Ok(res)) if res.trim() == "true"
    )
  }

  pub fn close(&self) {
    if let Some(w) = self.app.get_webview_window(self.label) {
      let _ = w.close();
    }
  }
}

pub async fn sleep(ms: u64) {
  tokio::time::sleep(Duration::from_millis(ms)).await;
}

pub fn join_cookies(cookies: &BTreeMap<String, String>) -> String {
  cookies
    .iter()
    .map(|(k, v)| format!("{k}={v}"))
    .collect::<Vec<_>>()
    .join("; ")
}
