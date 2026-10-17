# 會員與點數

0.17.0 的桌面及手機共用會員中心、會員管理與伺服器端計點。帳號與使用者資訊以 MongoDB Atlas 為準；本機 SQLite 保留生成佇列、點數交易及工作階段。

主機的專案根目錄 `.env` 只需要 `MONGODB_URI`。URI 已包含驗證資料，無需重複存放 username／password；費率與註冊開關仍由管理後台設定。URI 未指定資料庫時使用專案專屬 `qianmi_ai`。`.env` 已由 Git 忽略，不能提供給一般會員或打包進 EXE。

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

## MongoDB 與本機資料邊界

MongoDB 的 `members` 保存會員 ID、電子郵件、名稱、scrypt 密碼雜湊、角色、啟用狀態、加入／更新／最近登入時間、工作階段版本及單次密碼重設碼雜湊。電子郵件有唯一索引；`account_state` 的交易鎖避免首次管理員重複建立及併發移除最後一位管理員。改密碼、角色或停用時增加帳號版本，每次會員 API 都向 MongoDB 檢查版本，其他主機也會拒絕舊登入。

首次升級會先建立 `.runtime/mobile/members-before-mongodb.sqlite3` 備份，再將舊 `members` 帳號移至 Atlas，保留 ID 與密碼雜湊。確認雲端交易成功後，餘額移至本機 `member_wallets`，再移除舊 SQLite 帳號表。重試不覆寫既有雲端帳號；若信箱衝突或資料庫不可用，升級會停止並保留舊帳號表。切換前先安全停止舊服務，不能讓新舊版本同時操作同一份本機資料。

本機 `member_wallets`、`point_ledger` 與 `jobs` 仍共用 SQLite 交易，保持預扣及退點原子性。`sessions`、`uploads`、費率、註冊開關與稽核也留在本機；跨主機帳號可登入，但點數和歷史仍依各主機保存，不能當作跨主機共用錢包。退點不依賴 MongoDB 即時可用；新登入、生成與會員操作在 Atlas 斷線時回傳 503，排隊任務等待連線恢復，不回退到舊帳號儲存。

連線使用官方 PyMongo、TLS 與憑證驗證；服務只記錄例外類型，API 不回傳 URI、密碼或資料庫錯誤原文。URI 由主機環境變數或專案 `.env` 載入，不執行檔案中的 shell 指令。

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

`mobile/accounts.py` 的 `MongoAccounts` 是帳號資料存取邊界；`mobile/membership.py` 的 `Members` 負責會員 API 與本機錢包整合，`reserve()` 及 `settle()` 參與任務交易。若後續將點數集中到雲端，必須連同生成任務建立／結算一起設計，不能把扣點與任務建立拆成兩個獨立寫入。

目前是受信任單機主機的功能驗證版本。本機擁有者可以修改資料檔、程式與模型，因此此版本無法作為防竄改的商用授權或真實付費點數權威。正式收費前，須把權威帳務、管理憑證、登入限流與備份移到受控服務；會員 EXE 不應持有主機連線碼。外部資料庫連線資訊與郵件／支付密鑰才放服務端必要 `.env`，費率等選項維持在後台。

未接自動支付、發票、郵件驗證、自動郵件找回、MFA 或跨主機點數同步。

## 驗證

```powershell
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
.runtime\mobile-venv\Scripts\python.exe -m tools.test_accounts_mongo
node tools\test_membership_ui.cjs
node tools\test-mobile-ui.cjs
node tools\test-studio-ui.cjs
node tools\test_conversation_ui.cjs
cargo test --manifest-path src-tauri\Cargo.toml
powershell -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

UI 測試需 Playwright 與 Edge；一般 Python／UI 測試明確注入記憶體帳號，不讀取真實 Atlas，也不需要 GPU。`tools.test_accounts_mongo` 是需明確執行的 Atlas 整合測試，使用唯一 `qianmi_ai_test_*` 資料庫，結束後只移除該測試資料庫，不改動正式帳號。

計點實作參考 [credit_management](https://github.com/Meenapintu/credit_management) 的資料庫邊界與預扣／結算模式；帳號串接使用 [MongoDB 官方 PyMongo](https://github.com/mongodb/mongo-python-driver) 及其[交易 API](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/)，未加入 ORM 或另一套登入框架。
