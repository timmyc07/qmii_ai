# 手機工作室驗證

發行前執行：

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
node tools\test-mobile-ui.cjs
node tools\test-studio-ui.cjs
powershell -NoProfile -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1
```

真實 GPU 驗證只在 Qwen Image 2.1 Turbo 模型齊全時執行 `tools\mobile-smoke.py`。快速生成需產生有效 PNG；多圖參考需提交至少兩張圖片。下載端點在未登入的 session 必須回覆 401。
