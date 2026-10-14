# 工作流

## 快速生成

使用 `D:\AI\Qwen-Image-2.1-Turbo` 的既有本機 runtime，適合一般文字生圖與快速修改。

## Qwen 2.1 工作流

本次整合範圍：

- Route ① T2I：文字生圖、預設 NSFW LoRA、50 steps、CFG 2.5、`er_sde` + `beta`。
- Route ② Edit：上傳圖片後修改、20 steps、CFG 3、`er_sde` + `beta`；符合指定關鍵詞時使用 edit LoRA。

圖片與修改提示詞一起送出時，前端只建立圖片縮圖訊息；同一份完整提示詞仍以 `prompt` 參數傳給 Rust 後端與模型。

未整合 Route ④ VNCCS 精確姿勢。它需要未包含在上游 repo 的 CDP `browser_client.py`，以及 VNCCS 節點、姿勢庫和額外 LoRA，因此不能以目前選單宣稱支援 136 姿勢。

上游來源固定為 `Arekejoker/qwen21-nsfw-pose-skill` commit `4ca900d`。由於上游未提供 LICENSE，產品 repo 不提交其檔案；本機安裝在 `.runtime`。
