# 千迷AI（qmii_ai）

千迷AI是 Windows 本機圖片與影片創作工具，提供 Qwen Image 圖片生成、修改及 MiniMax H3 圖片生影片。

## 功能

- 快速生成：文字生圖，或將最多四張圖片逐張修改。
- 多圖參考：使用 2～4 張圖片融合生成一張新圖。
- SuperDuper：以 ComfyUI 雙階段工作流搭配 `pussyV2` 與局部細修 LoRA 進行文字生圖；上傳圖片時依提示詞逐張編輯。
- NSFW Adv 群組：依模型作者建議組合 Qwen Image FP8、NSFW Adv LoKr、Lightning 8-step LoRA、RES4LYF `res_2s` 與 `bong_tangent`；支援文字生圖、圖片逐張重繪與重繪強度調整。
- 精準模式：保留提示詞原文，僅附加使用者模板中適用的生成規範；所有圖片模式適用，桌面與手機共用開關，不呼叫重寫模型。
- 創作設定：可調整寬度、高度、Turbo 步數、CFG、種子與負面提示詞；右側欄會說明每項作用與調高／調低的影響，選用值保存在主機設定，不放入 `.env`。
- 正向／負面提示詞分欄：桌面、手機輸入框與常用提示詞模板均分開填寫；負面提示詞可多行、可留白，套用模板時會一起帶入，空白模板會清除先前負面內容。負面欄移至輸入框旁，仍可隨模式預設儲存。CFG=1 時負面提示詞作用有限。
- 跨裝置工作室：桌面與手機網頁共用佇列、提示詞設定及作品庫。
- 強制終止：圖片與影片生成期間可按輸入區的「強制終止」，停止目前任務並保留已完成輸出；手機圖片工作室也可終止目前工作。

兩組 ComfyUI 配方彼此隔離，快速生成仍使用原本的 Qwen Image 2.1 Turbo。

## 圖片生影片

頂部「圖片創作／圖片生影片」會直接切換獨立頁面，各自保留當次草稿。
影片模式沿用圖片聊天室：在底部選取 1～4 張首幀圖片、填寫 H3 的畫面／動作／聲音提示詞，在右側設定片長、尺寸與種子後送出。每張照片套用相同提示詞與參數，依序各生成一支影片；固定種子逐張遞增。
對話區獨立捲動，輸入框固定於底部；往上閱讀時新影片不會強制拉回最底部，可按「回到最新」。切換模式會保留各自的草稿、附件與閱讀位置。
可先載入橘貓範例了解提示詞格式；請讓描述對應實際圖片，時間碼不要超過片長。

- 基於 `verboa-h3-i2v.json` 的 H3 FL2VA INT8 配方，依 Turbo 作者建議配對 Euler、Simple、步數與影音 shift；預設 4-step 768p（6／3），可切換已安裝的 8-step 544p（12／3）或原版 20～60 步（12／3、不載入 Turbo LoRA）。
- 預設 512×896、12 秒；幀數向上對齊 `17k+5`，12 秒實際為 294 幀。768p 有更高的顯存與耗時需求。
- MP4 每完成一支即可在影片頁與共用任務播放、下載，依序保留在 `output/mobile/<任務編號>/0.mp4`～`3.mp4`，手機作品庫也能播放。任一支失敗即停止此批次，已完成影片仍保留。
- H3 沿用千迷 AI 的 ComfyUI Portable（`D:\AI\QwenImage21SuperDuper`、本機連接埠 8191），不需開啟 Comfy Desktop。
- 模型來源為已下載的 `D:\AI-Manju\Models`；首次使用以硬連結加入 Portable 的模型目錄，不複製大型權重。需 H3 主模型、Qwen3-VL 32B NVFP4 編碼器、影片／音訊 VAE 與 4-step Turbo LoRA。NVFP4 編碼器依原工作流使用 RTX 50 系列配方。
- 右側可調整品質配方、片長、自訂寬高、種子、裁切／拉伸、縮放演算法、採樣器、LoRA 權重、影音 shift、聲音開關及 MP4 CRF；參數可儲存為影片預設，不使用 `.env`。
- 一致性輔助可選擇文字引導，以及不使用尾幀／各自以首幀作尾幀／自選一張共用尾幀。自選尾幀不佔用 4 張首幀額度。首尾幀是原生條件，不能保證中間每幀的身分；相同首尾幀可能減少動作。尾幀附件只在本次開啟期間保留。
- 可選 RefMod 身分參考，預設關閉；支援三種 H3 品質配方，每支只參考自己的首幀，保留原生首尾幀與影音流程。可能帶入背景或降低動作幅度，身分改善仍需比較。Qwen 圖片模型不相容，開關停用並顯示原因。
- 圖片修改與影片對話送出後只顯示附件，不展開長提示詞；提示詞仍可在共用任務中查看。
- H3 保留原生 CFG 蒸餾配方，只有正向條件；影片頁與影片任務詳情不顯示負面欄，套用通用模板時只使用正向內容，不會傳送或併入負面提示詞。
- 詳見 [H3 參數與身分一致性核對](docs/H3.md)。此版本只接入圖片生影片。

## 本機路徑

本機效能、模型切換及 Wan 5B 實驗比較的固定案例與指令見 [本機生成基準](docs/BENCHMARKS.md)。

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
