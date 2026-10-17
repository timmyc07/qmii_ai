# 會員與點數

0.16.0 的桌面及手機共用會員中心、會員管理與伺服器端計點。外部資料庫尚未串接；開發與單機驗證暫時沿用 `.runtime/mobile/mobile.sqlite3`，不需要新增 `.env`。

## 第一次使用

1. 開啟桌面側欄「會員登入」，展開「第一次使用：建立管理員」。填寫名稱、電子郵件與至少 10 個字元的密碼。
2. 使用剛建立的管理員帳號登入，點「會員管理」。第一位管理員只能從主機桌面建立，公開註冊不會取得管理員權限。
3. 會員可從桌面或手機「註冊會員」自行註冊；新帳號為 0 點，管理員按姓名／電子郵件搜尋後，在「管理帳號」手動加點，填寫原因或儲值單號。
4. 管理員可調整每張圖片／每部影片點數、開關註冊、變更角色、停用或恢復會員。系統禁止移除最後一位有效管理員。

## 計費規則

- 預設照片一張 3 點、影片一部 10 點。費率在會員管理後台調整。
- 一般圖片批次按張數計算；沒有來源圖片時產出一張。多圖融合 `reference` 的所有參考圖片只產出一張，收取 3 點。
- H3 每張首幀各產出一部影片，每部 10 點，共用尾幀不計費；SVI 三段合成的一部影片收取 10 點。
- API 在同一交易內檢查餘額、預扣點數並建立任務，餘額不足回傳 HTTP 402，不啟動生成。會員管理員使用會員帳號生成也正常計點。
- 結束時依已發布的輸出結算。失敗、取消、部分完成或服務重啟，未完成部分退點；已完成作品保留並計費。尚在排隊的任務重啟後繼續處理。
- 已預扣任務保留提交時費率；後台變更價格不影響進行中任務。相同任務 `request_id` 不會重複排隊或扣點，管理加扣點亦需唯一 `request_id`。
- 停用帳號會撤銷全部工作階段，尚未開始的任務取消並退點；已開始的任務繼續結算。扣點不允許負餘額。

既有「私人連線碼」代表主機擁有者，仍可管理全機資料及使用免點數的私人 API；這是受信任的主機管理憑證，不能發給一般會員。桌面的正式生成入口要求會員登入，不會自動使用主機憑證生成。一般會員只能讀取自己的任務、來源與作品，會員名稱取自帳號，不能用自填設備名稱冒充其他會員。管理員可檢視全體任務與作品。

## 帳號安全與復原

scrypt 採 N=32768、r=8、p=3，依照 [OWASP 密碼儲存指南](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt) 的記憶體／CPU 取捨設定，不新增密碼套件。

密碼使用帶隨機 salt 的 scrypt 雜湊，不儲存原文。瀏覽器使用 HttpOnly、SameSite=Strict cookie；公開 HTTPS 連線另設 Secure。修改資料仍需 Origin 與 CSRF 驗證。會員驗證操作有每來源 IP 的五分鐘操作限制；目前為單服務程序計數。

修改密碼需要原密碼，會登出所有設備。忘記密碼時，管理員先自行驗證會員身分，再產生 30 分鐘內單次有效的重設碼並私下交付；伺服器僅保存重設碼雜湊。沒有設定郵件服務，因此不會自動寄信。會員角色或狀態變更也會撤銷登入。

桌面登入 cookie 保存於 `.runtime/mobile/desktop-session.cookies`，密碼不落盤；此檔及同目錄的主機連線碼都必須以作業系統帳號權限保護。帳號、點數流水、稽核紀錄及所有 `.runtime` 狀態皆不得提交 Git。帳號採停用方式保留點數與稽核紀錄，不提供刪除流水功能。

## 後續資料庫串接接口

網路接口仍使用現有 8787 port，不另開資料庫埠。桌面透過 `membership` Tauri 指令與 `mobile.desktop.membership_action()` 固定路由表呼叫同一組 API：

| 接口 | 用途 |
| --- | --- |
| `GET /api/membership` | 是否完成初始化、公開費率與註冊狀態 |
| `POST /api/membership/bootstrap` | 主機驗證後一次性建立管理員 |
| `POST /api/membership/register`、`login`、`reset` | 註冊、登入、單次碼重設密碼 |
| `GET /api/membership/me`、`ledger?offset=0` | 目前會員、餘額、每頁 50 筆點數明細 |
| `POST /api/membership/password`、`POST /api/logout` | 改密碼、登出 |
| `GET /api/admin/members?search=&offset=0` | 每頁 100 筆會員搜尋 |
| `PUT /api/admin/members/{id}` | 角色與啟用狀態 |
| `POST /api/admin/members/{id}/credits`、`reset` | 加扣點、產生重設碼 |
| `GET /api/admin/audit?offset=0` | 帳號操作與點數流水，各 100 筆 |
| `PUT /api/admin/membership` | 費率與註冊開關 |

`mobile/membership.py` 的 `Members` 是目前會員／點數資料存取邊界，由 `Store.connect()` 注入連線；`reserve()` 及 `settle()` 參與任務交易。未來取得資料庫資訊後，需一併將會員、sessions、uploads、jobs、流水與設定搬到服務端交易；不能只替換餘額查詢而把扣點與任務建立拆開。

目前是受信任單機主機的功能驗證版本。本機擁有者可以修改資料檔、程式與模型，因此此版本無法作為防竄改的商用授權或真實付費點數權威。正式收費前，須把權威帳務、管理憑證、登入限流與備份移到受控服務；會員 EXE 不應持有主機連線碼。外部資料庫連線資訊與郵件／支付密鑰才放服務端必要 `.env`，費率等選項維持在後台。

未接自動支付、發票、郵件驗證、自動郵件找回、MFA、跨主機會員同步；待服務端、資料庫與供應商資訊確定後串接。

## 驗證

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
node tools\test_membership_ui.cjs
node tools\test-mobile-ui.cjs
node tools\test-studio-ui.cjs
node tools\test_conversation_ui.cjs
cargo test --manifest-path src-tauri\Cargo.toml
powershell -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

UI 測試需 Playwright 與 Edge；會員測試使用隔離資料與模擬生成，不需要 GPU。會員端到端測試也不會改動主機帳號。

實作前檢視 [credit_management](https://github.com/Meenapintu/credit_management) 的資料庫邊界與預扣／結算模式；本專案重用現有 FastAPI、SQLite 交易與工作階段，未加入新依賴。
