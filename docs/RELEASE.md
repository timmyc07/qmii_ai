# 發行流程

1. 執行 Python、桌面與手機 UI 測試，以及 `cargo check --manifest-path src-tauri\Cargo.toml`。
2. 執行 `tools\build.ps1`。
3. 確認 `dist\千迷AI.exe`、版本化 EXE 與 `dist\SHA256SUMS.txt` 存在。
4. 提交並推送原始碼；需要公開發行時再建立 tag 與 GitHub Release。

`dist`、模型、runtime、日誌與生成圖片不提交 Git。目前 portable EXE 依賴本機 Turbo 與 SuperDuper 執行環境。

## 0.5.5

- 桌面比對背景服務程式碼指紋，安全排空並更新舊服務，避免新版程式仍使用舊工作流。
- SuperDuper 失敗訊息顯示節點名稱，不包含提示詞或上游錯誤內文。

## 0.5.4

- 修正 SuperDuper 偵測到臉部後，RGBA 圖片送入 SAM 導致三通道斷言失敗；每段細修前轉為 RGB。

## 0.5.3

- 所有模式可上傳圖片加提示詞；SuperDuper 與 NSFW Adv 新增逐張圖片編輯／重繪。
- NSFW Adv 新增重繪強度，桌面與手機同步支援。

## 0.5.2

- SuperDuper 安裝改用固定版本、SHA256 相同的 Hugging Face 基礎模型鏡像，不再需要 Civitai token。
- 安裝時將局部細修 LoRA 的合併 MLP 投影等價拆分，避免 ComfyUI 忽略部分權重；保留原始檔案。

## 0.5.1

- 修正桌面設定仍送出已移除的 `fixedPrompt`，導致儲存失敗。
- SuperDuper 恢復工作流原有的 `qwen2.1_penisV01_000004956.safetensors` 局部細修 LoRA。

## 0.5.0

- 新增指定的 ComfyUI SuperDuper 工作流與 `pussyV2` LoRA。
- 新增 NSFW Adv LoKr 作者建議群組與可切換的精準模式。
- 桌面與手機可調整尺寸、步數、CFG、種子、負面提示詞及 LoRA 強度。
- 新增最新版 ComfyUI Portable 與必要模型的一鍵安裝／驗證腳本。

## 0.4.2

- 右側欄完整列出 Turbo 可調參數，並說明作用與調高／調低的影響。
- 新增輸出寬高與負面提示詞，桌面、手機與主機設定同步驗證。

## 0.4.1

- 移除 ComfyUI、Chroma、FLUX、Wan、Qwen Pose 工作流與全部 LoRA 整合。
- 只保留 Qwen Image 2.1 Turbo 的快速生成、逐張修改與多圖參考。
