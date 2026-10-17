# 高耗能圖片轉影片模式

在頂部分頁選擇「高耗能圖片轉影片模式」，上傳一張首幀，依序填寫「第一段・起始動作」、「第二段・承接動作」與「第三段・收尾畫面」。每段最多 2,500 字；應描述同一主體的連續動作。右側可載入範例或設定種子，底部負面提示詞三段共用，留白沿用作者的負面詞。草稿與附件在切換頁面時保留。

右側 HIGH／LOW 可各選一個本機 `.safetensors` LoRA，分別調整 -2～2 的權重；預設 0.5、0 為停用。額外 LoRA 疊加於必要的 SVI／Lightning 後，不會替換它們；三段共用同一組選擇。「儲存為高耗能模式預設」會保存 LoRA、權重、種子與負面詞，首幀仍需重新上傳。

送出後對話只保留首幀縮圖，三段提示詞輸入框清空；完整三段提示詞、負面詞及 LoRA／權重仍保存在共用任務詳情。

沿用 `wan22SVI.json` 的 Wan 2.2 I2V A14B Q8、SVI v2 Pro、LightX2V 4-step 雙模型配方：480×720 置中裁切、Euler 共 8 步（高／低噪各 4 步）、CFG 1、shift 6。每段 81 幀，第二、三段承接前段 latent；各融合 5 幀，最後 233 幀、16 fps，約 14.56 秒。輸出 H.264 無聲 MP4，不含原工作流停用的插幀、放大及編譯節點。

影片保存在 `output/年-月-日/<任務編號>_0.mp4`，與其他平台同日成品放在一起，可於對話、共用任務及手機作品庫播放與下載；三段提示詞保存在任務詳情。此版由桌面新頁面送出，手機作品庫可查看結果。

原工作流 HIGH／LOW 額外 LoRA 插槽的適用類型、配對方式及作者清單對照，見 [LoRA 相容指南](SVI_LORAS.md)。新頁面也附有簡短選擇說明。

## 資源清理

每項任務啟動自己的 Portable ComfyUI（本機 8192），使用 `--lowvram --cache-none`。成功時先複製影片到作品目錄，顯示「正在釋放模型與快取」，呼叫 `/free` 並終止、等待專屬程序退出後，才回報完成並釋放共用 GPU 鎖。失敗、取消及啟動錯誤也走相同清理；正常終止逾時會強制結束，仍無法確認退出時停止佇列，避免繼續堆積模型。

開始前會釋放千迷AI 共用 ComfyUI（8191）的閒置模型與快取，並檢查 Comfy Desktop（8188）的佇列；Desktop 正在生成時拒絕啟動。這只管理千迷AI 的專屬生成程序，其他軟體已載入的模型仍由該軟體管理。系統檔案待命快取與其他程式的 RAM 不等於本模式持續運算。

## 安裝

需要現有的 `D:\AI\QwenImage21SuperDuper\ComfyUI_windows_portable`。在 repository 根目錄執行：

```powershell
.runtime\mobile-venv\Scripts\python.exe -X utf8 -m tools.install_svi
```

安裝器固定 [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) 與 [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) 的 commit 和 ZIP SHA256，拒絕覆寫其他版本。僅補齊 GGUF、color-matcher 與 mss 依賴，沿用現有 PyTorch。模型從 `D:\AI\ComfyUI-Models` 硬連結至 Portable，已有模型不覆寫，不重複下載大型權重。

高噪 Lightning 原檔有 41 個 `.diff_m` 調制權重鍵，原生 LoRA loader 會忽略。安裝器依 [WanVideoWrapper 的映射](https://github.com/kijai/ComfyUI-WanVideoWrapper/blob/main/nodes_model_loading.py) 產生 `_comfy.safetensors` 副本，改為 `.modulation.diff`，張量內容不變；不修改原檔或 ComfyUI 核心。

| 目錄 | 模型 |
| --- | --- |
| diffusion_models | `wan2.2_i2v_high_noise_14B_Q8_0.gguf`、`wan2.2_i2v_low_noise_14B_Q8_0.gguf` |
| loras | `SVI_v2_PRO_Wan2.2-I2V-A14B_HIGH_lora_rank_128_fp16.safetensors`、`SVI_v2_PRO_Wan2.2-I2V-A14B_LOW_lora_rank_128_fp16.safetensors` |
| loras | `wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step_1022.safetensors`、`wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step_1022.safetensors` |
| vae | `wan_2.1_vae.safetensors` |
| text_encoders | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |

執行日誌位於 `.runtime/svi_comfy.log`。Q8 雙模型仍需大量 RAM、顯存與載入時間；清理功能針對任務結束後的保留佔用，不降低生成期間的模型需求。所有模型、生成檔案與執行環境不包含在 EXE 或 Git。
