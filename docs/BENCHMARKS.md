# 本機生成基準

基準以實際工作流逐次生成，沿用桌面／手機的 GPU 檔案鎖。測試期間工作室任務會等待；ComfyUI 若已有其他未受此鎖管理的任務，基準會拒絕提交。輸出、版本盤點、原始日誌、工作流、節點時間與記憶體樣本都保存在 `output/benchmarks/`，不提交 Git。

## 執行

使用既有 ComfyUI Portable Python；量測所需的 `aiohttp`、`psutil`、`av` 已由 ComfyUI 安裝，不加入手機服務依賴。從專案根目錄執行：

```powershell
$benchmarkPython = 'D:\AI\QwenImage21SuperDuper\ComfyUI_windows_portable\python_embeded\python.exe'
# 只盤點，不使用 GPU 生成。
& $benchmarkPython -s -X utf8 tools\benchmark_generation.py
# 全部案例；預留足夠時間，H3 原版尤其較慢。
& $benchmarkPython -s -X utf8 tools\benchmark_generation.py --run --output output\benchmarks\local
# 在同一目錄選跑案例，來源沿用先前生成的 quick/0.png。
& $benchmarkPython -s -X utf8 tools\benchmark_generation.py --run --case h3_turbo4 --case h3_turbo8 --output output\benchmarks\local
```

固定案例在 `docs/benchmark_cases.json`。`quick` 生成首幀，`quick_edit` 生成綠衣尾幀；參考與影片案例需要這兩個來源先存在於同一輸出目錄。影片共同規格為 896×512、141 幀、24 fps、5.875 秒、seed 42，符合 H3 的 `17k+5` 與 Wan 的 `4k+1` 幀數規則。這是相同負載的比較規格；不能視為 H3 Turbo4 768p 配方在原生解析度的品質驗證。

每個案例產生 `case.json`、`result.json`、`samples.json`；ComfyUI 額外產生 `graph.json`、`history.json`，Qwen CLI 產生 `qwen.log`。影片完整解碼驗證並另存首／中／尾截圖。根目錄的 `comparison.md`、`results.json` 每個案例完成後更新；失敗不會抹除前面結果，程序以非零代碼退出。

每次執行另存帶時間戳的 `inventory_*.json`，各結果記錄對應檔名，避免選跑案例時覆蓋舊盤點。版本盤點包含 PyTorch、CUDA、Qwen commit、ComfyUI 工作階段資訊、模型／LoRA 檔名與大小、工作流及節點原始碼 SHA256。模型檔不逐一計算數十 GB 的 hash；Wan 安裝器會驗證下載的完整 SHA256。

## Wan 實驗路徑

先執行：

```powershell
.runtime\mobile-venv\Scripts\python.exe -X utf8 -m tools.install_wan
```

下載約 18.1 GB 官方 TI2V-5B、UMT5 FP8 與 Wan 2.2 VAE 至既有 ComfyUI 模型目錄；固定 Hugging Face revision 並驗證 SHA256，既有模型校驗失敗時拒絕覆寫。未安裝額外節點、LoRA 或 attention 套件。

`wan_text`／`wan_image` 沿用 [Comfy-Org 官方工作流](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_wan2_2_5B_ti2v.json)：UniPC、Simple、20 步、CFG 5、shift 8。僅輸出無聲 MP4，不支援 H3 尾幀或原生影音。此路徑只供基準評估；速度、品質與日常需要確認前不新增模式卡片或更改預設路由。

## 讀取量測

- VRAM、RAM 是約每秒取樣的整機占用，含 Windows 桌面與其他程序；不能當成模型獨占或瞬時最高值。
- 節點耗時由 ComfyUI WebSocket 執行事件量測。loader 節點耗時記錄於 `loader_node_seconds`，但原生延遲載入也發生於文字編碼、採樣與解碼；`sampler_node_seconds` 包含其內部模型載入，不能與純採樣時間混用。
- Qwen 的載入、採樣、解碼時間採用 CLI 本身日誌，另外保留端到端耗時，不重複加總巢狀時間。ComfyUI 在案例開始前啟動；`comfy_inventory_*.json` 另記服務準備時間，案例總時間不包含這次啟動。
- `cached_nodes`／`cached_sampling` 明確記錄執行快取。採樣命中快取的速度不算有效比較；需要重測時先在 ComfyUI 釋放模型和執行快取，再重跑。
- 成功代表可解碼輸出。身分、動態、音訊、接縫與嘴形必須另檢視，不能把成功率當作畫質分數。

## 記憶體與切換

保留原有 `--lowvram` 與 ComfyUI 原生 offload／RAM pressure cache。未設定 `--reserve-vram`、`--cache-none`、固定 pagefile 或雙模型常駐。

快速生成在持有 GPU 鎖期間檢查 ComfyUI 佇列；仍有工作或無法確認服務狀態時拒絕啟動 CLI。閒置時透過原生 `/free` 卸載模型、清除執行快取，等待 PyTorch 使用中顯存回落後再啟動 Qwen。此檢查不是整機顯存保證，也不能協調其他應用程式自行提交的 GPU 工作。

## 選配與 UI 差距

現有桌面已具備 H3 配方、首幀／自選尾幀、主體描述、聲音開關、參數保存與任務紀錄；API 回歸涵蓋尾幀數量與參數傳遞。0.15.0 起手機也可提交 H3 批次影片、調整參數、選擇尾幀，影片可由共用作品庫播放與下載。

本輪不新增 SageAttention、VAE 分塊、RIFE、放大、導演助手、逐幀臉部修復或自動尾幀。這些項目須分別有解碼 OOM、可重現效益或明確表單缺口的證據，並依原計畫在獨立環境／樣本比較；無效益的選配維持關閉。
