# Wan 2.2 與生成參數

桌面與手機共用任務佇列、GPU 鎖、作品庫與參數預設。在「創作設定」選擇影片模式，輸入提示詞後生成 MP4。

## 影片模式

- **Wan 2.2 5B**：使用主機既有 5B、UMT5 與 Wan 2.2 VAE。無圖片時文字生成影片；上傳 1 張圖片時作為起始畫面。預設 640 × 384、49 幀、24 FPS、20 步、CFG 5。
- **Wan 2.2 雙模型範本**：需要 1 張起始圖。移植下載的 `wan22NSFWI2VWorkflowOrSFW_v10.zip` 核心流程：CLIP Vision、圖片縮放、WanImageToVideo、高／低噪聲雙階段採樣、解碼與影片輸出。以下載的 Q8 高噪聲模型取代範本原本的 Q4 高噪聲模型，搭配原配方 Q4 低噪聲模型。預設 480 × 832、113 幀、16 FPS、6 步、CFG 1、shift 8；步數平均分配兩階段。

雙模型模式輸出原生 FPS 的 H.264 MP4，沒有移植 FILM 補幀、播放音效、最後一幀輸出或已停用節點。這是以已下載模型改編的範本，並非原作者完整流程的等效重現。

兩個下載的 LoRA 僅提供給 14B 模式，套用於高噪聲階段，可選強度 0～2。已檢查權重維度為 Wan 14B 的 5120，不應套到 5B。風格效果需依提示詞調整。

## 安裝

```powershell
powershell -ExecutionPolicy Bypass -File tools\import-wan.ps1
.runtime\mobile-venv\Scripts\python.exe tools\install_wan.py
```

匯入腳本複製下載的高噪聲 GGUF、兩個 LoRA 與範本壓縮檔，並比對 SHA-256。安裝腳本補齊低噪聲 GGUF、Wan 2.1 VAE 與 CLIP Vision H，依 Hugging Face LFS 大小與 SHA-256 校驗；`.part` 可續傳，既有不同檔案不覆蓋。

模型位於 `D:\AI\ComfyUI-Models`，透過 `config/windows_extra_model_paths.yaml` 與既有 ComfyUI-GGUF 節點讀取。新增路徑後需在空閒時重啟 ComfyUI。「重新檢查」會列出缺少的模型、節點與尚未載入的模型名稱。模型、影片與執行狀態不納入 Git。

## 生成參數

桌面「創作設定 → 生成參數」留白沿用配方，按「儲存為此模式預設」後所有設備共用。手機在設定側欄調整，再按「儲存共用設定」。不需要新增 `.env` 值；Qwen 文字生圖與圖片編輯分開儲存預設。

| 模式 | 可調參數 |
| --- | --- |
| 快速生成、多圖參考 | 步數、CFG、種子 |
| Qwen 文字生圖 | 步數、CFG、種子、寬高、負面提示詞 |
| Qwen 圖片編輯 | 步數、CFG、種子、denoise、負面提示詞、LoRA 強度 |
| FLUX | 步數、Guidance、種子、寬高、LoRA 強度 |
| Chroma 基礎 | 步數、CFG、種子、寬高、負面提示詞 |
| Chroma 人臉修復範本 | 基礎步數／CFG、種子、修復步數／CFG／denoise、遮罩膨脹、合成羽化、噪聲遮罩羽化 |
| Chroma 完整範本 | 種子；其餘多階段配方固定 |
| Wan 影片 | 步數、CFG、種子、寬高、幀數、FPS、負面提示詞；14B 模式可選 LoRA 強度 |

膨脹與羽化作用於 Chroma 人臉修復的自動遮罩。Qwen 一般圖片編輯沒有局部遮罩輸入，因此不提供這兩個選項。截圖中的 denoise 0.45～0.50、CFG 2.5～2.9、步數 8～12、LoRA 0.30 可在 Qwen 圖片編輯模式直接輸入；該組設定不代表適合所有模型。

每次提交固定並保存當次參數，修改預設不影響已排隊任務。固定種子可重現設定，批次圖片使用種子依序加一。影片幀數需為 4n+1，最多 121 幀；寬高以 32 為單位，最多 832，總像素不超過 832 × 480。

## 參考來源

- [ComfyUI 官方 Wan 節點](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_wan.py)
- [ComfyUI 官方工作流範本](https://github.com/Comfy-Org/workflow_templates)
- [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF)
- [QuantStack 低噪聲 GGUF](https://huggingface.co/QuantStack/Wan2.2-I2V-A14B-GGUF)
- [Comfy-Org Wan 2.1 VAE 與 CLIP Vision](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged)
