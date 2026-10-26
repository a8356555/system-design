# Gopuff（Local Delivery Service）
> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/gopuff ｜ 難度：easy ｜ 類別：Scaling Reads（作者 Stefan Mai；頁面標題為 Local Delivery Service）

## 一句話核心
兩條路徑、兩種一致性：availability 是「讀多、可容忍短暫過期」，用 Nearby Service（半徑預篩 + travel time service）找 1 小時內的 DC，再靠 Redis 短 TTL cache + Postgres read replica + 依 zipcode 前 3 碼分區撐 20k QPS；order 要「強一致、不可重複賣」，把 orders 與 inventory 放在同一個 Postgres，用 SERIALIZABLE 單一 transaction 搞定，避開分散式 lock 的失敗模式。

## 需求
Gopuff 透過 500+ 個 micro distribution centers (DCs) 提供便利商店商品的快速配送。

**Functional（Core）**
- 客戶可依位置查詢「1 小時內可送達」商品的可用性（有效庫存 = 附近所有 DC 庫存的聯集）
- 客戶可一次訂購多個商品

**Out of scope**：付款/購買處理、司機路徑與配送、搜尋與 catalog API（系統只關心 availability 與 ordering）、取消與退貨

原文重點：強調跨本地 DC 聚合庫存與下單「不重複預訂（double booking）」；其他題目可能更在意 catalog 與 search。

**Non-functional（Core）**
- Availability 請求要快（< 100ms），以支援搜尋等情境
- 下單必須強一致：兩個客戶不能買到同一個實體商品
- 支援 10k DCs、跨 DC 共 100k 個 catalog items
- 訂單量約 O(10m orders/day)

**Out of scope**：隱私與資安、災難復原

## Core Entities & API
**Entities**
- **Item**：商品類型（如 Cheetos），客戶真正在意的
- **Inventory**：某個 DC 中的一個實體商品。原文類比 OOP 的 Class vs Instance：Item 是 class，Inventory 是 instance；加總 Inventory 得到某使用者可用的某 Item 數量
- **DistributionCenter**：實體位置，用來決定哪些商品對使用者可用
- **Order**：被使用者訂購的一組 Inventory（加上寄送/帳單資訊）

原文提醒：從最具體的實體（商品、使用者）往抽象實體（訂單、購物車）建立，才不會漏。

**API**（兩個）
1. 取得 availability：依位置（可能加關鍵字），含分頁，避免回傳過多資料
2. 下單
兩者都傳入位置：處理訂單前需確認附近有庫存足以 1 小時內送達。（原文以圖示呈現，未列具體 URL。）

## High-Level Design
```
Client -> Availability Service -> Nearby Service (DC 表 + Travel Time Service) -> DC ids
                              \-> Postgres read replica (Inventory join Items) -> 加總回傳
Client -> Orders Service -> Nearby Service -> Postgres leader (單一 transaction)
```
### 1) 查詢 availability
兩步驟：先找 1 小時內可到的 DCs（所有庫存都在 DC 裡，避免檢查全部商品），再查這些 DC 的 inventory 取聯集。端到端 < 100ms。
- **Nearby Service**：內部 API，輸入 lat/long 回傳可送達 DC。初版用 DC 表的 lat/long 與 Euclidean 或 Haversine（考慮地球曲率）距離設門檻，得到「直線距離」內的 DC；不完全滿足需求，deep dive 再改進。
- **Inventory 查詢**：Postgres 的 Inventory 與 Items 表 join 取名稱/描述與數量。實務上 catalog 與 inventory 常因消費者與負載不同而分開，並加 search index（如 Elasticsearch）；此處為簡化放同一 DB，可口頭告知面試官。
- 元件：Availability Service、Nearby Service（定期與 DC 資料庫同步，使用外部 Travel Time Service，可能含路況）、Inventory table（replicated SQL）。
- 流程：請求帶 lat/long 與過濾條件 → Availability Service 呼叫 Nearby Service → 回傳可送 DC → 用 DC IDs 查 DB → 加總回傳。

### 2) 下單
要求強一致：檢查庫存、記錄訂單、更新庫存必須原子完成。延遲可以比讀取寬鬆，但絕不能把同一庫存承諾給兩位使用者。核心是 **double booking** 防止，需要某種 lock。
- **Good：兩個 data store + distributed lock**。orders 與 inventory 分庫（例如 inventory 用 KV、orders 用關聯式 DB）；下單時鎖定相關 inventory、建立 order、扣庫存、釋放 lock。可為每種用途選最佳儲存，但失敗模式很麻煩：
  - service 在建立 order 後、扣庫存前掛掉 → 後續使用者可能買到已承諾的庫存，需要 sweep 並回滾；
  - 兩筆訂單庫存重疊會死結（User1 持有 A 的鎖、User2 持有 B 的鎖，兩人都想買 A+B）。
  選這條路必須能處理這些失敗模式。
- **Great：單一 Postgres transaction**。orders 與 inventory 放同一 DB，用 ACID，isolation level = SERIALIZABLE，整個 transaction 原子：兩人搶同一商品時，其中一個會被拒絕（庫存不足時 commit 失敗）。
  流程：使用者請求 Orders Service → 對 Postgres leader 送出單一 transaction：(a) 檢查 A/B/C 庫存 > 0；(b) 任一缺貨則失敗；(c) 都有貨則記錄訂單並將庫存項目狀態更新為 "ordered"；(d) 在 Orders（與 OrderItems）建立新 row；(e) commit。成功則回傳 order。
  缺點：inventory 與 orders 的擴展耦合，無法為各用途選最佳 store。但需要原子性時，把資料放在同一 ACID store 較好；跨多 store 的 transaction 雖可行，複雜度與開銷不是面試重點。
  取捨：任一商品變為缺貨則整筆訂單失敗，需給有意義的錯誤訊息；但比成功建立一筆不合理的訂單（例如裝置買到了、電池沒有）好。

### 整合
三個服務：Availability、Orders、共享的 Nearby DCs service（前兩者都用它找足夠近的 DC）。單一 Postgres 存 inventory 與 orders，按 region 分區；Availability 讀 read replica，Orders 寫 leader 並用 atomic transaction 避免 double write。

## Deep Dives

### 1) 讓 availability 考慮路況與行車時間
問題：隔著河或國界的 DC 英里近但行車遠；路況也影響；需求是 1 小時行車時間。
- **Bad：簡單 SQL 距離**（Euclidean / Haversine + 門檻）。不考慮路況與道路條件，也無法處理同城市多個 DC。
- **Bad：對全部 DC 呼叫 Travel Time Estimation Service**。DC 很少變動（是建築物），可每 ~5 分鐘從 DC 表同步到 service 記憶體，再逐一呼叫外部服務。問題：查詢次數太多，大多數 DC 根本不可能 1 小時內到達。
- **Great：先用半徑預篩再呼叫 Travel Time Service**。同樣定期同步 DC 到記憶體；請求進來先用固定半徑（例如 60 英里，最樂觀 1 小時內能開的距離）篩出候選 DC，再只對候選呼叫外部 travel time service 得出最終估計。

### 2) 讓 availability 又快又可擴展
先用數字確認瓶頸（原文：有量化估算能幫助與面試官共享取捨基礎）。由 10m orders/day 反推：每位使用者買 1 件前約看 10 頁（搜尋、首頁等），且只有 5% 的使用者最終購買。
`Queries = 10M / 100k s × 10 / 0.05 = 20k queries/second`

- **Great：Redis cache 查詢庫存**。service 先查 cache，miss 再查 DB 並回寫；低 TTL（如 1 分鐘）保持新鮮。挑戰：cache 必須與 inventory 表同步，Order Service 寫 inventory 時要讓受影響的 cache entry 失效。
- **Great：Postgres read replicas + 分區**。因為只讀附近一批 DC，可用 zipcode 前 3 碼當 region ID 將 DC 分組，並按 region 分區 inventory，讓查詢多半只打 1-2 個 partition。availability 可容忍小幅不一致 → read replicas；orders 需強一致 → 打 leader。挑戰：replica 規模需配合流量調整；分區要避免單一 replica 過載。

兩項 Great 解合併即最終設計。

## 關鍵數字與 back-of-envelope
- 500+ micro DCs（描述）；NFR：10k DCs、100k items
- 10M orders/day；`100k s/day` 簡化；每次購買約看 10 頁；5% 轉換率
- Availability 約 20k QPS（10M/100k × 10 / 0.05）
- Latency：availability < 100ms；cache TTL 例 1 分鐘；DC 同步週期例 5 分鐘
- 預篩半徑例：60 英里（最樂觀 1 小時）
- Region ID：zipcode 前 3 碼

## 面試官期待
- **Mid-level**（80/20）：清楚定義 API 與資料模型，建立 availability 與 orders 兩條路徑；使用 Bad 解時，期待有好的討論，不要求立刻跳到 Good/Great。基礎會被追問（如用 DynamoDB 會問可用的 index）。
- **Senior**（60/40）：快速完成 HLD；對讀取量、顯而易見的分區（trivial partitioning）要有合理解；需要優化 orders service 的原子 transaction 與 availability service 的擴展。
- **Staff+**（40/60）：深入 2-3 個關鍵領域，展現創新與最佳解；對遞進難度的追問要有獨到見解；以面試官是否學到新觀點衡量。

## 可遷移的 pattern
1. **Item vs Inventory（Class vs Instance）建模**：區分 catalog 概念與實體庫存，適用票務、訂房、座位類題目。
2. **Double-booking → 同一 ACID store 的單一 SERIALIZABLE transaction**：共置資料取代分散式 lock，避開 crash 中間狀態與死結。
3. **空間預篩 + 昂貴精算**：先用廉價半徑過濾，再呼叫外部 travel-time 服務（適用附近搜尋、派車、地理圍欄）。
4. **讀寫分離的一致性分級**：reads 走 replica + 短 TTL cache（可過期），writes 走 leader（強一致），寫入時 invalidate cache。
5. **用資料局部性分區**：以 zipcode 前綴等 region key 分區，讓查詢多半只命中 1-2 個 partition；並用 back-of-envelope（反推 QPS）佐證瓶頸。

## 常見追問
- **為什麼不用 distributed lock？** 需處理 crash 後的半完成狀態與重疊商品造成的死結；單一 Postgres transaction 更簡單。
- **訂單中一件缺貨怎麼辦？** 整筆失敗並回傳明確錯誤，避免不合理的部分訂單（如裝置缺電池）。
- **Cache 過期造成超賣嗎？** 不會，下單一律在 leader 以 transaction 檢查庫存；cache 只用於 availability 顯示，且 Order Service 寫入時使 cache 失效。
- **為何 60 英里？** 它是 1 小時內最樂觀可達距離的保守上界，用來預篩候選 DC。
- **Postgres 擴展？** 依 region（zipcode 前 3 碼）分區 + read replicas；寫入集中在 leader（原文提醒需管理 replica 規模與分區均衡）。
