# 千迷AI（qmii_ai）

千迷AI是 Windows 本機圖片與影片創作工具，提供 Qwen Image 圖片生成、修改及 MiniMax H3 圖片生影片。

## 功能

- 快速生成：文字生圖，或將最多四張圖片逐張修改。
- 多圖參考：使用 2～4 張圖片融合生成一張新圖。
- SuperDuper：以 ComfyUI 雙階段工作流搭配 `pussyV2` 與局部細修 LoRA 進行文字生圖；上傳圖片時依提示詞逐張編輯。
- NSFW Adv 群組：依模型作者建議組合 Qwen Image FP8、NSFW Adv LoKr、Lightning 8-step LoRA、RES4LYF `res_2s` 與 `bong_tangent`；支援文字生圖、圖片逐張重繪與重繪強度調整。
- 精準模式：保留提示詞原文，僅附加使用者模板中適用的生成規範；所有圖片模式適用，桌面與手機共用開關，不呼叫重寫模型。
- 創作設定：可調整寬度、高度、Turbo 步數、CFG、種子與負面提示詞；右側欄會說明每項作用與調高／調低的影響，選用值保存在主機設定，不放入 `.env`。
- 跨裝置工作室：桌面與手機網頁共用佇列、提示詞設定及作品庫。

兩組 ComfyUI 配方彼此隔離，快速生成仍使用原本的 Qwen Image 2.1 Turbo。

## 圖片生影片

頂部「圖片創作／圖片生影片」會直接切換獨立頁面，各自保留當次草稿。
影片模式沿用圖片聊天室：在底部上傳一張首幀圖片、填寫 H3 的畫面／動作／聲音提示詞，在右側設定片長、尺寸與種子後送出。
對話區獨立捲動，輸入框固定於底部；往上閱讀時新影片不會強制拉回最底部，可按「回到最新」。切換模式會保留各自的草稿、附件與閱讀位置。
可先載入橘貓範例了解提示詞格式；請讓描述對應實際圖片，時間碼不要超過片長。

- 配方依 `verboa-h3-i2v.json`：首幀置中裁切、H3 FL2VA INT8、4-step Turbo LoRA、`res_multistep`、`simple`、Basic Guider、24 fps 原生音訊。
- 預設 512×896、12 秒；幀數向上對齊 `17k+5`，12 秒實際為 294 幀。768p 有更高的顯存與耗時需求。
- MP4 可在影片頁與共用任務播放、下載，並保留在 `output/mobile/<任務編號>/0.mp4`，手機作品庫也能播放。
- H3 沿用千迷 AI 的 ComfyUI Portable（`D:\AI\QwenImage21SuperDuper`、本機連接埠 8191），不需開啟 Comfy Desktop。
- 模型來源為已下載的 `D:\AI-Manju\Models`；首次使用以硬連結加入 Portable 的模型目錄，不複製大型權重。需 H3 主模型、Qwen3-VL 32B NVFP4 編碼器、影片／音訊 VAE 與 4-step Turbo LoRA。NVFP4 編碼器依原工作流使用 RTX 50 系列配方。
- 固定 4 步與音訊配方；片長、尺寸、種子可在影片頁儲存為此模式預設，不使用 `.env`。此版本只接入圖片生影片。

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
