# 發行流程

1. 執行 Python、桌面與手機 UI 測試，以及 `cargo check --manifest-path src-tauri\Cargo.toml`。
2. 執行 `tools\build.ps1`。
3. 確認 `dist\千迷AI.exe`、版本化 EXE 與 `dist\SHA256SUMS.txt` 存在。
4. 提交並推送原始碼；需要公開發行時再建立 tag 與 GitHub Release。

`dist`、模型、runtime、日誌與生成圖片不提交 Git。目前 portable EXE 依賴本機 Turbo 與 SuperDuper 執行環境。

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
