# 安裝與維運

## 必要元件

- Windows 10/11
- Rust stable MSVC、Microsoft C++ Build Tools、Microsoft Edge WebView2 Runtime
- `D:\AI\Qwen-Image-2.1-Turbo` 的既有 Turbo 執行環境與模型
- 手機功能另需 Python 3.12+；公開連線需 `.runtime\cloudflared.exe`

不需要安裝 ComfyUI。

## 建置

在 repo 根目錄執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

成品位於 `dist\千迷AI.exe` 與 `dist\千迷AI-0.4.1.exe`。Rust 編譯快取位於 `src-tauri\target`，不會提交 Git。

## 疑難排解

- 確認 `D:\AI\Qwen-Image-2.1-Turbo\sd-cli.exe` 與 `models` 內的必要檔案存在。
- 模型首次載入較久；生成錯誤寫入 `.runtime\mobile\service.log`。
- 桌面與手機任務共用 `.runtime\gpu-task.lock`，同一時間只執行一個 Turbo 任務。

## 回滾

關閉千迷AI，將 `dist` 中上一版的版本檔複製為 `dist\千迷AI.exe`。模型與使用者輸出不受影響。
