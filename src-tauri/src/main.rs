#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod background_process;
mod mobile_connection;

use background_process::background_command;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Command, Stdio},
    time::{SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter};

const OUTPUT_ROOT: &str = r"D:\codes\qmii_ai\output";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Preset {
    #[serde(default = "default_preset_id")]
    id: String,
    name: String,
    prompt: String,
    #[serde(default)]
    negative: String,
}

fn default_preset_id() -> String {
    format!("legacy-{}", unique_stamp())
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct Settings {
    #[serde(default)]
    presets: Vec<Preset>,
    #[serde(default)]
    precise_mode: bool,
    #[serde(default)]
    generation: serde_json::Map<String, serde_json::Value>,
    #[serde(default)]
    revision: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    job_id: Option<String>,
    index: usize,
    total: usize,
    message: String,
    done: bool,
    image: Option<String>,
    video: Option<String>,
    error: Option<String>,
}

fn bridge(
    action: &str,
    payload: serde_json::Value,
    app: Option<AppHandle>,
) -> Result<String, String> {
    let root = PathBuf::from(OUTPUT_ROOT).parent().unwrap().to_path_buf();
    let python = root.join(r".runtime\mobile-venv\Scripts\python.exe");
    if !python.is_file() {
        let status = background_command("powershell.exe")
            .current_dir(&root)
            .args([
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
            ])
            .arg(root.join("tools/start-mobile.ps1"))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|_| "無法安裝工作室執行環境。".to_string())?;
        if !status.success() {
            return Err("工作室執行環境安裝失敗，請檢查主機連線日誌。".into());
        }
    }
    let mut child = background_command(python)
        .current_dir(&root)
        .args(["-X", "utf8", "-m", "mobile.desktop", action])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|_| "無法啟動工作室，請先完成執行環境安裝。".to_string())?;
    let input = serde_json::to_vec(&payload).map_err(|e| e.to_string())?;
    child
        .stdin
        .take()
        .unwrap()
        .write_all(&input)
        .map_err(|e| e.to_string())?;
    let mut output = String::new();
    for line in BufReader::new(child.stdout.take().unwrap()).lines() {
        let line = line.map_err(|e| e.to_string())?;
        if let Some(ref app) = app {
            let progress: Progress = serde_json::from_str(&line).map_err(|e| e.to_string())?;
            let _ = app.emit("generation-progress", progress);
        } else {
            output.push_str(&line);
        }
    }
    let result = child.wait_with_output().map_err(|e| e.to_string())?;
    if !result.status.success() {
        return Err(String::from_utf8_lossy(&result.stderr).trim().to_string());
    }
    Ok(output)
}

#[tauri::command]
async fn load_settings() -> Result<Settings, String> {
    tauri::async_runtime::spawn_blocking(|| {
        serde_json::from_str(&bridge("load_settings", serde_json::Value::Null, None)?)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn save_settings(settings: Settings) -> Result<Settings, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let value = serde_json::to_value(settings).map_err(|e| e.to_string())?;
        serde_json::from_str(&bridge("save_settings", value, None)?).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn studio_jobs() -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        serde_json::from_str(&bridge("jobs", serde_json::Value::Null, None)?)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn import_svi_lora(path: String) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        serde_json::from_str(&bridge(
            "import_svi_lora",
            serde_json::json!({"path": path}),
            None,
        )?)
        .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn cancel_generation(job_id: String) -> Result<(), String> {
    if job_id.len() != 32 || !job_id.bytes().all(|value| value.is_ascii_hexdigit()) {
        return Err("找不到任務。".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        bridge("cancel", serde_json::json!({"job_id": job_id}), None).map(|_| ())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn google_drive(
    action: String,
    value: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let command = match action.as_str() {
        "status" => "drive_status",
        "save" => "save_drive",
        "connect" => "connect_drive",
        _ => return Err("不支援的 Google Drive 操作。".into()),
    };
    tauri::async_runtime::spawn_blocking(move || {
        serde_json::from_str(&bridge(command, value, None)?).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn open_output_folder() -> Result<(), String> {
    fs::create_dir_all(OUTPUT_ROOT).map_err(|e| e.to_string())?;
    Command::new("explorer.exe")
        .arg(OUTPUT_ROOT)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn window_minimize(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .minimize()
        .map_err(|e| format!("無法最小化視窗：{e}"))
}

#[tauri::command]
fn window_toggle_maximize(window: tauri::WebviewWindow) -> Result<(), String> {
    if window
        .is_maximized()
        .map_err(|e| format!("無法讀取視窗狀態：{e}"))?
    {
        window
            .unmaximize()
            .map_err(|e| format!("無法還原視窗：{e}"))
    } else {
        window
            .maximize()
            .map_err(|e| format!("無法最大化視窗：{e}"))
    }
}

#[tauri::command]
fn window_close(window: tauri::WebviewWindow) -> Result<(), String> {
    window.close().map_err(|e| format!("無法關閉視窗：{e}"))
}

#[tauri::command]
fn window_start_dragging(window: tauri::WebviewWindow) -> Result<(), String> {
    window
        .start_dragging()
        .map_err(|e| format!("無法拖曳視窗：{e}"))
}

#[tauri::command]
async fn generate_images(
    app: AppHandle,
    prompt: String,
    images: Vec<String>,
    last_image: Option<String>,
    workflow: String,
    parameters: serde_json::Value,
    precise_mode: bool,
) -> Result<(), String> {
    if prompt.trim().is_empty() || prompt.len() > 32000 || images.len() > 4 {
        return Err("請檢查提示詞與圖片數量（最多 4 張）。".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        bridge(
            "generate",
            serde_json::json!({"prompt": prompt, "images": images, "last_image": last_image, "workflow": workflow,
                "parameters": parameters, "precise_mode": precise_mode}),
            Some(app),
        )
        .map(|_| ())
    })
    .await
    .map_err(|e| e.to_string())?
}

fn unique_stamp() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            load_settings,
            save_settings,
            open_output_folder,
            google_drive,
            mobile_connection::mobile_status,
            mobile_connection::start_mobile,
            mobile_connection::stop_mobile,
            generate_images,
            cancel_generation,
            studio_jobs,
            import_svi_lora,
            window_minimize,
            window_toggle_maximize,
            window_close,
            window_start_dragging
        ])
        .run(tauri::generate_context!())
        .expect("啟動千迷AI失敗");
}

#[cfg(test)]
mod tests {
    use super::{Preset, Settings};

    #[test]
    fn preset_preserves_separate_negative_prompt() {
        let mut preset: Preset = serde_json::from_value(serde_json::json!({
            "id": "one", "name": "花園", "prompt": "正向描述"
        }))
        .unwrap();
        assert_eq!(preset.negative, "");
        preset.negative = "模糊\n<水印>".into();
        let value = serde_json::to_value(preset).unwrap();
        assert_eq!(value["prompt"], "正向描述");
        assert_eq!(value["negative"], "模糊\n<水印>");
    }

    #[test]
    fn settings_uses_current_shared_fields() {
        let value = serde_json::to_value(Settings::default()).unwrap();
        assert_eq!(value["preciseMode"], false);
        assert_eq!(value["generation"], serde_json::json!({}));
        assert!(value.get("fixedPrompt").is_none());
    }
}
