//! 站点窗口的通用能力（扫码登录与小红书抓取共用）：直接用 Tauri 自带的 WebView2（Windows）/
//! WKWebView（macOS）打开平台页面，无需 Playwright、外部浏览器或 node 驱动；
//! 可读取 WebView 的 Cookie 存储，并在页面中执行 JS。

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
    Self::build(app, label, title, url, true)
  }

  /// 打开不可见的后台窗口（用于抓取）；若同名窗口已存在说明已有任务在进行
  pub fn open_hidden(
    app: &AppHandle<R>,
    label: &'static str,
    title: &str,
    url: &str,
  ) -> Result<Self, String> {
    if app.get_webview_window(label).is_some() {
      return Err(format!("{title}任务正在进行中，请稍后再试"));
    }
    Self::build(app, label, title, url, false)
  }

  fn build(
    app: &AppHandle<R>,
    label: &'static str,
    title: &str,
    url: &str,
    visible: bool,
  ) -> Result<Self, String> {
    let url = Url::parse(url).map_err(|e| e.to_string())?;
    let win = WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))
      .title(title)
      .inner_size(1280.0, 860.0)
      .center()
      .visible(visible)
      .build()
      .map_err(|e| format!("无法创建窗口: {e}"))?;
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

  /// 在页面中执行一段同步 JS 表达式，返回其 JSON 序列化结果；页面未就绪或超时返回 None
  pub async fn eval_json(&self, js: &str) -> Option<String> {
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();
    let tx = Mutex::new(Some(tx));
    let script = format!("(() => {{ try {{ return ({js}); }} catch (e) {{ return null; }} }})()");
    self
      .win
      .eval_with_callback(script, move |res| {
        if let Some(tx) = tx.lock().unwrap().take() {
          let _ = tx.send(res);
        }
      })
      .ok()?;
    tokio::time::timeout(Duration::from_secs(3), rx).await.ok()?.ok()
  }

  /// 在页面中执行一段返回布尔值的同步 JS 表达式；页面未就绪或出错时返回 false
  pub async fn eval_bool(&self, js: &str) -> bool {
    self
      .eval_json(&format!("!!({js})"))
      .await
      .is_some_and(|res| res.trim() == "true")
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
