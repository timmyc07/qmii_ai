# 千迷AI（qmii_ai）

千迷AI是 Windows 本機圖片生成與修改工具，快速功能使用 Qwen Image 2.1 Turbo，另提供兩組獨立的 ComfyUI 工作流。

## 功能

- 快速生成：文字生圖，或將最多四張圖片逐張修改。
- 多圖參考：使用 2～4 張圖片融合生成一張新圖。
- SuperDuper：以 ComfyUI 雙階段工作流搭配 `pussyV2` 與局部細修 LoRA 進行文字生圖；上傳圖片時依提示詞逐張編輯。
- NSFW Adv 群組：依模型作者建議組合 Qwen Image FP8、NSFW Adv LoKr、Lightning 8-step LoRA、RES4LYF `res_2s` 與 `bong_tangent`；支援文字生圖、圖片逐張重繪與重繪強度調整。
- 精準模式：可選擇以 Qwen Image 2.1 PE 模型及使用者提供模板先重寫提示詞；桌面與手機共用開關。
- 創作設定：可調整寬度、高度、Turbo 步數、CFG、種子與負面提示詞；右側欄會說明每項作用與調高／調低的影響，選用值保存在主機設定，不放入 `.env`。
- 跨裝置工作室：桌面與手機網頁共用佇列、提示詞設定及作品庫。

兩組 ComfyUI 配方彼此隔離，快速生成仍使用原本的 Qwen Image 2.1 Turbo。

## 本機路徑

- 原始碼：`D:\codes\qmii_ai`
- Turbo 執行環境與模型：`D:\AI\Qwen-Image-2.1-Turbo`
- ComfyUI SuperDuper 執行環境：`D:\AI\QwenImage21SuperDuper`
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
