# Semantic Search for AI Agents at Scale: Retrieval and Ranking for LinkedIn's Hiring Assistant
> 原文：https://www.linkedin.com/blog/engineering/ai/semantic-search-for-ai-agents-at-scale-retrieval-and-ranking-for-linkedins-hiring-assistant ｜ LinkedIn Engineering / 2026-06-11（作者：Nikita Zhiltsov 等） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DbI44rlAZ6L（2026-07-23）

## 一句話重點
用「單一 LLM 雙塔 + Matryoshka embedding」把 1.3B+ 份 profile 的語義搜尋做成 query 端 <100ms（p95）、離線預算 profile 向量，並用 LLM 當「裁判」產生訓練標籤，讓 recall 與品質同時成立。

## 作者的解讀（貼文重點）
- 作者開頭：LinkedIn 有「10 億個 users」，語義搜尋本身不難，難在「ms 內跑完還要準」，所以建了 MUSE。
- 傳統搜尋靠 keyword，語義搜尋靠 vector：履歷與 query 都被模型轉成向量，意思近的向量也近。
- 例：「資深 ML 工程師」與「機器學習技術主管」向量接近，「會計師」很遠。
- 搜尋從「有沒有這個字」變成「意思夠不夠近」。
- 貼文在此處結束（取得的內容止於概念介紹），後續「架構決策」部分未見於抓到的文字；以下以原文補足。

## 原文重點
### 背景 / 問題
- Hiring Assistant 要把招募者的自然語言 query 對上 1.3B+ member profiles。
- 同一種資格有數十種描述方式。Boolean keyword search 對約 50% 的 query 回傳零結果；faceted（屬性）search 覆蓋高但撈出很多不合格的人。→ 品質 vs 覆蓋的兩難。

### 整體 pipeline（5 階段）
1. 自然語言 query 輸入
2. Query understanding：專有 LLM 把 free text 解析成結構化的職務與資格
3. MUSE（Member Understanding Semantic Embeddings）embedding retrieval：對 1B+ 預先算好的 profile 向量做 ANN，並套 attribute filter
4. 與其他 sourcing 策略合併，L2 ranker（DCNv2，針對 recruiter engagement 最佳化）重排
5. LLM guard/評估：判斷候選人與職缺的契合並附自然語言解釋

### 設計決策
- **Dual-tower、共用單一 LLM**：query 與 profile 編進同一向量空間。Query 由 vLLM 線上算（p95 <100ms）；profile 向量離線預算。
- **Matryoshka embedding**：一個 4096 維向量內嵌 2048 / 1024 / 512 維。2048 維用於 ANN 檢索（1B+ 規模），完整 4096 維作 L2 ranker 特徵。設計理由：粗訊號（title、seniority、location）放前面低維，細緻的資格推理放高維。
- **Constitutional AI 式監督**：以產品政策定義「什麼叫 qualified」。Expert Judge（專有 LLM）是政策的參考實作與種子標籤來源；其產能有限（數十萬標籤等級），所以用 MUSE Teacher（open-weight reasoning model，prompt-engineered）複製其判斷，量產至百萬級訓練標籤。有 chain-of-thought 的模型明顯較準；迭代 prompt 帶來 +24% Kappa。與人工標註不一致時，高信心 Teacher 預測約 4/5 次是對的。
- **Lambda architecture**：Batch layer 每週對 1B+ profile 全量 LLM 推論；Speed layer 每日以 CDC 對新增/更新 profile 做 delta 推論。Apache Iceberg 作 single source of truth（time-aware feature 避免 look-ahead bias）；Venice KV store 存 4096 維向量；Galene 做 IVFPQ ANN index（含 inverted index 整合）。
- 優化：bisecting k-means 初始化 centroid；inline filtering 略過被過濾文件的距離計算；兩階段 pipeline 解耦（inverted index → forward index 取值）。

### 取捨
- ANN 犧牲 recall 換速度，post-filter 再丟掉一批，「兩種損失相乘」；原文估計 exhaustive kNN + pre-filter 在同等相關度下可多約 30% 候選人（已知限制）。
- 對 embedding 任務，base model 的 post-training 目標（contrastive）與下游任務對齊，比參數量更重要。
- 候選人數量少 4% 但品質高（見結果）。

### 結果
- 離線（Expert Judge replay）：pre-L2 HRR +1%、Facepalm rate −5%、76% 平均 pool 利用率 @ 96% query coverage、post-L2 HRR +4%。
- 線上 A/B（2 週）：post-LLM-Guard HRR +2.7%、InMail sends/seat +4.1%、Eval Pass Rate +3.8%、InMail accepts/seat +1.8%、candidates sourced/seat −4%。MUSE 成為品質最高的 sourcing 策略。
- 評估階梯：PyTorch 訓練指標（小時級）→ 離線 Expert Judge replay → 線上 A/B；replay 的 HRR/Facepalm 趨勢可預測線上方向。

## 面試怎麼用
- **語義/向量搜尋題**（People/Job/Post search）：舉「query 線上算、document 向量離線預算」的標準切分，以及 ANN index（IVFPQ）+ KV store 分工。
- **Embedding 維度取捨**：Matryoshka 讓一份向量同時服務 retrieval（低維省成本）與 ranking（高維保真），避免維護兩套模型。
- **Index freshness**：週批 + 日 CDC delta 的 Lambda 模式，說明「全量重建 vs 增量更新」的折衷。
- **多階段 ranking（recall → rerank → LLM verify）**，及「ANN 與 post-filter 損失相乘」是好用的 failure mode 論點（filter 應盡量 pre-filter / inline）。
- **評估設計**：用 LLM judge 擴大標籤，再用人工校準，並建立離線 replay 與線上 A/B 的相關性。

## 相關筆記
- [向量資料庫](../../hellointerview-learn/deep-dives/vector-databases.md)
- [Elasticsearch](../../hellointerview-learn/deep-dives/elasticsearch.md)
- [Change Data Capture](../../hellointerview-learn/deep-dives/change-data-capture.md)
- [FB Post Search](../../hellointerview-breakdowns/fb-post-search.md)
