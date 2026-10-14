use crate::background_process::background_command;
use serde::Deserialize;
use std::{fs, io::Write, path::PathBuf, process::Stdio, sync::Mutex};

static CONTROL: Mutex<()> = Mutex::new(());

#[derive(Deserialize, serde::Serialize)]
pub(crate) struct MobileStatus {
    running: bool,
    registered: bool,
    url: String,
    code: String,
    message: String,
}

fn root() -> PathBuf {
    // This release uses the same workstation installation as the image workers.
    PathBuf::from(crate::OUTPUT_ROOT)
        .parent()
        .unwrap()
        .to_path_buf()
}

fn log_event(event: &str) {
    let state = root().join(".runtime/mobile");
    let _ = fs::create_dir_all(&state);
    if let Ok(mut file) = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(state.join("desktop.log"))
    {
        let _ = writeln!(file, "{} {event}", crate::unique_stamp());
    }
}

fn script(name: &str, public: bool) -> Result<String, String> {
    let mut command = background_command("powershell.exe");
    command
        .current_dir(root())
        .args([
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
        ])
        .arg(root().join("tools").join(name));
    if public {
        command.arg("-Public");
    }
    let result = if name == "status-mobile.ps1" {
        command
            .output()
            .map(|output| (output.status, output.stdout))
    } else {
        // Long-lived Windows children can retain capture pipes after PowerShell exits.
        command
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| (status, Vec::new()))
    };
    let (exit_status, stdout) = result.map_err(|_| {
        log_event("mobile script could not launch");
        "無法執行手機連線工具，請確認專案與 PowerShell 安裝。".to_string()
    })?;
    if !exit_status.success() {
        log_event("mobile script failed");
        // Never include subprocess output: the status response contains a private code.
        return Err("手機連線操作失敗。請確認網路、Python 與 cloudflared；若有其他操作進行中請稍候。詳見 .runtime/mobile/desktop-control.log。".into());
    }
    Ok(String::from_utf8_lossy(&stdout).into_owned())
}

fn status() -> Result<MobileStatus, String> {
    let json = script("status-mobile.ps1", false)?;
    serde_json::from_str(json.trim_start_matches('\u{feff}').trim()).map_err(|_| {
        log_event("mobile status response invalid");
        "無法讀取手機連線狀態，請重新整理。".into()
    })
}

#[tauri::command]
pub(crate) async fn mobile_status() -> Result<MobileStatus, String> {
    tauri::async_runtime::spawn_blocking(status)
        .await
        .map_err(|_| "手機狀態查詢中斷。".to_string())?
}

async fn control(start: bool) -> Result<MobileStatus, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = CONTROL
            .try_lock()
            .map_err(|_| "手機連線正在啟動或停止，請稍候。".to_string())?;
        log_event(if start {
            "mobile start requested"
        } else {
            "mobile stop requested"
        });
        let current = status()?;
        if start && current.running {
            return Ok(current);
        }
        if current.registered {
            script("stop-mobile.ps1", false)?;
        }
        if start {
            script("start-mobile.ps1", true)?;
        }
        let result = status()?;
        if start && !result.running {
            log_event("mobile start health check failed");
            return Err("手機連線尚未就緒，請重新整理或重新連線。".into());
        }
        log_event(if start {
            "mobile started"
        } else {
            "mobile stopped"
        });
        Ok(result)
    })
    .await
    .map_err(|_| "手機連線操作中斷。".to_string())?
}

#[tauri::command]
pub(crate) async fn start_mobile() -> Result<MobileStatus, String> {
    control(true).await
}

#[tauri::command]
pub(crate) async fn stop_mobile() -> Result<MobileStatus, String> {
    control(false).await
}
