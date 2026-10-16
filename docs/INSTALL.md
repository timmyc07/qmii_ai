# 安裝與維運

## 必要元件

- Windows 10/11
- Rust stable MSVC、Microsoft C++ Build Tools、Microsoft Edge WebView2 Runtime
- `D:\AI\Qwen-Image-2.1-Turbo` 的既有 Turbo 執行環境與模型
- ComfyUI 工作流與精準模式另需 `D:\AI\QwenImage21SuperDuper`（完整安裝約 50～60GB）
- 手機功能另需 Python 3.12+；公開連線需 `.runtime\cloudflared.exe`

安裝或修復最新版 ComfyUI Portable、SuperDuper、NSFW Adv 群組、精準模式與必要模型：

```powershell
powershell -ExecutionPolicy Bypass -File tools\install-superduper.ps1
```

SuperDuper 基礎模型由 Civitai 保護；第一次安裝請在本機 PowerShell 以 `-CivitaiToken` 傳入自己的 API token，或手動下載到安裝程式提示的目標路徑。Token 不寫入 `.env`、設定或 Git。NSFW Adv 群組、精準模式與其他公開模型不需要此 token。

## 建置

在 repo 根目錄執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

成品位於 `dist\千迷AI.exe` 與對應版本檔。Rust 編譯快取位於 `src-tauri\target`，不會提交 Git。

## 疑難排解

- 確認 `D:\AI\Qwen-Image-2.1-Turbo\sd-cli.exe` 與 `models` 內的必要檔案存在。
- 模型首次載入較久；生成錯誤寫入 `.runtime\mobile\service.log`。
- SuperDuper 的 ComfyUI 啟動記錄位於 `.runtime\superduper.log`。
- 桌面與手機任務共用 `.runtime\gpu-task.lock`，同一時間只執行一個 GPU 任務。

## 回滾

關閉千迷AI，將 `dist` 中上一版的版本檔複製為 `dist\千迷AI.exe`。模型與使用者輸出不受影響。
