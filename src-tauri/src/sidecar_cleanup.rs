//! 清理残留的后端进程。
//!
//! PyInstaller 单文件打包的后端运行时是「引导进程 + 实际 Python 进程」两层，应用退出时只能杀掉引导进程，
//! 实际进程会成为孤儿并继续占用 8000 端口，导致新版本后端无法启动、请求被旧版本后端处理。
//! 因此启动前先结束所有「从本应用目录启动的 server 进程」（按完整路径匹配，不影响其他程序）。

use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

fn sidecar_path() -> Option<PathBuf> {
  let dir = std::env::current_exe().ok()?.parent()?.to_path_buf();
  let name = if cfg!(windows) { "server.exe" } else { "server" };
  Some(dir.join(name))
}

#[cfg(windows)]
fn kill_by_path(path: &PathBuf) -> bool {
  use std::os::windows::process::CommandExt;
  const CREATE_NO_WINDOW: u32 = 0x0800_0000;
  // 路径通过环境变量传入，避免中文路径与引号转义问题
  let script = "$p = $env:SZ_SERVER_PATH; $n = 0; \
    Get-CimInstance Win32_Process -Filter \"Name='server.exe'\" | \
    Where-Object { $_.ExecutablePath -ieq $p } | \
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; \
    Write-Output $n";
  let output = Command::new("powershell")
    .args(["-NoProfile", "-NonInteractive", "-Command", script])
    .env("SZ_SERVER_PATH", path)
    .creation_flags(CREATE_NO_WINDOW)
    .output();
  match output {
    Ok(out) => {
      let killed = String::from_utf8_lossy(&out.stdout).trim().parse::<u32>().unwrap_or(0);
      if killed > 0 {
        log::info!("已结束 {killed} 个残留后端进程");
      }
      killed > 0
    }
    Err(e) => {
      log::warn!("清理残留后端进程失败: {e}");
      false
    }
  }
}

#[cfg(not(windows))]
fn kill_by_path(path: &PathBuf) -> bool {
  let Some(path) = path.to_str() else { return false };
  let Ok(out) = Command::new("ps").args(["-axo", "pid=,command="]).output() else {
    return false;
  };
  let mut killed = 0;
  for line in String::from_utf8_lossy(&out.stdout).lines() {
    let line = line.trim_start();
    let Some((pid, cmd)) = line.split_once(' ') else { continue };
    let cmd = cmd.trim_start();
    let matches = cmd == path || cmd.strip_prefix(path).is_some_and(|rest| rest.starts_with(' '));
    if matches && Command::new("kill").args(["-9", pid]).status().is_ok_and(|s| s.success()) {
      killed += 1;
    }
  }
  if killed > 0 {
    log::info!("已结束 {killed} 个残留后端进程");
  }
  killed > 0
}

/// 结束本应用目录下残留的后端进程；如有结束，稍等片刻让端口释放
pub fn kill_stale_sidecars() {
  let Some(path) = sidecar_path() else { return };
  if kill_by_path(&path) {
    std::thread::sleep(Duration::from_millis(800));
  }
}
