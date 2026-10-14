#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod background_process;

use background_process::background_command;
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Emitter};

const MODEL_ROOT: &str = r"D:\AI\Qwen-Image-2.1-Turbo";
const OUTPUT_ROOT: &str = r"D:\codes\qmii_ai\output";
const POSE_ROOT: &str = r"D:\codes\qmii_ai\.runtime\qwen21-nsfw-pose-skill";
const COMFY_MODELS: &str = r"D:\AI\ComfyUI-Models";
const COMFY_PYTHON: &str = r"C:\Users\Yumai\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\.venv\Scripts\python.exe";
const COMFY_ROOT: &str =
    r"C:\Users\Yumai\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI";
const COMFY_SHARED: &str = r"C:\Users\Yumai\AppData\Local\Comfy-Desktop\ComfyUI-Shared";
const DEFAULT_POSE_LORA: &str = "qwen2_1-femaledVaginus-nsfw-v1_3-fine_L22-31.safetensors";
const EDIT_POSE_LORA: &str = "qwen21-nsfw-image-edit.safetensors";
const SIGMA: &str = "1.0,0.978453,0.95418,0.926626,0.89508,0.845148,0.704534,0.414568,0.0";

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
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct Progress {
    index: usize,
    total: usize,
    message: String,
    done: bool,
    image: Option<String>,
    error: Option<String>,
}

fn settings_path() -> PathBuf {
    PathBuf::from(OUTPUT_ROOT).join("qianmi_settings.json")
}

#[tauri::command]
fn load_settings() -> Result<Settings, String> {
    let path = settings_path();
    if path.exists() {
        let text = fs::read_to_string(path).map_err(|e| format!("讀取提示詞設定失敗：{e}"))?;
        return serde_json::from_str(&text).map_err(|e| format!("提示詞設定格式錯誤：{e}"));
    }

    // Import the existing Flutter app's settings on the first Tauri launch.
    let mut settings = Settings::default();
    let old_presets = PathBuf::from(OUTPUT_ROOT).join("prompt_templates.json");
    if old_presets.exists() {
        let text = fs::read_to_string(old_presets).map_err(|e| format!("讀取舊版按鈕失敗：{e}"))?;
        settings.presets =
            serde_json::from_str(&text).map_err(|e| format!("舊版按鈕資料格式錯誤：{e}"))?;
    }
    let old_fixed_prompt = PathBuf::from(OUTPUT_ROOT).join("fixed_prompt.txt");
    if old_fixed_prompt.exists() {
        settings.fixed_prompt = fs::read_to_string(old_fixed_prompt)
            .map_err(|e| format!("讀取舊版固定提示詞失敗：{e}"))?;
    }
    Ok(settings)
}

#[tauri::command]
fn save_settings(settings: Settings) -> Result<(), String> {
    fs::create_dir_all(OUTPUT_ROOT).map_err(|e| format!("建立輸出資料夾失敗：{e}"))?;
    let text = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    fs::write(settings_path(), text).map_err(|e| format!("儲存提示詞設定失敗：{e}"))
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
) -> Result<(), String> {
    let prompt = prompt.trim().to_owned();
    if prompt.is_empty() {
        return Err("請先輸入提示詞，或設定固定提示詞。".into());
    }
    let images = if images.is_empty() {
        vec![String::new()]
    } else {
        images
    };
    tauri::async_runtime::spawn_blocking(move || {
        let _gpu_guard = acquire_gpu()?;
        if workflow == "pose" {
            run_pose_batch(app, prompt, images)
        } else {
            run_batch(app, prompt, images)
        }
    })
    .await
    .map_err(|e| format!("生成工作中斷：{e}"))?
}

fn acquire_gpu() -> Result<fs::File, String> {
    let runtime = PathBuf::from(OUTPUT_ROOT)
        .parent()
        .ok_or("無法定位產品資料夾。")?
        .join(".runtime");
    fs::create_dir_all(&runtime).map_err(|e| format!("無法建立 GPU 鎖目錄：{e}"))?;
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(runtime.join("gpu-task.lock"))
        .map_err(|e| format!("無法建立 GPU 鎖：{e}"))?;
    if let Err(error) = file.try_lock() {
        if let Ok(mut log) = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(runtime.join("gpu.log"))
        {
            let _ = writeln!(
                log,
                "{} desktop GPU lock unavailable: {error}",
                unique_stamp()
            );
        }
        return Err("GPU 正由手機或其他千迷AI工作使用，請稍後再試。".into());
    }
    Ok(file)
}

fn run_pose_batch(app: AppHandle, prompt: String, images: Vec<String>) -> Result<(), String> {
    validate_pose_dependencies(images.first().is_some_and(|image| !image.is_empty()))?;
    ensure_comfyui_running()?;
    fs::create_dir_all(OUTPUT_ROOT).map_err(|e| format!("無法建立輸出資料夾：{e}"))?;
    let total = images.len();
    let mut successes = 0usize;
    let mut failures = 0usize;

    for (index, image) in images.iter().enumerate() {
        let _ = app.emit(
            "generation-progress",
            Progress {
                index: index + 1,
                total,
                message: format!(
                    "Qwen 2.1 姿勢工作流：正在處理第 {}/{} 張…",
                    index + 1,
                    total
                ),
                done: false,
                image: None,
                error: None,
            },
        );
        let output = PathBuf::from(OUTPUT_ROOT).join(format!("qianmi-pose-{}.png", unique_stamp()));
        let result = run_pose_one(&prompt, image, &output);
        let (message, image_path, error) = match result {
            Ok(()) => {
                successes += 1;
                (
                    format!("第 {}/{} 張姿勢工作流完成", index + 1, total),
                    Some(output.to_string_lossy().to_string()),
                    None,
                )
            }
            Err(error) => {
                failures += 1;
                (
                    format!("第 {}/{} 張姿勢工作流失敗", index + 1, total),
                    None,
                    Some(error),
                )
            }
        };
        let _ = app.emit(
            "generation-progress",
            Progress {
                index: index + 1,
                total,
                message,
                done: false,
                image: image_path,
                error,
            },
        );
    }

    let _ = app.emit(
        "generation-progress",
        Progress {
            index: total,
            total,
            message: format!("姿勢工作流完成：成功 {successes} 張，失敗 {failures} 張。"),
            done: true,
            image: None,
            error: None,
        },
    );
    Ok(())
}

fn ensure_comfyui_running() -> Result<(), String> {
    let address: SocketAddr = "127.0.0.1:8188"
        .parse()
        .map_err(|e| format!("ComfyUI 位址無效：{e}"))?;
    if comfyui_is_healthy(&address) {
        return Ok(());
    }
    if TcpStream::connect_timeout(&address, Duration::from_millis(500)).is_ok() {
        return Err("連接埠 8188 已被其他程式占用，但不是可用的 ComfyUI 服務。".into());
    }

    let main_py = PathBuf::from(COMFY_ROOT).join("main.py");
    let extra_paths = PathBuf::from(POSE_ROOT).join(r"install\windows_extra_model_paths.yaml");
    let input_dir = PathBuf::from(COMFY_SHARED).join("input");
    let output_dir = PathBuf::from(COMFY_SHARED).join("output");
    fs::create_dir_all(&input_dir).map_err(|e| format!("無法建立 ComfyUI 輸入資料夾：{e}"))?;
    fs::create_dir_all(&output_dir).map_err(|e| format!("無法建立 ComfyUI 輸出資料夾：{e}"))?;
    let log_path = PathBuf::from(POSE_ROOT).join("comfyui.log");
    let mut log_file = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| format!("無法建立 ComfyUI 日誌 {}：{e}", log_path.display()))?;
    let _ = writeln!(
        log_file,
        "\n===== 千迷AI 啟動 ComfyUI {} =====",
        unique_stamp()
    );
    let stderr_log = log_file
        .try_clone()
        .map_err(|e| format!("無法開啟 ComfyUI 錯誤日誌：{e}"))?;

    let mut cmd = background_command(COMFY_PYTHON);
    cmd.current_dir(COMFY_ROOT)
        .arg(main_py)
        .args([
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
            "--disable-auto-launch",
        ])
        .arg("--extra-model-paths-config")
        .arg(extra_paths)
        .arg("--input-directory")
        .arg(input_dir)
        .arg("--output-directory")
        .arg(output_dir)
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(stderr_log))
        .spawn()
        .map_err(|e| format!("無法自動啟動 ComfyUI：{e}。日誌：{}", log_path.display()))?;

    for _ in 0..90 {
        if comfyui_is_healthy(&address) {
            return Ok(());
        }
        thread::sleep(Duration::from_secs(1));
    }
    Err(format!(
        "ComfyUI 自動啟動逾時，請查看日誌：{}",
        log_path.display()
    ))
}

fn comfyui_is_healthy(address: &SocketAddr) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(address, Duration::from_millis(800)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    if stream
        .write_all(
            b"GET /system_stats HTTP/1.1\r\nHost: 127.0.0.1:8188\r\nConnection: close\r\n\r\n",
        )
        .is_err()
    {
        return false;
    }
    let mut response = [0u8; 256];
    match stream.read(&mut response) {
        Ok(read) if read > 0 => {
            let head = String::from_utf8_lossy(&response[..read]);
            head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
        }
        _ => false,
    }
}

fn validate_pose_dependencies(edit_mode: bool) -> Result<(), String> {
    let required = [
        PathBuf::from(POSE_ROOT).join(r"scripts\qwen_pose_test.py"),
        PathBuf::from(COMFY_PYTHON),
        PathBuf::from(COMFY_MODELS)
            .join(r"diffusion_models\qwen_image_2.1_int8_convrot.safetensors"),
        PathBuf::from(COMFY_MODELS).join(r"text_encoders\qwen3vl_8b_int8_convrot.safetensors"),
        PathBuf::from(COMFY_MODELS).join(r"vae\qwen_image_2.1_vae_bf16.safetensors"),
    ];
    if let Some(path) = required.iter().find(|path| !path.exists()) {
        return Err(format!(
            "Qwen 2.1 姿勢工作流尚未安裝完整，缺少：{}",
            path.display()
        ));
    }
    if !edit_mode {
        let lora = PathBuf::from(COMFY_MODELS)
            .join("loras")
            .join(DEFAULT_POSE_LORA);
        if !lora.exists() {
            return Err(format!("文字姿勢工作流缺少預設 LoRA：{}", lora.display()));
        }
    }
    Ok(())
}

fn run_pose_one(prompt: &str, image: &str, output: &Path) -> Result<(), String> {
    let edit_mode = !image.is_empty();
    let run_name = format!("qianmi_{}", unique_stamp());
    let seed = (unique_stamp() % 9_223_372_036_854_775_807).to_string();
    let script = PathBuf::from(POSE_ROOT).join(r"scripts\qwen_pose_test.py");
    let mut cmd = background_command(COMFY_PYTHON);
    cmd.current_dir(POSE_ROOT)
        .env("POSELAB", POSE_ROOT)
        .env(
            "QWEN_POSE_WORKFLOWS",
            PathBuf::from(POSE_ROOT).join("workflows"),
        )
        .env("COMFYUI_URL", "http://127.0.0.1:8188")
        .env(
            "MEDIA_LOCK_FILE",
            PathBuf::from(POSE_ROOT).join(".media-task.lock"),
        )
        .arg(script)
        .args([
            "--mode",
            if edit_mode { "edit" } else { "t2i" },
            "--name",
            &run_name,
            "--prompt",
            prompt,
        ])
        .args([
            "--out",
            output.to_str().unwrap_or_default(),
            "--seed",
            &seed,
        ]);

    if edit_mode {
        cmd.args([
            "--input",
            image,
            "--steps",
            "20",
            "--cfg",
            "3",
            "--sampler",
            "er_sde",
            "--scheduler",
            "beta",
        ]);
        let edit_lora = PathBuf::from(COMFY_MODELS)
            .join("loras")
            .join(EDIT_POSE_LORA);
        if prompt_requests_nsfw_edit(prompt) && edit_lora.exists() {
            cmd.args(["--lora", EDIT_POSE_LORA, "--lora-strength", "1.0"]);
        }
    } else {
        cmd.args([
            "--steps",
            "50",
            "--cfg",
            "2.5",
            "--sampler",
            "er_sde",
            "--scheduler",
            "beta",
            "--width",
            "1152",
            "--height",
            "1728",
            "--lora",
            DEFAULT_POSE_LORA,
            "--lora-strength",
            "1.0",
        ]);
    }

    let output_log = cmd
        .output()
        .map_err(|e| format!("無法啟動 Qwen 2.1 姿勢工作流：{e}"))?;
    if !output_log.status.success() {
        let stderr = String::from_utf8_lossy(&output_log.stderr);
        let stdout = String::from_utf8_lossy(&output_log.stdout);
        let log = if !stderr.trim().is_empty() {
            stderr
        } else {
            stdout
        };
        let tail = log
            .chars()
            .rev()
            .take(1800)
            .collect::<String>()
            .chars()
            .rev()
            .collect::<String>();
        return Err(format!(
            "姿勢工作流執行失敗。請確認 ComfyUI 已開啟並連線至 127.0.0.1:8188。\n{tail}"
        ));
    }
    if !output.exists() || output.metadata().map(|meta| meta.len()).unwrap_or(0) == 0 {
        return Err("姿勢工作流已結束，但沒有找到輸出圖片。".into());
    }
    Ok(())
}

fn prompt_requests_nsfw_edit(prompt: &str) -> bool {
    let lower = prompt.to_lowercase();
    [
        "脫衣",
        "脱衣",
        "裸體",
        "裸体",
        "裸露",
        "nude",
        "undress",
        "remove clothes",
        "nsfw",
    ]
    .iter()
    .any(|keyword| lower.contains(keyword))
}

fn run_batch(app: AppHandle, prompt: String, images: Vec<String>) -> Result<(), String> {
    fs::create_dir_all(OUTPUT_ROOT).map_err(|e| format!("無法建立輸出資料夾：{e}"))?;
    let total = images.len();
    let mut successes = 0usize;
    let mut failures = 0usize;

    for (index, image) in images.iter().enumerate() {
        let _ = app.emit(
            "generation-progress",
            Progress {
                index: index + 1,
                total,
                message: format!("正在處理第 {}/{} 張圖片…", index + 1, total),
                done: false,
                image: None,
                error: None,
            },
        );
        let output = PathBuf::from(OUTPUT_ROOT).join(format!("qianmi-{}.png", unique_stamp()));
        let prompt_file =
            PathBuf::from(OUTPUT_ROOT).join(format!(".qianmi-prompt-{}.txt", unique_stamp()));
        let result = (|| -> Result<(), String> {
            fs::write(&prompt_file, prompt.as_bytes())
                .map_err(|e| format!("寫入提示詞失敗：{e}"))?;
            let mut cmd = background_command(format!(r"{MODEL_ROOT}\sd-cli.exe"));
            cmd.current_dir(MODEL_ROOT).args([
                "--diffusion-model",
                &format!(r"{MODEL_ROOT}\models\Qwen-Image-2.1-Turbo-AD-Q4_K.gguf"),
                "--llm",
                &format!(
                    r"{MODEL_ROOT}\models\Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf"
                ),
                "--vae",
                &format!(r"{MODEL_ROOT}\models\qwen_image_2.1_vae_bf16.safetensors"),
                "--prompt-file",
                prompt_file.to_str().unwrap_or_default(),
                "--steps",
                "8",
                "--cfg-scale",
                "1.0",
                "--sampling-method",
                "euler",
                "--sigmas",
                SIGMA,
                "-W",
                "1024",
                "-H",
                "1024",
                "--diffusion-fa",
                "-o",
                output.to_str().unwrap_or_default(),
                "--backend",
                "cuda0",
                "--auto-fit",
                "on",
                "--max-vram",
                "cuda0=9",
            ]);
            if !image.is_empty() {
                cmd.args([
                    "--llm_vision", &format!(r"{MODEL_ROOT}\models\mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf"),
                    "--ref-image-args", "preset=qwen", "-r", image,
                ]);
            }
            let output_log = cmd.output().map_err(|e| format!("無法啟動本機模型：{e}"))?;
            if !output_log.status.success() {
                let stderr = String::from_utf8_lossy(&output_log.stderr);
                let stdout = String::from_utf8_lossy(&output_log.stdout);
                let log = if !stderr.trim().is_empty() {
                    stderr
                } else {
                    stdout
                };
                return Err(format!(
                    "模型處理失敗（代碼 {:?}）：{}",
                    output_log.status.code(),
                    log.chars()
                        .rev()
                        .take(1800)
                        .collect::<String>()
                        .chars()
                        .rev()
                        .collect::<String>()
                ));
            }
            if !output.exists() {
                return Err("模型結束但沒有找到輸出圖片。".into());
            }
            Ok(())
        })();
        let _ = fs::remove_file(&prompt_file);

        let (message, image_path, error) = match result {
            Ok(()) => {
                successes += 1;
                let path = output.to_string_lossy().to_string();
                (
                    format!("第 {}/{} 張完成", index + 1, total),
                    Some(path),
                    None,
                )
            }
            Err(error) => {
                failures += 1;
                (
                    format!("第 {}/{} 張失敗", index + 1, total),
                    None,
                    Some(error),
                )
            }
        };
        let _ = app.emit(
            "generation-progress",
            Progress {
                index: index + 1,
                total,
                message,
                done: false,
                image: image_path,
                error,
            },
        );
    }

    let _ = app.emit(
        "generation-progress",
        Progress {
            index: total,
            total,
            message: format!("批次完成：成功 {successes} 張，失敗 {failures} 張。"),
            done: true,
            image: None,
            error: None,
        },
    );
    Ok(())
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
            generate_images,
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
    use super::*;

    #[test]
    fn desktop_lock_blocks_the_mobile_worker() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let python = root.join(r".runtime\mobile-venv\Scripts\python.exe");
        let probe = "import sys\nfrom mobile.gpu import gpu_lock\ntry:\n with gpu_lock(timeout=0, path=sys.argv[1]): pass\nexcept TimeoutError:\n raise SystemExit(7)";
        let lock_path = root
            .join(".runtime")
            .join(format!("gpu-test-{}.lock", unique_stamp()));
        let guard = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .unwrap();
        guard.try_lock().unwrap();
        let status = Command::new(&python)
            .current_dir(&root)
            .args(["-c", probe, lock_path.to_str().unwrap()])
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(7));
        drop(guard);
        let status = Command::new(&python)
            .current_dir(&root)
            .args(["-c", probe, lock_path.to_str().unwrap()])
            .status()
            .unwrap();
        assert!(status.success());
        fs::remove_file(lock_path).unwrap();
    }
}
