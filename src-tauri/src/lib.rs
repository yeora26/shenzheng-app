use std::sync::{Arc, Mutex};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

mod login_window;
mod weibo_login;
mod xhs_crawl;
mod xhs_login;

#[derive(Default, Clone)]
struct ServerState(Arc<Mutex<Option<CommandChild>>>);

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let server_state = ServerState::default();
  let server_state_clone = server_state.clone();

  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![
      weibo_login::weibo_login,
      xhs_login::xhs_login,
      xhs_crawl::xhs_crawl
    ])
    .setup(move |app| {
      if cfg!(debug_assertions) {
        let _ = app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        );
      }

      // 启动 sidecar 后端服务
      let handle = app.handle().clone();
      let state = server_state_clone.clone();

      tauri::async_runtime::spawn(async move {
        match handle.shell().sidecar("server") {
          Ok(command) => {
            log::info!("正在拉起 Sidecar 后端服务...");
            match command.spawn() {
              Ok((_rx, child)) => {
                log::info!("Sidecar 后端服务已成功启动 (PID: {:?})", child.pid());
                let mut guard = state.0.lock().unwrap();
                *guard = Some(child);
              }
              Err(e) => {
                log::error!("启动 Sidecar 失败: {}", e);
              }
            }
          }
          Err(e) => {
            log::warn!("未配置或找不到 Sidecar server: {}", e);
          }
        }
      });

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(move |_app_handle, event| {
      // 当应用退出时，安全终止后台子进程
      if let tauri::RunEvent::Exit = event {
        let mut guard = server_state.0.lock().unwrap();
        if let Some(child) = guard.take() {
          let _ = child.kill();
          log::info!("Sidecar 后端服务已终止");
        }
      }
    });
}
