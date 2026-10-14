# 安裝與維運

## 支援範圍

目前發行版是針對這台 Windows 電腦的本機產品環境。模型位置維持在 `D:\AI`，ComfyUI Desktop 使用目前使用者的 LocalAppData 安裝位置。

## 必要元件

- Windows 10/11
- Rust stable MSVC 與 Microsoft C++ Build Tools
- Microsoft Edge WebView2 Runtime
- ComfyUI Desktop（目前驗證版本 0.39.2）
- Python 3.10+（使用 ComfyUI 的 `.venv`）

## 建置

在 repo 根目錄執行：

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup-workflow.ps1
powershell -ExecutionPolicy Bypass -File tools\verify-models.ps1
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

成品位於 `dist\千迷AI.exe` 與 `dist\千迷AI-0.2.5.exe`。Rust 編譯快取位於 `src-tauri\target`，不會提交到 Git。

手機網頁與PWA的啟動、私人連線碼及HTTPS連線方式見 [手機使用說明](MOBILE.md)。桌面版0.2.5新增與手機服務共用的GPU鎖。

## 執行與疑難排解

- 選擇「Qwen 2.1 工作流」時，程式會檢查 `127.0.0.1:8188/system_stats`，需要時自動啟動 ComfyUI。
- 首次載入約 17 GB 的 Qwen 2.1 模型會比後續生成久。
- ComfyUI 啟動日誌位於 `.runtime\qwen21-nsfw-pose-skill\comfyui.log`。
- ComfyUI 是共用背景服務；關閉千迷AI不會強制停止使用者原本可能正在使用的 ComfyUI。
- 若 8188 被非 ComfyUI 程式占用，千迷AI會停止並顯示明確錯誤。

## 回滾

`dist` 內保留帶版本號的執行檔。需要回滾時，關閉千迷AI，將上一版複製為 `dist\千迷AI.exe` 即可；模型與使用者輸出不受影響。
