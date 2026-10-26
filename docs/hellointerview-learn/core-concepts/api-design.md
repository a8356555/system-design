# API Design
> 來源：https://www.hellointerview.com/learn/system-design/core-concepts/api-design ｜ 分類：core-concepts

## 一句話重點
API 步驟只需約 5 分鐘：預設選 REST、用核心 entities 當 resources、講清楚 path/query/body 與 status code，然後把時間留給真正困難的架構；遇到付款/訂位等 POST 要主動提 idempotency key。

## 核心內容

### 前提
- 面試官多半不在乎 API 完美，只想看你能設計出合理 API 然後繼續往下走。
- 例外：面試前端/產品職，或 junior 職位，API 會被問得比較深。
- 實務上候選人「在 API 花太多時間」的錯誤比「投入太少」更常見，上限約 5 分鐘。

### API 類型（三選一）
| 協定 | 特性 | 何時選 |
|---|---|---|
| REST | 標準 HTTP method 操作以 URL 識別的 resource；對應 CRUD | **預設**。不確定就說「I'll use REST APIs」然後繼續（原文：適用 90% 情境） |
| GraphQL | 單一 endpoint + query language，client 指定要的欄位 | 面試官提到 flexible data fetching、over-fetching/under-fetching、多種 client 需求不同（mobile vs web）、前端要快速迭代 |
| RPC (gRPC/Thrift) | action 導向、binary serialization (protobuf) + HTTP/2 | 微服務內部、效能關鍵、多語言（polyglot）、需要 streaming |

- 即時功能（通知、聊天、live updates）用 WebSocket / SSE，這不是傳統 API，是持久連線，見 Real-time Updates Pattern。
- 典型組合：對外 REST，內部 service 間 gRPC。除非被問，API 步驟只列 user-facing API，內部 RPC 在 high-level design 提一句即可。

### REST
**Resource modeling**
- Resources = delivery framework 裡的 core entities。以 Ticketmaster 為例：`GET /events`、`GET /events/{id}`、`GET /venues/{id}`、`GET /events/{id}/tickets`、`POST /events/{id}/bookings`、`GET /bookings/{id}`。
- Resource 代表「系統裡存在的東西」而不是動作；一律用**複數名詞**。
- 關係表達兩種：巢狀（`/events/{id}/tickets`）或扁平 + query（`/tickets?event_id=123`）。
- 判準：關係「必要」→ path parameter / 巢狀；「可選 filter」→ query parameter。

**HTTP methods**
| Method | 用途 | Idempotent? |
|---|---|---|
| GET | 讀取，不改資料 | 是 |
| POST | 建立新 resource，server 指派 ID | 否（重複呼叫會建立多筆） |
| PUT | 整個取代（或不存在則建立） | 是 |
| PATCH | 部分更新 | 不保證：「set email to X」是；「append to list」不是 |
| DELETE | 刪除 | 是（狀態相同，回應碼可不同：204 → 404） |

- Idempotency 重要性：網路失敗時 client 會 retry，不能因 retry 造成重複 booking。

**傳遞資料**
- Path parameter：結構性，識別特定 resource（`/events/123`）。
- Query parameter：修飾/過濾/排序/分頁（`/events?city=NYC&date=...`、`?page=2&limit=20`），可選。
- Request body：實際 payload，複雜或敏感/過大的資料。
- 範例：`POST /events/123/bookings?notify=true` + body `{tickets:[...], payment_method}`。event ID 在 path（必要）、notify 在 query（可選行為）、訂單細節在 body。

**回傳資料**
- 由 status code + response body（通常 JSON）組成。
- 常用：200 成功、201 created、400 bad request、401 需認證、404 not found、500 server error。
- 重點是分辨 4xx（client 錯）與 5xx（server 錯），不用背全部；用 XXX 帶過也通常可接受。

### GraphQL
- 2012 起源 Facebook：mobile 與 web 需要不同資料，REST 要嘛 endpoint 暴增、要嘛 over-fetching。
- 一個 query 可穿越關係（event → venue + tickets），回傳形狀由 client 決定。
- 缺點/複雜度：需要 query parsing、schema validation、較複雜的 caching。
- Schema 設計：用 type 定義 entities 與關係（Event、Venue、Query）。
- **N+1 problem**：查 100 個 events 帶 venues → 101 次 DB query 而非 2 次；解法是 batching / dataloader。
- 授權在**欄位層級**（resolver），而不是整個 endpoint。
- 面試建議：看到明確的 over/under-fetching 問題才提，不要預設；先用簡單工具解核心架構問題。

### RPC
- 呼叫遠端 procedure 如同本地函式（`getEvent`, `createBooking`, `getAvailableTickets`）。
- gRPC = Protocol Buffers + HTTP/2；用 `.proto` 定義 service，自動產生多語言 client/server code，編譯期型別安全（Go ↔ Java 互通）。
- 適用：效能關鍵、型別安全、service-to-service、需 bidirectional streaming。

## API Design Principles（九條）
1. **Design around resources, not actions**：避免 `/getUserBookings`、`/processPayment`；改 `GET /users/{id}/bookings`、`POST /payments`。
2. **Be consistent everywhere**：命名/參數/response shape 一致（不要 `status` 與 `state` 混用）。
3. **Least surprise**：GET 不改資料、DELETE 刪除、200 就是成功（不要在 200 body 裡包 `success:false`）。
4. **Stateless**：每個 request 帶齊 auth token、參數、payload，任何 server 都能處理 → 水平擴展變成 LB 問題；JWT 流行的原因之一。
5. **Make retries safe**：GET/PUT/DELETE 天生 idempotent；重要的 POST（booking、payment）用 idempotency key。
6. **Paginate anything that can grow**：從第一天就分頁，並限制 page size 上限（防 `?limit=100000`）。
7. **Secure by default**：認證 opt-out 而非 opt-in；授權確認對「這個 resource」的權限；rate limiting 兜底。
8. **Evolve without breaking clients**：加欄位安全；改名/刪除/改語意是 breaking change，需要 versioning。舊 mobile app 會存活多年。
9. **Make errors actionable**：正確的 4xx/5xx + machine-readable code + human-readable message。

原文提醒：重點不是背誦原則，而是「說出口地應用」，例如「我在這個 endpoint 用 idempotency key，這樣 retry 不會重複訂位」。

## Common API Patterns
### Pagination
| | Offset-based | Cursor-based |
|---|---|---|
| 形式 | `?offset=20&limit=10` | `?cursor=<last id>&limit=10`，回應含 `next_cursor` |
| 優點 | 直覺、好實作、可跳頁 | 不受新資料插入影響（穩定） |
| 缺點 | 大資料集有問題；翻頁期間資料變動會重複/漏資料 | 難做「跳到第 5 頁」 |
- 面試：offset 通常夠用，除非即時資料或面試官問高流量；最重要是「記得放分頁」。

### Filtering and Sorting
- 慣例：`?city=NYC&status=upcoming`；排序 `?sort=date`，前綴減號為降序 `?sort=-date`。
- 設計重點在跨 endpoint 一致，不用列舉所有 filter；示範一個並說明慣例通用即可。

### Idempotency Keys
- 情境：訂票 request timeout，client retry，可能重複訂票/扣款。
- Client 為每個邏輯操作產生唯一 ID，放 `Idempotency-Key` header；server 把 key 與第一次結果一起存，retry 時直接回傳儲存的 response。Stripe 就是這樣處理付款 retry。
- 在 payments / bookings / orders 設計中提到是強烈加分訊號（展示你想的是失敗情境）。

### Consistent Error Responses
- 統一 envelope：`{"error": {"code": "SEAT_UNAVAILABLE", "message": "..."}}`。code 是穩定字串供程式判斷，message 給人看、可改。
- 面試中一句話帶過即可。

### Versioning
- URL versioning（`/v1/events`）：明確、易路由，面試首選。
- Header versioning（`Accept-Version: v2`）：URL 較乾淨、較符合 HTTP 標準，但不直觀、瀏覽器難測。
- 原文的 breakdowns 通常不寫 versioning，不代表實務不重要。

## Security Considerations
- Authentication（你是誰）vs Authorization（你能不能做這件事）。例：John 只能取消自己的 booking。
- 面試建議：標出哪些 endpoint 需要登入，說「用 JWT 或 DB 存 session」即可。

| | API Keys | JWT |
|---|---|---|
| 本質 | 長隨機字串，像應用程式的密碼；server 查 DB 識別 | 把 user id/權限/exp 編進 token 並簽章；驗簽即可，不需查 DB |
| 適用 | server-to-server、開放第三方開發者 | user-facing web/mobile session |
| 不適用 | 使用者產品（不會過期、無 user context） | — |
- JWT 適合分散式系統：任何有驗證金鑰的 service（如 API gateway）都能獨立驗證。
- **RBAC**：角色（customer / venue_manager / admin）→ 權限；檢查「已認證」且「已授權（擁有該 booking 或是 admin）」。面試最多提哪些 endpoint 屬於哪些角色。
- **Rate limiting**：per-user（如 1000/hr）、per-IP（如 100/hr 未認證）、endpoint-specific（如 10 booking/min 防黃牛）；通常在 API gateway 或 middleware；超限回 429。面試一句「implement rate limiting to prevent abuse」即可，除非被問不要設計演算法。

## 面試怎麼用
- 何時提：Delivery framework 的 API 步驟；別超過 5 分鐘。
- 怎麼說：「core entities 對應 REST resources，我會用 REST；內部 service 之間可用 gRPC。」列出 3-6 個 endpoint 即可。
- 加分：付款/訂位提 idempotency key；列表提分頁；提 4xx/5xx 區別；標出需 auth 的 endpoint。
- 陷阱：endpoint 用動詞（`/bookTicket`）；沒有分頁；一開始就選 GraphQL 又無明確 over-fetching 理由；花太多時間在 status code / versioning 細節；把 WebSocket/SSE 當成一般 API。

## 關鍵數字
原文無具體效能數字（僅範例：per-user 1000 req/hr、per-IP 100 req/hr、10 booking/min、REST 適用 90% 情境）。

## 相關題目
- [ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)（原文範例）
- [payment-system](../../hellointerview-breakdowns/payment-system.md)（idempotency key）
- [distributed-rate-limiter](../../hellointerview-breakdowns/distributed-rate-limiter.md)
- [bitly](../../hellointerview-breakdowns/bitly.md)

## 自測問題
1. REST 的 path parameter 與 query parameter 如何取捨？答：必要、識別 resource 用 path；可選的過濾/排序/分頁用 query。
2. 哪些 HTTP method 是 idempotent？為何重要？答：GET/PUT/DELETE；PATCH 視實作；POST 否。網路失敗 retry 時避免重複副作用。
3. 何時選 GraphQL？代價？答：多種 client 需不同資料、避免 over/under-fetching；代價是 parsing/schema/caching 複雜度與 N+1（用 dataloader 批次）。
4. Offset 與 cursor 分頁差異？答：offset 簡單可跳頁但資料變動會重複/漏；cursor 穩定但不能跳頁。
5. 如何防止 retry 造成重複扣款？答：client 產生 Idempotency-Key，server 儲存 key+結果，重複 key 回傳原結果。
