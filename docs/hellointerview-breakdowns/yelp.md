# Yelp
> ⚠️ Premium 文章，原文僅公開需求與大綱；設計細節為整理者補充。

> 來源：https://www.hellointerview.com/learn/system-design/problem-breakdowns/yelp ｜ 難度：easy ｜ 類別：Scaling Reads ｜ 作者 Evan King

## 一句話核心
（原文）本地商家搜尋與評論平台；讀多寫少，重點在 geo 搜尋、評分聚合的預先計算，以及評論的唯一性約束。

## 需求（Functional / Non-functional / 規模數字）
**Functional（原文）**
- 依名稱、位置（lat/long）、分類搜尋商家
- 查看商家（含其評論）
- 對商家留評論（必填 1-5 星、可選文字）
- Out of scope：Admin 增刪改商家、地圖檢視、個人化推薦

**Non-functional（原文）**
- 搜尋低延遲（< 500ms）
- 高可用，eventual consistency 可接受
- 擴展至 100M DAU、10M 商家
- Out of scope：GDPR、fault tolerance、防垃圾/濫用

## Core Entities & API
（原文僅有標題，以下為補充，非原文）
- Entities：Business、User、Review(business_id, user_id, rating, text)
- API：
  - `GET /businesses?query=&lat=&long=&category=&page=`
  - `GET /businesses/{id}`（含分頁 reviews）
  - `POST /businesses/{id}/reviews {rating, text}`

## High-Level Design
（原文僅有標題；補充，非原文）
1. 搜尋：Client -> Gateway -> Search Service -> Search 索引（先以 DB 為底，再進階 Elasticsearch）。
2. 檢視商家：Business Service -> DB（Business 表 + Review 表），加 cache。
3. 留評論：Review Service -> DB 寫入，並更新商家平均評分（見 Deep Dive 1）。
架構上讀寫分離：讀量遠大於寫量。

## Deep Dives（依原文大綱逐條）
### 1) 如何有效計算並更新平均評分，使其能直接顯示在搜尋結果？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：每次搜尋/檢視時 `AVG(rating)` 掃 review 表，搜尋結果每頁 N 家就 N 次聚合，太慢。
- 好解：在 Business 上存 `avg_rating` 與 `review_count`，寫評論時同一 transaction 更新：`new_avg = (avg*n + r)/(n+1)`。
- 最佳解：評論是低頻寫入，增量更新即可；高寫入熱門商家可改非同步（寫入 queue，worker 批次更新），並把 avg_rating 同步進搜尋索引（近即時 reindex）。更新評論/刪除時用 delta 修正。
- 取捨：同步更新簡單且正確但在熱商家產生 row contention；非同步最終一致，符合本題 eventual consistency 的要求。

### 2) 如何確保一位用戶對一家商家只能留一則評論？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：應用層先查再寫（check-then-insert），有 race condition，雙擊就重複。
- 好解：DB 層 `UNIQUE(user_id, business_id)` 約束，違反時回 409。
- 最佳解：加 unique constraint 並讓 API 為 upsert/PUT 語意（再次提交視為修改），評分聚合依舊值差更新；分片時以 business_id 或 user_id 做 shard key 使唯一性檢查落在單一分片內。
- 取捨：unique index 在分片 DB 要 shard key 對齊，否則需分散式唯一性檢查。

### 3) 如何改善複雜查詢的搜尋效率？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：在 SQL 用 `WHERE name LIKE '%x%'` 加 lat/long 範圍比較，全表掃描、無法用索引。
- 好解：對 lat/long 建 geospatial 索引（PostGIS、geohash、quadtree），對 category 建索引。
- 最佳解：獨立搜尋引擎（Elasticsearch/OpenSearch）：全文（名稱）+ geo_distance + category filter + 依評分排序，經 CDC 從主 DB 同步；10M 商家資料量小，單索引多 shard 即可。
- 取捨：多一套系統與同步延遲（eventual consistency 可接受）；換得複合條件查詢的效能與相關性排序。

### 4) 如何支援以城市/社區等預定義地名搜尋？（原文題目）
（補充，非原文 — 原文為 Premium）
- 爛解：把地名字串當全文關鍵字比對，會把「Springfield」的所有州混在一起。
- 好解：維護 Location 表（city/neighborhood -> bounding box 或 polygon），查詢時先解析成地理範圍再做 geo filter。
- 最佳解：Gazetteer/geocoding 步驟：autocomplete 將輸入對應到標準化 location_id（含 polygon），搜尋引擎用 geo_shape 或預先在商家文件寫入 city/neighborhood 欄位做 term filter（索引時一次性標註）。
- 取捨：預標註查詢最快但邊界變動需重建；polygon 查詢彈性高但較貴。

## 關鍵數字與 back-of-envelope
- 100M DAU，假設每人 5 次搜尋 -> 5 億/天 ≈ 5.8k QPS 平均，峰值 ×3 約 17k QPS。
- 10M 商家 × ~1KB ≈ 10GB，完全可放記憶體/單一搜尋叢集；評論量大但可冷熱分離。
- 讀寫比極高（例如 100:1），強力支持 cache + 預計算。

## 可遷移的 pattern（3-5 條）
1. 衍生欄位預先計算（denormalize avg_rating/count），讀路徑 O(1)。
2. 唯一性靠 DB unique constraint，而非 check-then-insert。
3. Geo 搜尋用 geohash/quadtree/搜尋引擎 geo index。
4. 主 DB + 搜尋索引 via CDC，讀寫分離與最終一致。
5. 名稱到地理範圍的解析（geocoding）獨立成前置步驟。

## 常見追問（3-5 題，附簡短答案）
- 熱門商家評論寫入競爭？非同步聚合 + 批次更新，或 sharded counter。
- 評論列表如何分頁？keyset pagination（依 created_at + id），避免 offset。
- 如何防垃圾評論？rate limit、需有購買/到訪驗證、ML 偵測（原文列為 out of scope）。
- 搜尋結果如何排序？距離、評分、相關性加權（score function），可離線訓練。
- 圖片/照片怎麼存？物件儲存 + CDN，DB 只存 URL。
