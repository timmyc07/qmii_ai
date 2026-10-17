# 模型

千迷AI使用 `D:\AI\Qwen-Image-2.1-Turbo` 與 `D:\AI\QwenImage21SuperDuper`；模型不搬入 repository、不提交 Git，也不打包進 EXE。

Wan 2.2 TI2V-5B 僅用於 [本機基準比較](BENCHMARKS.md)，由 `tools/install_wan.py` 下載並校驗官方 5B FP16、UMT5 FP8 與 Wan 2.2 VAE；不加入日常 UI 或改變 H3 的影音／首尾幀用途。

必要檔案：

- `sd-cli.exe`
- `models\Qwen-Image-2.1-Turbo-AD-Q4_K.gguf`
- `models\Qwen-Image-2.1-Turbo-Abliterated-Uncensored-AD-Q4_K.gguf`
- `models\qwen_image_2.1_vae_bf16.safetensors`
- 圖片修改與多圖參考另需 `models\mmproj-Qwen-Image-2.1-Turbo-Abliterated-Uncensored-BF16.gguf`

SuperDuper 使用官方最新版 ComfyUI Portable、Impact Pack、Impact Subpack、工作流指定的 Qwen 2.1 模型與偵測模型，以及使用者提供的 `pussyV2.safetensors`、`qwen2.1_penisV01_000004956.safetensors`。執行 `tools\install-superduper.ps1` 可安裝或補齊；基礎 INT8 模型使用固定版本的 Hugging Face 鏡像，SHA256 為 `30532b445eabd4b84b108168b6b3fe720535ef400f6bf9d68bd551817d3531a3`，不需要 token。工作流原本引用但未提供的 `NSFW Qwen by TheseAlpacas V2.safetensors` 不會自動加入。第三方模型權利仍以來源條款為準。

NSFW Adv 群組共用同一套 ComfyUI，但使用獨立的 Qwen Image FP8、Qwen 2.5 VL text encoder、Qwen Image VAE、`qwen-image_nsfw_adv_v1.0.safetensors`、Lightning 8-step V2 與 RES4LYF。預設依作者建議為 10 steps、CFG 1、LoKr 1.0、Lightning 0.45、`res_2s` + `bong_tangent`。

安裝器保留局部細修 LoRA 原檔，另產生 `_comfy.safetensors` 版本；將合併的 `gate_up` LoRA 投影等價拆為 `gate_layer`／`proj`，供 ComfyUI 完整載入。可使用 portable Python 執行 `tools\test_qwen_lora.py` 驗證拆分前後的投影等價性。

精準模式的生成規範整理自使用者模板，由程式直接附加，不再依賴 PE T2I／I2I text encoder 或本機模板檔。已下載的 PE 模型保留在本機，但程式不再載入，也不再自動下載。模型、LoRA、LoKr 與 ComfyUI runtime 只保存在 `D:\AI\QwenImage21SuperDuper`，不提交 Git。

## H3 RefMod

RefMod 只支援 H3，沿用現有 FL2VA、Qwen3-VL 編碼器、影音 VAE 與所選 Turbo LoRA；不新增大型模型。Qwen 圖片模式不相容，介面標示停用。

```powershell
.runtime\mobile-venv\Scripts\python.exe -m tools.install_refmod
```

安裝器將 [ComfyUI-MiniMaxH3Mod](https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod) 固定在 `517e8c419a8584fbf69fceb487bc39d83e6a6ec8`，先驗證 ZIP SHA256 `53c2b89eac307d7d22d27803df150f6a6e429234ecf36f4a29c3fe04cbdbb523` 才解壓縮至 Portable 的 `custom_nodes`。已有不同版本會拒絕覆寫；同版重跑不重裝。使用 Portable 既有的 torch、safetensors、numpy、Pillow，不執行 pip 或下載額外權重。

安裝後須等 ComfyUI 佇列空閒，並確保沒有千迷AI GPU 工作，再重新啟動該 Portable 服務。本機已完成安裝與載入。若未安裝或尚未重新載入，啟用開關會明確回報缺少套件／節點。

可使用 Portable Python 執行 `tools\test_refmod_runtime.py`，在 CPU 上驗證三種配方與三種尾幀圖，以及參考注入保留原生首尾幀條件；不載入生成權重。效果與限制見 [H3 說明](H3.md)。
