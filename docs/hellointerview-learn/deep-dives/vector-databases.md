# Vector Databases
> 來源：https://www.hellointerview.com/learn/system-design/deep-dives/vector-databases ｜ 分類：deep-dives

## 一句話重點
Vector DB 的核心是 ANN（approximate nearest neighbor）索引，在 recall / latency / memory 三者間取捨；HNSW 是 production 預設答案。實務建議「先從簡單開始」：pgvector / ES kNN 等擴充先上，超過約 1 億向量才考慮專用 vector DB；vector DB 是 index，不是 source of truth。

## 它是什麼 / 核心機制

### Vector / Embedding
- 向量 = 代表某物（字、句子、圖片、user、商品）的一組數字，相似的東西向量相似。典型 128-1536 維（OpenAI text-embedding-3-large 為 3072）；各維度人類通常不可解讀，重要的是幾何關係反映語意關係。
- 「相似」取決於 embedding model：通用預訓練模型（OpenAI embedding API、Sentence Transformers、BERT；圖像用 CLIP、ResNet）把它當成昂貴的 GPU function；也可用自訂 ML 模型定義精確相似（例：尿布與奶瓶因「新手父母常一起買」而相似）。

### 相似度指標
- Euclidean (L2)：直線距離，在意方向與大小。
- Cosine：向量夾角，忽略大小（1 同向、0 垂直、-1 反向）；embedding 通常已 normalize。
- Dot product：未對大小 normalize，稍快。
- Hamming：二元向量不同位數（XOR + 計數），LSH 常用。
- 面試（infra 型）通常不重要，說「用 cosine 或適當的相似度」即可領先多數人；ML 型面試才可能深入。

### KNN → ANN
- 精確 KNN：與所有向量比較、排序取 top K，O(n)。100 萬筆 × 1536 維 ≈ 60 億次浮點運算/query。可用 SIMD（CPU 一次 2-8 個）或 GPU 加速，但多數應用可容忍些許誤差換取大速度。
- ANN 是所有實用 vector DB 的基礎。品質指標 = recall（真正 top-K 中找到幾成）；0.95 對多數應用已足夠。
- 三者權衡：Recall、Latency、Memory（尤其 RAM）。

### 索引演算法（面試只要有直覺，不需會實作）
實務上哪種索引較好很難靠推理證明，要用帶標準答案的 evaluation set 實測 recall/latency；vector DB 的好處之一就是可換索引/調參數而不改應用。

**HNSW**（最重要）
- 類比 skip list 的「快速道」：多層 graph，每個 vector 是 node，插入時找最相似的 vectors 建 edge。Layer 0 含全部 vector 且與近鄰相連；每個 vector 以機率被提升到更高層（Layer 1 數萬、Layer 2 數百…），高層作長程連結。
- 搜尋：從頂層隨機 entry point → greedy 移到最接近 query 的鄰居 → 走不下去就下一層 → Layer 0 做較徹底的局部搜尋取 K 個。O(log n)，通常 95%+ recall、低延遲，故為預設選擇。
- 代價：記憶體約為原向量的 2 倍（要存 graph edges）；建索引慢；insert 較貴（要在每層找位置並建連結）。
- 面試說法：「多層 graph，從稀疏頂層 greedy 導航，逐層降到密集層，像 skip list 用在高維空間。」

**IVF（Inverted File）**
- k-means 把向量分群，每群有 centroid；查詢先找最近的 centroid 再只搜那些群。1000 群搜 10 群 = 少 99% 比較。
- 邊界問題（類似 geospatial）：query 靠近群邊緣要搜相鄰群，高維有更多邊。`nprobe` 控制搜幾群：越高 recall 越好但越慢；單一 query 可平行，但在高負載下平均延遲會變差。
- 比 HNSW 建得快、insert 好處理（指派到群即可）、記憶體少；缺點同延遲下 recall 通常較低，尤其資料不自然成群時。

**LSH（Locality Sensitive Hashing）**
- 設計讓相似向量碰撞到同 bucket（與一般 hash 避免碰撞相反）。常用隨機 hyperplane：向量在平面上方/下方 = 1 bit，8 個平面 = 8-bit hash。多個 hash table（不同隨機平面）提高相似向量至少共用一個 bucket 的機率。
- 查詢：在所有 table hash query → 收集候選 → 只對候選算精確距離。更多 table/bit → recall 好但更耗記憶體、更慢。
- 在 HNSW 前流行；實務上 HNSW 同延遲下 recall 通常更好。適用：極快建索引、streaming 資料、Hamming distance。

**Annoy（Spotify）**
- Random projection trees 森林：隨機挑兩向量，在其等距處切 hyperplane，遞迴分左右直到 leaf 夠小（如 100 個）；建 10-100 棵樹，查詢搜所有樹的候選 leaf 聯集再算精確距離（類似 Random Forest）。
- 殺手級特性：整個 index 是單一檔案可 mmap → 多 process 共享不拷貝、可超過 RAM、載入瞬間。
- 缺點：index 不可變（增刪都要整個重建）；適合靜態/批次更新的資料（如 Spotify 曲庫），不適合即時資料。

### Filtering 與 Hybrid Search
- Filtered vector search（例：in stock、價格範圍、今年發布）兩種做法：
  - **Post-filtering**：先取 top-N（N >> K）再過濾；filter 太嚴格可能湊不到 K 個，增大 N 又多做工。
  - **Pre-filtering**：先過濾再在子集搜；但可能無法在任意子集上用既有索引結構。
  - 哪個好取決於資料 → 面試說「我會用真實資料做 benchmark」；粗略結論：若只對資料很小的子集做向量搜尋，pre-filtering 較好。（與 FB Post Search 類似但多一個維度）
- 各家做法：
  - **pgvector**：依賴 Postgres query planner（WHERE + ORDER BY 向量距離）；filter 高選擇性時常略過向量索引直接對過濾後的 row 暴力比對（反而較快）；不做真正的 filtered HNSW traversal，filter 選擇性落在尷尬中間地帶時可能得到次優 plan。
  - **Elasticsearch**：kNN 的 filter 參數在 index traversal 期間套用；HNSW 取候選 → 套 filter → 繼續探索直到湊足；filter 越嚴格越慢，但存在就保證給 K 個。原生支援 hybrid search（BM25 + 向量，sub_searches 或 rescore）。
  - **Pinecone**：metadata（每個 vector 最多 40KB）filter 是一等公民，在 ANN 搜尋期間套用；內部對 metadata 欄位維護 inverted index 並與向量搜尋在單一操作中求交集；可調 "filter effort" 參數。
- Hybrid search（全文 + 向量，如 "red running shoes"）：平行執行兩種搜尋再合併結果，通常比單一方式好。

### Insert / Update / Index 維護
- Vector DB 偏讀多寫少。HNSW insert 昂貴；大量 insert 後 graph 品質可能退化（新向量連結不如初建時好）；IVF 隨時間 cluster 漂移需重建。
- **Hot / Cold index**：小的 hot index 放新資料（甚至只是未索引的 list 做暴力搜尋）+ 大的 cold index；查詢兩邊合併；定期 hot 併入 cold 並完整重建。此模式可推廣（如罕見的刪除可維護一個小的「已刪除」index，查詢結果前先檢查，爭取時間清理 cache/預計算）。
- Update = delete + insert；多半 soft delete，刪除向量仍佔空間、拖慢查詢直到 rebuild/compaction。
- 重建很慢（HNSW 數百萬向量可能數小時）。策略：rolling rebuild（新舊並存後切換）、分區 index 一次重建一個分區、背景 reindex 不阻塞查詢。Embedding 常變時，批次更新 + 定期重建通常比即時更新務實。
- 與傳統 DB 的主要差異：後者能即時處理大量寫入，vector DB 往往不能 → 面試要刻意討論 rebuild 策略與 side hot index。

## 何時用 / 何時不用
- 用：語意相似度（非精確匹配）。常見題型：Semantic search、Recommendations、圖片/影片相似、RAG、Deduplication（近似重複）、Anomaly detection（找與常態不相似的交易，如詐欺）。幾乎都與 AI/ML 相鄰。
- **從簡單開始**（原文核心建議）：
  - pgvector：已在 Postgres 就先用；支援 HNSW 與 IVF，處理數百萬向量沒問題；附贈 ACID、熟悉工具、可與關聯資料 join（相似商品且有庫存且在使用者地區 = 一個 query）。
  - Elasticsearch kNN：已有 ES 就加向量；hybrid search 開箱即用；缺點 ES 本身營運複雜。
  - Redis Vector Search：需要即時、低延遲；索引選項比專用 DB 簡單。
  - S3 Vector：AWS 新服務，向量存 S3 並用 S3 API 查詢；已用 S3 且不想多加系統時。
- 專用 vector DB：經驗法則 **超過 1 億向量** 才考慮。Pinecone（全託管 serverless、最好營運、成本高/控制少）、Weaviate（開源、hybrid search 佳、GraphQL API）、Milvus（開源、可到數十億向量、營運複雜—多種節點的分散式系統）、Qdrant（開源 Rust、filtering 特別好）、Chroma（輕量、原型/LLM/RAG 常用）。
- 不用：當 source of truth 或交易型資料庫；精確 ID 查詢（用一般 DB）。

## 面試常考的進階點
1. **架構模式**：(1) Vector DB 作為獨立服務（最常見）— app 產生 embedding → 向量服務回傳相似 item IDs → 從主 DB 取完整資料；(2) Hybrid search — 關鍵字 index（ES）+ 向量 index，用 ranking function 合併；(3) Two-stage retrieval — 向量搜尋回大候選集（如 top 1000），再用較精緻但較慢的模型 rerank（推薦系統常見，reranker 可用 embedding 沒捕捉的 feature）。原文建議除非題目專注於此，大多數題目用 Pattern 1，避免過度複雜。
2. **要主動討論的設計決策**：一致性（向量搜尋結果可略 stale，新 item 數秒到數分鐘後才可搜尋，可 eventually consistent）；更新策略（即時 vs 每小時批次）；filtering 策略（pre/post/hybrid，filter 選擇性高時特別重要）。
3. **較少見的**：embedding model 選擇（影響維度、品質、延遲；一般說「sentence transformer 或 OpenAI embedding API」即可）；index 類型（「HNSW 是通常的正確答案」，除非極度寫多、超大規模或記憶體受限）；embedding 更新（換模型要大規模重建 → API 要記錄是哪個 model 產生的 embedding，避免用錯 embedding 搜尋）。
4. **Embedding drift**：換 embedding model 後舊向量全部不相容 → 重新 embed 全部（昂貴）或過渡期維護多套 index。
5. **Cold start**：新使用者沒有行為可 embed → 需要 fallback。
6. **維度 vs 效能**：高維捕捉更多細節但搜尋慢、佔記憶體；有些應用 128 維就夠。
7. **Index 建置時間**：HNSW 一千萬向量可能需一小時以上，影響部署變更與故障恢復速度。
8. **Recall/latency/memory 旋鈕**：HNSW 參數、IVF 的 nprobe、LSH 的 table/bit 數。
9. **Filter 策略的決策**：寫出 benchmark 計畫；了解 pgvector 的 planner 行為與 ES 的 traversal-time filter。
10. **精確 KNN 的合理性**：資料量小或需精確時，SIMD/GPU 暴力搜尋也是選項。

## 關鍵數字
- Embedding 維度：128-1536 常見（OpenAI 1536；開源常 384 或 768；text-embedding-3-large 3072）。
- 記憶體：float32 每維 4 bytes；1536 維 ≈ 6KB/向量；100 萬向量 @1536 維 ≈ 6GB（僅向量），HNSW 約加倍。
- 精確 KNN：100 萬 × 1536 維 ≈ 60 億次浮點運算/query。
- 延遲：調好的系統可 sub-10ms，常見 1-5ms。
- Recall：95%+ 通常可接受；99%+ 可達成但代價較高。
- 吞吐：in-memory index 每節點每秒數萬 query 是現實的。
- 專用 vector DB 門檻：> 1 億向量。HNSW 建置：一千萬向量可能 1 小時以上；數百萬向量可能數小時。Pinecone metadata 每向量最多 40KB。

## 相關題目
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)（filtering 類比）
- [ChatGPT](../../hellointerview-breakdowns/chatgpt.md)（RAG 相關，補充）
- [YouTube](../../hellointerview-breakdowns/youtube.md)（相似影片 / 多階段推薦，補充）
- [Instagram](../../hellointerview-breakdowns/instagram.md)（推薦 / 相似內容，補充）

## 自測問題
1. 為何要用 ANN 而非精確 KNN？衡量品質的指標是什麼？
   答：精確 KNN 是 O(n)（100 萬 × 1536 維約 60 億次運算/query）。ANN 以少量準確度換速度；指標 recall（真實 top-K 找到的比例，95%+ 通常足夠），並在 recall/latency/memory 間權衡。
2. 解釋 HNSW 如何搜尋，以及它的代價。
   答：多層 graph，頂層稀疏、Layer 0 含全部；從頂層 greedy 走向最近鄰居，逐層下降，Layer 0 做局部搜尋；O(log n)、95%+ recall。代價：記憶體約 2x、建置慢、insert 貴。
3. Pre-filtering 與 post-filtering 的取捨？
   答：post 可能湊不到 K 個（filter 嚴格）；pre 可能無法用向量索引在任意子集上。取決於資料，應 benchmark；子集很小時 pre-filter 通常較好。
4. 如何處理即時 insert 又保持查詢品質？
   答：hot（小/暴力搜尋）+ cold（完整 index）雙 index，查詢合併，定期併入 cold 並重建；soft delete；rolling / 分區 / 背景重建。
5. 什麼時候該從 pgvector 升級到專用 vector DB？
   答：超過約 1 億向量或功能需求超出擴充（如極大規模、複雜 filter）；否則 pgvector 提供 ACID、join、少一套營運系統。
