# 這套 SVI 工作流的 LoRA 相容指南

截圖中的兩個 `Power Lora Loader (rgthree)` 是額外疊加入口：`LoRA Loader HIGH` 接高噪模型，`LoRA Loader LOW` 接低噪模型。可加入多個 LoRA，但空白也能執行；它們與必要的 SVI Pro／Lightning LoRA 是不同用途。千迷AI 新頁面目前載入固定的必要配方，額外入口仍在原 ComfyUI 工作流，沒有自動載入本機所有 LoRA。

本流程的基礎是 [Wan 2.2 I2V A14B](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B)，具有高噪與低噪兩個專家模型。挑選時需核對模型家族、14B／A14B、I2V、適用噪聲支線，以及作者要求的步數／觸發詞；只有 `.safetensors` 副檔名不能代表相容。

| LoRA 類型或標示 | 如何搭配 |
| --- | --- |
| Wan 2.2 I2V A14B 成對 HIGH／LOW | 優先選擇；HIGH 放 HIGH，LOW 放 LOW，同系列同版本配對。 |
| Wan 2.2 I2V A14B、只訓練 HIGH 或 LOW | 只放指定支線；另一邊留空，保留既有 SVI／Lightning。 |
| Wan 2.2 I2V A14B 通用單檔 | 依作者明確指示選單支線或兩邊；不能只憑「Wan 2.2」就當成通用。 |
| 角色、畫風、鏡頭／動作 LoRA | 可以是額外疊加的用途，但仍須符合上述基礎模型與支線條件。三段使用同一套，觸發詞按作者要求放進三段提示詞。 |
| Wan 2.1 14B 或 Wan 2.2 T2V A14B | 部分張量可能可載入，但不等於此 I2V／SVI 配方有效；只在作者明確驗證相容時試用。 |
| Wan 1.3B、Wan 2.2 TI2V-5B、Qwen Image、MiniMax H3、SD／SDXL、FLUX | 架構或尺寸不同，不適用這套 A14B I2V 工作流。 |
| 其他加速／蒸餾 LoRA | 不能當一般風格 LoRA隨意疊加。已使用 LightX2V，新增其他加速器需重新核對採樣步數、CFG、shift 與高低噪切換。 |

## 作者清單中的檔案

| 檔案 | 用途與位置 |
| --- | --- |
| `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH/LOW_lora_rank_128_fp16.safetensors` | 既有續接配方，各接對應支線；保留。來源：[Kijai SVI v2.0](https://huggingface.co/Kijai/WanVideo_comfy/tree/main/LoRAs/Stable-Video-Infinity/v2.0)。 |
| `wan2.2_i2v_A14b_high/low_noise_lora_rank64_lightx2v_4step_1022.safetensors` | 既有加速配方，各接對應支線；不用再在額外入口重複加一次。來源：[LightX2V 模型卡](https://huggingface.co/lightx2v/Wan2.2-Distill-Loras)。 |
| `NSFW-22-H-e8.safetensors`／`NSFW-22-L-e8.safetensors` | 依你提供的作者清單，H 對 HIGH、L 對 LOW，作為額外配對；仍須核對下載版本的 I2V 適用範圍與權重說明。 |
| `livewallpaper_wan22_14b_i2v_low_model_0_1_e26.safetensors` | 依你提供的作者檔名與清單，是 LOW 支線的額外風格 LoRA，HIGH 留空。不能為了湊對而複製到 HIGH。 |

以上兩個 Civitai 頁面本次無法讀取，因此後兩列只依你提供的原作者清單整理，未確認目前網站的新版檔案、觸發詞或建議權重。下載時應重新核對版本頁。

## 最少試法

先用不加額外 LoRA 的影片作基準。每次只加入一組，優先採作者建議權重；作者未說明時，可從 0.3～0.5 作保守試驗，再比較角色、動作與三段接縫。這是試驗起點，不能保證任何 LoRA 的效果。

三段應保持同組 LoRA 與權重，角色觸發詞、服裝及風格描述也保持一致。I2V 已有首幀作條件，過強的風格／角色權重可能改變首幀外觀或壓縮動作幅度；SVI 並不保證長片段完全不漂移。

Q8 是主模型的量化格式，額外 LoRA 可保留 FP16／BF16，不需尋找「Q8 LoRA」；是否可用取決於架構及載入器。LightX2V 官方明確支援 LoRA 與量化結合。此工作流用 UMT5 編碼提示詞，額外效果主要加在 MODEL 支線；不要額外套用其他模型家族的 CLIP LoRA。

大量疊加仍增加記憶體、權重修補與載入成本。千迷AI 會在任務結束後釋放自己的生成程序，但不會因此降低同時載入多個 LoRA 的生成峰值需求。
