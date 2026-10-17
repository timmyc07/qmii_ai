# 會員與點數

0.18.0 的桌面及手機共用會員中心、會員管理與伺服器端計點。同一 MongoDB 資料庫內的帳號、餘額、消費紀錄及費率跨電腦共用；生成佇列、檔案及工作階段留在各主機。

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
- API 先保存本機待扣點任務，再以 MongoDB 交易原子檢查餘額、預扣點數、寫入流水及預扣憑據。確認成功才允許 GPU 執行；餘額不足回傳 HTTP 402，不啟動生成。會員管理員使用會員帳號生成也正常計點。
- 結束時依已發布的輸出結算。失敗、取消、部分完成或服務重啟，未完成部分退點；已完成作品保留並計費。尚在排隊的任務重啟後繼續處理。
- 已預扣任務保留提交時費率；後台變更價格不影響進行中任務。同一會員的相同 `request_id` 重試沿用原任務，內容不同回傳 409；另一台電腦不能接手或退還原電腦的預扣。管理加扣點亦需唯一 `request_id`，重試不能改金額或原因。
- 每筆扣點與退點都有唯一流水鍵，與餘額在同一 MongoDB 交易提交。同帳號的併發交易先鎖定該錢包並在衝突後重試，避免超扣。結算後不可更改完成數量，重試不會重複退點。
- 如果雲端已入帳但回應中斷，本機保留原請求與結算狀態。桌面、手機在原內容重試時沿用請求編號；工作程序重啟後也會確認原預扣。離線退點先保存待結算紀錄，恢復連線後自動重試，介面顯示待結算狀態。
- 停用帳號會撤銷全部工作階段，尚未開始的任務取消並退點；已開始的任務繼續結算。扣點不允許負餘額。

既有「私人連線碼」代表主機擁有者，仍可管理本機資料及使用免點數的私人 API，但不能管理共用會員、加扣點或費率；這些操作要求有效的會員管理員登入。這是受信任的主機管理憑證，不能發給一般會員。桌面的正式生成入口要求會員登入。一般會員只能讀取自己的本機任務、來源與作品，會員名稱取自帳號，不能用自填設備名稱冒充其他會員。管理員可檢視全體本機任務與作品。

## 帳號安全與復原

scrypt 採 N=32768、r=8、p=3，依照 [OWASP 密碼儲存指南](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt) 的記憶體／CPU 取捨設定，不新增密碼套件。

密碼使用帶隨機 salt 的 scrypt 雜湊，不儲存原文。瀏覽器使用 HttpOnly、SameSite=Strict cookie；公開 HTTPS 連線另設 Secure。修改資料仍需 Origin 與 CSRF 驗證。會員驗證操作有每來源 IP 的五分鐘操作限制；目前為單服務程序計數。

修改密碼需要原密碼，會登出所有設備。忘記密碼時，管理員先自行驗證會員身分，再產生 30 分鐘內單次有效的重設碼並私下交付；伺服器僅保存重設碼雜湊。沒有設定郵件服務，因此不會自動寄信。會員角色或狀態變更也會撤銷登入。

桌面登入 cookie 保存於 `.runtime/mobile/desktop-session.cookies`，密碼不落盤；此檔及同目錄的主機連線碼都必須以作業系統帳號權限保護。帳號、點數流水、稽核紀錄及所有 `.runtime` 狀態皆不得提交 Git。帳號採停用方式保留點數與稽核紀錄，不提供刪除流水功能。

## MongoDB 與本機資料邊界

MongoDB 的 `members` 保存會員 ID、電子郵件、名稱、scrypt 密碼雜湊、角色、啟用狀態、加入／更新／最近登入時間、工作階段版本及單次密碼重設碼雜湊。電子郵件有唯一索引；`account_state` 的交易鎖避免首次管理員重複建立及併發移除最後一位管理員。改密碼、角色或停用時增加帳號版本，每次會員 API 都向 MongoDB 檢查版本，其他主機也會拒絕舊登入。

升級舊帳號前會建立 `.runtime/mobile/members-before-mongodb.sqlite3` 備份，保留會員 ID 與密碼雜湊。升級舊點數前另建 `points-before-mongodb.sqlite3`，以原流水鍵移轉歷史、餘額差額及尚未結算的任務。每個會員的移轉使用 MongoDB 交易；全部成功才移除本機帳號／錢包／流水表。重試不覆寫既有帳號或雲端餘額，也不會重複匯入同筆歷史；信箱衝突或資料庫不可用時保留本機資料。切換前安全停止舊服務，不可讓新舊版本同時操作同一份本機資料，也不可再以舊版服務操作已移轉的錢包。

`point_wallets` 保存雲端餘額；`point_ledger` 保存不可覆寫的帳務流水；`point_requests` 保存預扣、來源主機與結算憑據；`membership_settings` 保存共用費率及註冊開關。MongoDB 必須支援多文件交易（Atlas 副本集）。SQLite 的 `jobs` 保存可重試的扣點／結算意圖，`host_identity` 綁定原電腦；`sessions`、`uploads` 與帳號操作稽核留在本機。會員登入任一主機，都讀取同一份餘額與消費流水；作品與生成歷史仍在原主機。

新登入、生成與會員操作在 Atlas 斷線時回傳 503，排隊任務等待連線恢復，已開始的任務可完成並留下待結算紀錄。請保留原主機 `.runtime/mobile`，勿將執行中的資料目錄複製給另一台電腦，也不要刪除尚未結算的任務。新電腦使用自己的本機狀態並連接相同 MongoDB 即可。原主機永久遺失時，預扣不會按時間自動退還，需以備份復原原主機後結算，避免仍在執行的任務被錯誤退款。

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

`mobile/accounts.py` 的 `MongoAccounts` 負責帳號；`mobile/points.py` 的 `MongoPoints` 負責帳務交易；`mobile/server.py` 的 `Store` 保存任務意圖並補結算。不在 GPU 生成期間持有資料庫交易，也不假裝 MongoDB 和 SQLite 能共用交易。

目前要求各生成主機受信任，持有 MongoDB 寫入憑證的主機仍可直接修改雲端帳務，因此不是防竄改的商用授權。正式收費前須將資料庫憑證與帳務 API 收斂到受控服務，不能把 `.env` 發給一般會員。外部資料庫連線資訊與郵件／支付密鑰才放服務端必要 `.env`，費率等選項維持在後台。

未接自動支付、發票、郵件驗證、自動郵件找回、MFA 或跨主機作品同步。

## 驗證

```powershell
.runtime\mobile-venv\Scripts\python.exe -m pip install -r mobile\tests\requirements.txt
.runtime\mobile-venv\Scripts\python.exe -m unittest discover -s mobile\tests -v
.runtime\mobile-venv\Scripts\python.exe -m tools.test_accounts_mongo
.runtime\mobile-venv\Scripts\python.exe -m tools.test_points_mongo
node tools\test_membership_ui.cjs
node tools\test-mobile-ui.cjs
node tools\test-studio-ui.cjs
node tools\test_conversation_ui.cjs
cargo test --manifest-path src-tauri\Cargo.toml
powershell -ExecutionPolicy Bypass -File tools\test-mobile-session.ps1
powershell -ExecutionPolicy Bypass -File tools\build.ps1
```

UI 測試需 Playwright 與 Edge；一般 Python／UI 測試注入 mongomock，不讀取真實 Atlas，也不需要 GPU。mongomock 不模擬交易回滾；回滾與跨獨立用戶端併發由需明確執行的 Atlas 整合測試驗證，使用唯一 `qianmi_ai_test_*`／`qianmi_points_test_*` 資料庫，結束後只移除該測試資料庫，不改動正式帳號。

計點實作參考 [credit_management](https://github.com/Meenapintu/credit_management) 的資料庫邊界與預扣／結算模式；帳號串接使用 [MongoDB 官方 PyMongo](https://github.com/mongodb/mongo-python-driver) 及其[交易 API](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/)，未加入 ORM 或另一套登入框架。
