# GenRec: Towards LLM-Native Recommendation at Netflix
> 原文：https://netflixtechblog.com/genrec-towards-llm-native-recommendation-at-netflix-f20be6f643e3（作者 Ying Li、Arjun Rao、Shradha Sehgal；2026-07-30 發表。原文經 Wayback Machine 存檔 https://web.archive.org/web/2026/https://netflixtechblog.com/genrec-towards-llm-native-recommendation-at-netflix-f20be6f643e3 核對，下列「原文重點」已逐條對照原文） ｜ Netflix ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DcOZHciDJ6h（2026-08-19）
> 🗄 原站擋自動讀取，內容依 Internet Archive 公開存檔整理（2026-10 起不再以此方式讀取被擋的網站）。

## 一句話重點
Netflix 把 ranker 從「幾千個手工特徵 + 客製神經網路」改成「把使用者歷史 verbalize 成 prompt，丟給 post-train 過的 LLM，用 prefill-only 一次 forward 對整個候選集打分」，用 10-40 倍更少的 Phase-2 標註資料就贏過成熟的 production ranker。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- 以前推薦系統靠幾千個人工特徵（觀看時間、類型偏好、時段信號），每個都要精心維護；GenRec 把這一切換成一個 prompt。
- 這不只是換 model，是換掉整個 ML 基礎架構的思路。貼文標榜「5 個關鍵轉變」。
- 第 1 個轉變：Feature engineering -> context engineering。不再是數值特徵向量，而是把觀看歷史轉成自然語言；工程師的工作從「選特徵」變成「設計 prompt」，哪些事件保留、壓縮、捨棄，全在 token budget 裡決定。
- （貼文抓取內容只到第 1 點，其餘未在貼文文字中取得；下方「原文重點」以原文補上。注意：原文「Towards LLM-Native Recommendation」一節實際列 4 項轉變，貼文所稱「5 個」未在原文對上。）

## 原文重點
### 背景與問題
- 成熟的 production stack 靠數千個手工特徵加序列建模、特徵交互、多任務的專用架構；內容類型（電影、影集、遊戲、直播、podcast）與 surface 越來越多，每加一種內容或 surface 都要大量 feature engineering、架構與基礎設施改動、實驗，onboarding 成本高。
- 現成（off-the-shelf）LLM 離 production 還遠：過度推薦全球熱門、幻覺出 catalog 外的項目、無視商業限制、個人化有限。故 GenRec 是 post-train 內部 foundation LLM 的 ranker。
- 任務：full-catalog ranking（或給定候選集時 top-K）；輸入 (user, context[device/surface/locale/time], time, history)，輸出 catalog 上的排序，優化長期會員效用而非僅短期互動。

### 四個轉變（原文「Towards LLM-Native Recommendation」）
1. Feature -> context engineering：prompt 即新的 feature vector，從 raw logs、metadata 建構文字 context；工作變成決定納入哪些訊號、回看多久、如何在 token budget 內壓縮。
2. 客製架構 -> foundation backbone：多任務共用同一 backbone，差異來自資料與 verbalization、post-training 目標與 reward、inference 優化；GenRec 沿用 foundation LLM 的 backbone，利於跨應用共享並開啟自然語言 steering。
3. Scaling laws 作為設計指引：傳統 RecSys 因稀疏 ID 等易遇邊際遞減，LLM backbone 在成本內「更多資料、更大模型」持續變好。
4. RecSys infra -> LLM infra：GPU 加速、vLLM/Triton 為基礎、細緻 batching 與 caching，serving 越來越像通用 LLM infra 而非 MLP / factorization 堆疊。
- （原文沒有獨立的「foundation model economics」一項；Phase-2 標註資料少 10-40 倍屬實驗結果，見下。）

### 兩階段訓練
- Phase 1：用 Netflix 專有語料 adapt 開源 LLM，建立對 catalog 與會員行為的基礎理解。原文稱相對 off-the-shelf 模型帶來 10-20% 離線排序指標提升；更新不頻繁、跨應用共享。
- Phase 2：針對 ranking post-train，多目標 loss：catalog-aware ranking（對 catalog 或候選集的 cross-entropy，正樣本取長播放、強顯式回饋並加門檻與去噪）、language modeling（保留語言理解、也保留產生推薦解釋的可能）、reward-weighted loss（以兩類 reward model 訊號給每個樣本純量權重：長期滿意度 proxy、跨內容類型/上線階段的行為再平衡；比完整 RL 簡單便宜，GRPO 等 RL 風格有額外增益但因成本留待未來）。需頻繁 refresh，並在 serving 成本約束下優化。
- Phase 2 相對 Phase 1 的增益：Phase 1 模型最新時（接近訓練截止點）離線排序指標再提升約 35-50%；Phase 1 隨新內容與口味變舊，相對增益兩週後增至約 80%。（舊稿誤寫成「Phase 1 的價值放大」。）

### 資料與 context 設計
- 數千億（hundreds of billions）筆互動事件（view、play、時長、thumbs、add to list、abandon 等）轉成單輪或多輪「對話」：user message = verbalized context/profile/history/item metadata/任務；assistant message = 會員實際互動。對話格式主要用於訓練 LM 目標；inference 不 decode assistant message。
- Context window 視為「feature budget」：保留高訊號且細節豐富的互動、省略低訊號事件、摘要重複模式、選擇性展開重要項目。
- 同時把 prompt 結構設計成共享前綴最大化，以利 prefix caching；固定 token budget 內優先近期、高訊號歷史。
- 三步優化：清理壓縮事件 → 找「elbow point」（MRR vs 事件數的邊際遞減點）→ 調 verbosity。結果：context token 降到約原本的 1/3，離線指標幾乎無損；serving 成本約與 context 長度成正比，故成本也約降到 1/3。

### 模型與 serving
- Decoder-only Transformer（沿用 foundation LLM）+ catalog-aware scoring head，只對 Netflix catalog 內項目打分：verbalizer 序列化 history/context/item metadata → LLM 取 pooled hidden state h → 每個 catalog item 有學習到的 embedding eᵢ，scoring head 結合 h 與 eᵢ（如 dot product 或小 MLP）得分 sᵢ → softmax 後轉排序。backbone、head、item embedding 聯合訓練；超大 catalog 可用 sampled softmax 或候選集。
- Serving 成本三因素：模型大小、context 長度、inference 模式；三策略：較小/蒸餾模型（常搭配更大或更針對性的資料）、積極壓縮 context、prefill-only。
- 關鍵：prefill-only inference，prompt 只消化一次，單次 forward 就對整個候選集打分，不做昂貴的 autoregressive decoding；跑在 Netflix 的 vLLM infra 上。

### 結果
- 離線：用約 40 倍更少的 Phase-2 標註樣本，MRR 約 +1.6%（對多年調校的 production ranker）；從強 Phase-1 起步，視配置以少 10-40 倍 Phase-2 標註即可持平或超越；增加 Phase-2 資料與輸入訊號仍持續進步。
- 約 1B 與 10B 參數 backbone 的 MRR 都隨 Phase-2 資料量成長，大模型絕對 MRR 較高、scaling 曲線相似；固定訓練預算下 1B 到 10B 越大越好。
- 線上 A/B：batch-compute recommendation surfaces，約 10% Netflix 流量、約 4 週，在低資料、低訊號配置下，短期與長期線上指標皆統計顯著優於 production baseline。

### 取捨與限制
- 線上絕對提升幅度未公開（僅圖示）。（以下為補充評論，非原文論述：）baseline 細節不足，公平性難評；Phase 1 應是巨大前期投資；測試在 batch-compute surfaces，即時 surface 的延遲成本未知；context engineering 有持續調校成本。
- 原文自述：GenRec 為「早期但有希望的一步」，結果在低資料、低訊號配置下取得，仍有 scale 資料與訊號的空間。

## 面試怎麼用
- 推薦 / ranking 題（Netflix、YouTube、News Feed）：說明 ranking 階段可以是「LLM 當 ranker」，並講清楚為何用 prefill-only（候選集一次打分，不 decode）才可能達到 serving 成本。
- 成本 / 延遲取捨：context token 是成本旋鈕（壓到 1/3 近乎無損），可以類比 feature selection 但現在是 token budget。
- Batch vs real-time：此案例只證明 batch-compute surface 可行，面試中別宣稱 LLM ranker 已可取代 online 低延遲 ranking（補充）。
- 兩階段訓練（共享 foundation 少更新 + 任務層頻繁 refresh）可支撐 model lifecycle / retraining cadence 的論點。
- 評估：offline MRR + 約 10% 流量 A/B 的驗證路徑，可作 ML 系統上線流程範例。

## 相關筆記
- ../../hellointerview-learn/patterns/scaling-reads.md
- ../../hellointerview-breakdowns/fb-news-feed.md
- ../../hellointerview-breakdowns/youtube.md
