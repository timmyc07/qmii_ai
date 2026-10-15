# 跨裝置工作室 0.3.0

Windows 主機保存模型、設定、任務與圖片；桌面安裝版透過私人橋接呼叫與瀏覽器相同的 FastAPI。所有生成由同一 SQLite 佇列與單一 worker 處理，worker 再取得主機 GPU 鎖。Rust 不再維護另一套生成參數。

## 創作規格

| 工作流 | 輸入圖片 | 行為 | 生成設定 |
| --- | --- | --- | --- |
| 快速生成 | 0～4 張 | 無圖片時文字生圖；有圖片時逐張修改 | Turbo、8 steps、CFG 1、Euler、1024 × 1024、既有 sigma 配方 |
| 多圖參考 | 2～4 張 | 所有參考圖搭配同一提示詞融合為一張；不拼貼 | Turbo、8 steps、CFG 1、Euler、1024 × 1024、遞增參考索引 |
| Qwen 2.1 T2I | 0 張 | 文字生圖一張 | 50 steps、CFG 2.5、er_sde、beta、1152 × 1728、既有 T2I LoRA、強度 1 |
| Qwen 2.1 Edit | 1～4 張 | 逐張修改 | 20 steps、CFG 3、er_sde、beta；沿用既有關鍵詞與已安裝 Edit LoRA 的自動選擇規則 |

各端都將固定提示詞與本次提示詞以空行相接，合計最多 8000 字。圖片限制統一為單張 12 MiB、2000 萬像素、PNG／JPEG／WebP／BMP；由服務解碼、套用 EXIF 方向並轉存 PNG。每日最多 200 張上傳，最多 8 個未完成任務。

模型設定沿用既有配方，本版沒有新增可調參數或 `.env` 選項。相同輸入使用同一配方，但每次隨機種子不同，不保證逐像素相同。

## 共用 API 與資料

| API | 用途 | 保護 |
| --- | --- | --- |
| POST `/api/login`、GET `/api/session`、POST `/api/logout` | 配對、工作階段、登出 | 私人連線碼、HttpOnly session；公開入口使用 Secure cookie |
| GET／PUT `/api/settings` | 讀寫固定提示詞與常用按鈕 | 登入；寫入另驗 Origin、CSRF、revision |
| POST `/api/uploads` | 正規化輸入圖片 | 登入、Origin、CSRF、大小與格式驗證 |
| POST／GET `/api/jobs`、GET `/api/jobs/{id}` | 提交、最近 30 筆任務、個別任務 | 登入；提交另驗 Origin、CSRF、request_id 去重 |
| GET `/api/jobs/{id}/images/{index}` | 批次完成圖片 | 登入；不回傳主機路徑 |
| GET `/api/library?offset=0` | 每頁 40 張作品 | 登入；涵蓋 output 下既有作品與新作品 |
| GET `/api/library/{id}` | 預覽與單張下載 | 登入；opaque ID，排除指向作品目錄外的連結 |

設定沿用 `output/qianmi_settings.json`。若尚未建立，讀取既有 `prompt_templates.json` 與 `fixed_prompt.txt`；首次儲存建立共用設定。寫入具跨程序鎖、暫存檔原子替換與版本衝突檢查。其他設備修改時，閒置桌面每五秒同步；網頁依任務輪詢週期（2～10 秒）同步。編輯中的內容不會被自動更新覆蓋；遇到衝突先重新載入再修改。

任務沿用 `.runtime/mobile/mobile.sqlite3`，既有資料不需重建。新圖片保存於 `output/mobile/{任務 ID}/`，既有桌面圖片保留原位。**完成圖片與任務不再於七天後刪除**；七天清理只處理過期 session 與不被待處理任務使用的上傳暫存。

## 操作

1. 開啟新版桌面程式。第一次需要 Python 3.12 以上與工作室執行環境；程式會在環境缺少時呼叫既有安裝腳本。
2. 桌面首次生成或查看「共用任務」會啟動本機工作室。模型仍需要先依安裝文件準備。
3. 透過「手機連線」啟動 HTTPS 入口；Mac、Windows 瀏覽器、手機或平板開啟同一網址，輸入私人連線碼。
4. 網頁左側提供常用按鈕管理與固定提示詞，按「儲存共用設定」後供其他設備使用。按常用按鈕會直接提交生成，與桌面相同。
5. 桌面以「共用任務」查看各設備的狀態與結果；網頁創作紀錄顯示同一佇列。桌面「作品集」開啟主機資料夾，網頁「作品庫」提供預覽及下載。
6. 停止連線會停止整個共用服務，等待目前 GPU 任務完成，保留尚未開始的任務。下次桌面生成或手動啟動時繼續處理。

切換本機服務至 HTTPS 模式時會安全排空並重啟同一資料來源；桌面任務輪詢允許短暫重新連線。關閉桌面視窗或瀏覽器不會取消主機任務。ComfyUI 維持只監聽 loopback；瀏覽器不直接取得模型路徑或存取 8188。

## 驗收狀態與限制

- 已通過 Python API、安全、資料保留、桌面 HTTP 橋接與佇列測試（使用替代 runner，無 GPU 消耗）。
- 已通過 Edge 自動化：提示詞按鈕管理與執行、衝突復原、作品預覽下載、桌面連線面板與共用任務；網頁測試寬度 360／390／768／1280／1440。
- 已完成 Rust 檢查與新版 release 打包。
- macOS Safari／Chrome、iPhone Safari、Android Chrome 真機與三端實際 GPU 圖片比對仍待驗收，不能將響應式測試視為實機認證。
- 尚未提供取消任務；既有配方集中於主機生成服務。0.3.5 新增桌面 LoRA 選單與強度設定。
- 作品庫目前掃描 output 下圖片並以原始解析度載入，圖片很多時會較慢；任務列表顯示最近 30 筆，較舊完成圖片仍可由作品庫存取。
- PWA 僅在曾成功連線並快取後可離線開啟介面；生成、登入、設定同步與私人圖片存取仍需要主機連線。
- 所有任務保留完整送出提示詞及來源資訊，僅經配對驗證後提供；既有桌面作品下載保留原檔及原 metadata。

## 更新與回復

0.3.0 將桌面生成改走共用 API；新增設定管理、版本衝突保護、響應式工作室、共用任務與永久作品庫。私人登入及主機連線管理沿用既有機制。

更新前先安全停止服務，備份 `output`、`.runtime/mobile` 與上一版本程式／原始碼；此安裝仍使用本機專案中的 Python、靜態頁面與工具，不能只複製 EXE 到其他電腦。

回復時先停止新版服務，執行保留的 `dist/千迷AI-0.2.10.exe` 可回到舊版桌面生成流程。若也要回復舊網頁服務，需還原先前備份的 `mobile` 與 `tools`；不要清除 output 或資料庫。舊版的七天清理政策會再次生效，還原舊服務前務必備份作品。不要同時啟動兩版服務。

## 開源參考

已搜尋 [ComfyUI-Remote](https://github.com/Adachi-Hougetsu/ComfyUI-Remote) 的 FastAPI／PWA 模式及 [somni](https://github.com/searcc/somni-comfyui) 的桌面與手機介面方向。採用本專案既有 FastAPI、PWA、SQLite、GPU 鎖與工作流工具，未複製參考專案原始碼。

## 0.3.1 介面修正

生成進度、圖片載入及完成通知只在停留對話底部時跟隨。往上捲動會停止跟隨，可按「回到最新」恢復；主動提交新任務時定位到最新訊息。側欄保持固定內容寬度，只對位移與透明度做動畫，主對話區不再於每幀改變寬度。

新增隔離的無畫面回歸測試 `node tools/test_conversation_ui.cjs`，涵蓋持續更新、延遲圖片、完成通知、小幅及鍵盤捲動、恢復跟隨與側欄收放。不會操作使用者的原生桌面或呼叫 GPU。

## 0.3.2 共用任務紀錄

- 桌面共用任務以最新優先顯示最近 30 筆，完整 Prompt 可展開閱讀；網頁創作紀錄也顯示完整 Prompt。
- 提交、首次開始、完成或失敗時間由主機記錄，依檢視設備的本地時間顯示。
- 桌面來源回報作業系統、電腦名稱及系統使用者；網頁來源回報系統、瀏覽器、PWA／網頁、設備識別碼及自行填寫的名稱。來源名稱不代表經驗證的個人帳號。
- 網頁設備識別碼保存在瀏覽器 localStorage；清除網站資料或更換瀏覽器會產生新碼。同一瀏覽器共用者需自行切換使用者名稱。
- 任務提交時保存來源快照，之後改名不改寫歷史。既有資料庫自動新增欄位，缺少的歷史資訊標示未記錄；不推算或補造。

## 0.3.3 啟動錯誤修正

- 桌面橋接程序使用 UTF-8 模式，錯誤輸出也明確使用 UTF-8，避免 Windows 中文環境顯示亂碼。
- 登入後檢查工作室 API 版本；舊服務會在上傳圖片與提交生成前提供明確的重啟提示，不再回報籠統的輸入格式錯誤。

## 0.3.5 右側創作設定與 LoRA

桌面將原本對話輸入框下方的四種工作流移到右側「創作設定」。窄視窗以頂部「創作設定」開啟右側抽屜；工作流、LoRA 與強度在生成期間鎖定。LoRA 根據工作流及是否上傳圖片篩選，移除圖片或切換模式後自動清除不再適用的選擇。

### 匯入與適配

執行 `powershell -ExecutionPolicy Bypass -File tools/import-library.ps1`，從使用者提供的 QWEN／CHROMA 目錄讀取檔案。六個 Qwen LoRA 複製至既有 `D:\AI\ComfyUI-Models\loras`，逐檔驗證 SHA256；原檔保留，已存在且內容不同的檔案不覆蓋。兩個 ZIP 保留於 `.runtime/creation_library`，不提交模型或原始範本至 Git。

| 選項 | 適用模式 | 判斷依據 |
| --- | --- | --- |
| TheseAlpacas V2 | Qwen 文字生圖／圖片編輯 | Qwen metadata 與 4096 維 transformer 張量 |
| Qwen 姿態 V3 | Qwen 文字生圖／圖片編輯 | 基底 metadata 指向 Qwen-Image-2.1 |
| Qwen Image Edit V3 | Qwen 圖片編輯 | Qwen 張量；編輯用途依檔名推定 |
| Qwen 服裝替換 | Qwen 圖片編輯 | Qwen metadata；編輯用途依檔名推定 |
| Qwen 全身構圖 | Qwen 文字生圖／圖片編輯 | Qwen metadata 與 transformer 張量 |
| Qwen 人物細節 V1.3 | Qwen 文字生圖／圖片編輯 | 既有 Qwen LoRA 與 transformer 張量 |

架構吻合並不等於已驗證成圖品質。這次以模型檔頭及本機 ComfyUI loader 對照適配，未執行 GPU 成圖。姿態與 Edit V3 的 `lora_A/B.default.weight` 及拆分 gate/proj 由本機既有 ComfyUI Qwen 2.1 loader 支援；不額外改寫權重。

CHROMA 目錄中的 Female_Figure.safetensors、scg-anatomy-female-v2.safetensors、undressing_flux_v3.safetensors 不啟用：前後兩者 metadata 明確為 FLUX.1-dev，中間一個無基底 metadata 且為 FLUX 類型張量。不能只因存放位置、部分共享結構或檔名就視為已確認 Chroma 適配。

**兩個 Chroma 原始工作流目前僅收錄與列出依賴，尚未接成可執行選項。** chromaHDSimpleWorkflowMulti_v30.zip 使用 Velvet Chroma GGUF、FLAN-T5、FaceDetailer／SAM／YOLO、Ultimate SD Upscale 等；Full V1 包含 Hyper Flash LoRA、ControlNet／OpenPose、遮罩、多階段放大，以及作者本機圖片與資料夾路徑。不可用現有 Chroma1-HD 文字生圖替代後仍宣稱完整支援原始範本。右側欄會明確標示「待補齊依賴與整合」。

### 行為與 API

預設「不使用 LoRA」。移除舊版依提示詞關鍵字自動套用 Edit LoRA／T2I 固定 LoRA 的規則，使用者可明確選擇一個 LoRA，強度 0～2。快速生成與多圖參考不接受這批 ComfyUI LoRA；不會隱性堆疊。

新增唯讀且需登入的 `GET /api/creation-library`。任務提交新增 `lora`（清單 ID）與 `lora_strength`；主機驗證 ID、工作流、圖片需求、強度與已安裝檔案，佇列記錄並傳遞選擇。桌面共用任務顯示 LoRA 名稱與強度。既有任務保留，新增欄位預設無 LoRA；網頁維持原本工作流介面，以無 LoRA 提交。

桌面要求工作室 API 版本 3。更新後若舊服務仍在運行，在「手機連線」安全停止並重新開啟服務。無新增 `.env` 參數。

本次驗證包含 27 項 Python 測試、桌面右側欄與 LoRA 提交／圖片需求／生成期間鎖定測試、原有手機與共用工作室 UI 回歸，以及 Rust 檢查。無畫面瀏覽器涵蓋 1280／768／390／360 寬度；截圖保存在 `.runtime/creation-desktop.png` 和 `.runtime/creation-mobile.png`。

開源參考：[ComfyUI 原生 LoRA loader](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/lora.py)、[Qwen 官方工作流文件](https://github.com/Comfy-Org/docs/blob/main/tutorials/image/qwen/qwen-image.mdx)。沿用本機 ComfyUI 與既有 Qwen runner，不另外引入自訂載入器。

## 0.3.6 Chroma 範本整合

右側「創作設定」提供兩個獨立工作流，範本卡片可直接套用。依賴尚未就緒時停用選項，展開卡片可查看缺少的模型／節點；安裝完成後按「重新檢查」。兩個範本都使用既有 GPU 鎖、登入驗證與共用任務佇列，不會另外啟動平行 GPU worker。

| 工作流 | 輸入 | 已整合的生成流程 | 最終輸出 |
| --- | --- | --- | --- |
| chromaHDSimpleWorkflowMulti_v30.zip · 修復放大 | 純文字 | Velvet Chroma v2 FP16，896 × 1152、Euler／sigmoid_offset、10 steps、CFG 4 → YOLO／SAM FaceDetailer → Nomos Web Photo Ultimate SD 2 倍分塊放大 | 1792 × 2304，一張 |
| comfyuiChroma1HdFull_v10.zip · 完整生成 | 1 張姿態參考圖；可加入第 2 張色彩參考圖 | OpenPose／Union ControlNet + Hyper Flash 四步 Heun → 色彩匹配／曲線 → 1024 細節修復 → 2048 分塊擴圖 → 3072 分塊擴圖 → 最終雙放大模型處理 | 約 4669 × 4669，一張 |

Full V1 將原作者的階段間本機讀檔改成直接圖片連線；參考圖以服務正規化的上傳檔案替換，不存取作者的 Mac 路徑。使用現有 Chroma1-HD／T5 的 FP8 權重以適配本機 12 GB 顯卡，保留 Hyper Flash、ControlNet、原始取樣及放大參數。HaDeS 使用真正的 Velvet Chroma 權重，不以 stock Chroma 替代。

匯出的是原範本主生成管線。原編輯畫布中的互動遮罩分支、資料夾批次讀取、Florence2 獨立圖片描述工具、預覽比較器及群組開關未連入這兩個工作流。空的 Power LoRA Loader、SageAttention 效能包裝、easy get/set 與 reroute 轉為原生接線；HaDeS 原本的空白 16 通道 latent 改用等效的 EmptySD3LatentImage。Full V1 的色彩匹配與曲線仍保留。放大與人臉修復使用分塊 VAE，沒有為通過測試降低原始輸出尺寸或步數。

### 可重現安裝

```powershell
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\install_chroma_templates.py nodes
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\install_chroma_templates.py models
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\install_chroma_templates.py velvet --file "完整的 Velvet Chroma v2 FP16 下載檔路徑"
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\install_chroma_templates.py verify
```

`config/chroma_dependencies.json` 保存節點 Git commit、公開模型來源、大小與 SHA256。節點安裝於 `.runtime/chroma/nodes`，ComfyUI 以額外搜尋路徑載入；模型放在既有模型目錄。安裝固定現有 torch／torchvision／numpy／transformers／tokenizers／huggingface-hub 版本，不升降既有 GPU 核心套件。OpenPose 使用已預下載並驗證的權重，不需在首次生成下載。依賴資訊沒有新增 `.env` 參數。

Velvet Chroma v2 FP16 的已知 SHA256 為 `9d8e243d9980bf78850ceb4dd66e1961b69785d50e1c653c80b4d22bf7d2517a`。匯入工具保留來源檔，只接受符合此雜湊的原版權重，不覆寫內容不同的既有模型。標準匯入名稱為 `D:\AI\ComfyUI-Models\diffusion_models\velvetChroma_v20FP16.safetensors`。

新增節點後，需在目前任務完成且 ComfyUI 佇列空閒時重新啟動 ComfyUI，再執行 `verify`。範本生成前也會重新驗證實際 `/object_info` 中的類別、必要輸入、模型選項與 scheduler。API 增加 `chroma_hades`／`chroma_full` 工作流 ID，版本為 4；舊工作室服務需安全停止後重新開啟。新增選項不能套用 Qwen／未確認的 FLUX LoRA。

### 驗證

32 項 Python 測試涵蓋主管線接線、原配方、參考圖數量、依賴就緒狀態、單次最終結果與共用 runner。桌面 UI 測試驗證卡片／模式選擇、姿態與色彩角色、缺少模型時停用、生成期間鎖定及 1280／768／390／360 寬度；既有手機與工作室 UI 回歸通過。

真實 GPU 驗證指令：

```powershell
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\test_chroma_templates_gpu.py chroma_full
.runtime\mobile-venv\Scripts\python.exe -X utf8 tools\test_chroma_templates_gpu.py chroma_hades
```

測試使用中性成年人物提示詞，從桌面 Python 橋接提交至實際主機 API，檢查一張最終 PNG、預期尺寸、非空白內容、移除生成 metadata 與登入後下載的位元組一致。結果保存於 `.runtime/chroma/*_validation.json`；`passed: true` 才代表該範本已完成真實生成驗證，單純安裝或 UI 測試不代表 GPU 驗收完成。

本機 RTX 5070（12 GB）已完成 Full V1 真實驗證：4669 × 4669、40,957,361 bytes、約 894.6 秒；登入後下載與桌面檔案完全一致，並已檢視成圖。0.3.6 時 HaDeS 仍待使用者下載模型；0.3.7 改接使用者實際下載的 FP16 原版。

Full V1 最終成圖約 2180 萬像素。生成結果解碼允許此已知尺寸；外部上傳仍在解碼前明確限制 2000 萬像素與 12 MiB，沒有放寬上傳限制。


## 0.3.7 Velvet FP16 原版

使用者下載的 `velvetChroma_v20FP16.safetensors`（17,800,057,328 bytes）已核對原版 SHA256 並複製到共用模型目錄，保留下載原檔。HaDeS 改用 ComfyUI 原生 `UNETLoader`、`weight_dtype=default` 與原生動態顯存載入，不將 FP16 改名當成 GGUF，也不替換為其他模型。取樣、人臉修復與 2 倍放大的原始參數保持一致。手動匯入模型的大小及雜湊集中於 `config/chroma_dependencies.json`。

修正 GetImageSize+ 轉換後的寬／高輸出索引，並在提交前核對節點連線型別；避免圖片輸出誤接到整數尺寸欄位。新增相關回歸測試。


HaDeS 已在 RTX 5070（12 GB）完成原版 FP16 真實生成驗證：1792 × 2304、一張最終 PNG，約 340.8 秒。YOLO 成功偵測一張臉，FaceDetailer／SAM 修復與四分塊放大全部執行完成；登入後下載與桌面檔案完全一致。33 項後端測試、桌面／手機／工作室 UI 回歸及 Rust 檢查通過。兩個 Chroma 範本目前均已就緒，GPU 驗收報告見 `.runtime/chroma/chroma_hades_validation.json` 與 `.runtime/chroma/chroma_full_validation.json`。
