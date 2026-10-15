# 工作流

## 快速生成

使用 `D:\AI\Qwen-Image-2.1-Turbo` 的既有本機 runtime，適合一般文字生圖與快速修改。

## 多圖參考生成

選擇「多圖參考生成」並上傳 2～4 張圖片。模型會在同一次推理中參考全部圖片，再依照提示詞產生一張新的融合圖片；這和快速生成的「逐張修改」不同，不會為每張參考圖各自產生結果。

Turbo runtime 使用 Qwen vision encoder 與可重複的 `--ref-image` 參數傳入多張參考圖，並以 `--increase-ref-index` 將圖片依序標記為 `<image1>`、`<image2>` 等；提示詞會要求模型重新創作單一畫面，而不是直接拼貼參考圖。

## Qwen 2.1 工作流

本次整合範圍：

- Route ① T2I：文字生圖、預設 NSFW LoRA、50 steps、CFG 2.5、`er_sde` + `beta`。
- Route ② Edit：上傳圖片後修改、20 steps、CFG 3、`er_sde` + `beta`；符合指定關鍵詞時使用 edit LoRA。

圖片與修改提示詞一起送出時，前端只建立圖片縮圖訊息；同一份完整提示詞仍以 `prompt` 參數傳給 Rust 後端與模型。

未整合 Route ④ VNCCS 精確姿勢。它需要未包含在上游 repo 的 CDP `browser_client.py`，以及 VNCCS 節點、姿勢庫和額外 LoRA，因此不能以目前選單宣稱支援 136 姿勢。

上游來源固定為 `Arekejoker/qwen21-nsfw-pose-skill` commit `4ca900d`。由於上游未提供 LICENSE，產品 repo 不提交其檔案；本機安裝在 `.runtime`。

## Chroma1-HD 文字生圖

電腦與手機的工作流選單皆可選擇「Chroma1-HD 文字生圖」。輸入提示詞即可生成一張 1024 × 1024 圖片；此工作流不接受參考圖片。

執行 `powershell -ExecutionPolicy Bypass -File tools\install-chroma.ps1` 安裝至 `D:\AI\ComfyUI-Models`。安裝程式支援續傳，並在核對檔案大小與 SHA256 後才將檔案交給 ComfyUI：

- `diffusion_models/Chroma1-HD-fp8_scaled_defaultloader_hybrid_large_rev2.safetensors`
- `text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors`
- `vae/ae.safetensors`

沿用現有 ComfyUI、GPU 排隊鎖及共用作品集，無需新增環境變數或自訂節點。採用官方工作流的 Euler、26 步、CFG 3.8、Flow Shift 1、Beta 排程 alpha/beta 0.45；解析度調整為 1024，以配合本機 12 GB 顯示卡。首次使用需載入模型，速度會比快速生成慢。

來源：[模型下載頁](https://huggingface.co/silveroxides/Chroma1-HD-fp8-scaled)、[作者工作流](https://huggingface.co/lodestones/Chroma1-HD/blob/main/ComfyUI_Chroma1-HD_T2I-workflow.json)、[ComfyUI Chroma 範例](https://github.com/comfyanonymous/ComfyUI_examples/tree/master/chroma)。


## FLUX.1-dev 與三個人物 LoRA

0.3.8 新增「FLUX.1-dev」模式，支援 Female_Figure.safetensors、scg-anatomy-female-v2.safetensors、undressing_flux_v3.safetensors。每次可選一個 LoRA，強度 0～2；只接受文字提示詞，不接受參考圖片。這三個 LoRA 使用 FLUX 基底，與 Chroma、Qwen 模式分開。

下載 [Comfy-Org FLUX.1-dev FP8 整合模型](https://huggingface.co/Comfy-Org/flux1-dev/blob/main/flux1-dev-fp8.safetensors)，將模型放在 `C:\Users\Yumai\Downloads\Comfy UI & Lora\`，三個 LoRA 放在該目錄下的 `CHROMA` 子目錄，再執行 `powershell -ExecutionPolicy Bypass -File tools\install-flux.ps1`。安裝器校驗官方模型 SHA256 並核對每個複製檔案，安裝到 `D:\AI\ComfyUI-Models\checkpoints` 與 `loras`。

使用 ComfyUI 核心節點，不需要自訂擴充。模型搜尋路徑新增 checkpoints 後，需要在無生成工作時重新啟動 ComfyUI。既有工作室服務也需要安全停止並重新開啟，才會載入新版 API。

驗證：`python tools/test_flux_gpu.py` 使用同一種子生成基底與三個 LoRA 各一張 1024×1024 圖片，檢查圖片有效、與基底有差異，以及日誌沒有未載入的 LoRA 權重。此測試會使用 GPU，須先完成模型與 ComfyUI 安裝。
