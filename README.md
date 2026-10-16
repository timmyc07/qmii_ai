# 千迷AI（qmii_ai）

千迷AI是 Windows 本機圖片生成與修改工具，只使用 Qwen Image 2.1 Turbo。

## 功能

- 快速生成：文字生圖，或將最多四張圖片逐張修改。
- 多圖參考：使用 2～4 張圖片融合生成一張新圖。
- 創作設定：可調整寬度、高度、Turbo 步數、CFG、種子與負面提示詞；右側欄會說明每項作用與調高／調低的影響，選用值保存在主機設定，不放入 `.env`。
- 跨裝置工作室：桌面與手機網頁共用佇列、提示詞設定及作品庫。

專案不再包含 ComfyUI、其他生成模型或 LoRA 的整合、安裝與驗證程式。

## 本機路徑

- 原始碼：`D:\codes\qmii_ai`
- Turbo 執行環境與模型：`D:\AI\Qwen-Image-2.1-Turbo`
- 生成圖片：`D:\codes\qmii_ai\output`
- 編譯成品：`D:\codes\qmii_ai\dist`

## 建置

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
node tools\test-mobile-ui.cjs
node tools\test-studio-ui.cjs
node tools\test_conversation_ui.cjs
cargo check --manifest-path src-tauri\Cargo.toml
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

手機連線與維運方式見 [手機網頁說明](docs/MOBILE.md)，本機需求見 [安裝說明](docs/INSTALL.md)。
