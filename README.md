# 千迷AI（qmii_ai）

千迷AI是 Windows 本機圖片生成與圖片修改桌面產品。介面使用 Tauri 2；模型在本機執行，不會提交到 GitHub。

## 目前功能

- 快速生成：沿用 Qwen Image 2.1 Turbo 本機推理。
- Qwen 2.1 工作流：整合上游 Route ① T2I 與 Route ② Edit。
- 圖片修改訊息送出後，聊天只顯示圖片；提示詞仍會完整傳給模型，但不顯示在聊天內容。
- 支援多張圖片依序修改、固定提示詞與自訂提示詞按鈕。

> VNCCS Route ④（136 個精確 3D 姿勢）需要額外的 VNCCS 節點、LoRA 與 CDP 瀏覽器控制器，目前不包含在產品介面中。

## 專案位置

- 原始碼：`D:\codes\qmii_ai`
- 編譯成品：`D:\codes\qmii_ai\dist`
- 生成圖片：`D:\codes\qmii_ai\output`
- ComfyUI 共用模型：`D:\AI\ComfyUI-Models`（維持原位置）
- Turbo 模型：`D:\AI\Qwen-Image-2.1-Turbo`（維持原位置）

## 本機準備與建置

1. 執行 `powershell -ExecutionPolicy Bypass -File tools\setup-workflow.ps1` 準備工作流。
2. 執行 `powershell -ExecutionPolicy Bypass -File tools\verify-models.ps1` 驗證模型。
3. 執行 `powershell -ExecutionPolicy Bypass -File tools\build.ps1` 建置產品。

建置腳本會將 portable EXE 複製到 `dist\千迷AI.exe`。`dist`、模型、日誌、生成圖片與本機工作流 runtime 均由 `.gitignore` 排除。

更多資訊請見 [安裝與維運說明](docs/INSTALL.md)、[模型清單](docs/MODELS.md) 與 [工作流說明](docs/WORKFLOWS.md)。

## 第三方來源

Qwen 2.1 工作流參考 [Arekejoker/qwen21-nsfw-pose-skill](https://github.com/Arekejoker/qwen21-nsfw-pose-skill)。該上游目前沒有附 LICENSE，因此本 repo 不再散布其程式碼；安裝腳本只在本機取得固定版本，`.runtime` 不會提交。
