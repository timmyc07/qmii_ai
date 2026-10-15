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
    fixed_prompt: String,
    #[serde(default)]
    revision: String,
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    index: usize,
    total: usize,
    message: String,
    done: bool,
    image: Option<String>,
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
async fn creation_library() -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        serde_json::from_str(&bridge("library", serde_json::Value::Null, None)?)
            .map_err(|e| e.to_string())
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
    workflow: String,
    lora: String,
    lora_strength: f64,
    parameters: serde_json::Value,
) -> Result<(), String> {
    if prompt.trim().is_empty() || prompt.len() > 32000 || images.len() > 4 {
        return Err("請檢查提示詞與圖片數量（最多 4 張）。".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        bridge(
            "generate",
            serde_json::json!({"prompt": prompt, "images": images, "workflow": workflow,
                "lora": lora, "lora_strength": lora_strength, "parameters": parameters}),
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
            mobile_connection::mobile_status,
            mobile_connection::start_mobile,
            mobile_connection::stop_mobile,
            generate_images,
            studio_jobs,
            creation_library,
            window_minimize,
            window_toggle_maximize,
            window_close,
            window_start_dragging
        ])
        .run(tauri::generate_context!())
        .expect("啟動千迷AI失敗");
}
