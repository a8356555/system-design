# MAPS: Netflix's Multimodal Asset Personalization at Scale
> 原文：https://netflixtechblog.com/maps-netflixs-multimodal-asset-personalization-at-scale-32f96320785e（作者 Emma Yanyang Kong 等 8 人；2026-08-28 發表。原文經 Wayback Machine 存檔 https://web.archive.org/web/2026/https://netflixtechblog.com/maps-netflixs-multimodal-asset-personalization-at-scale-32f96320785e 核對，下列「原文重點」已逐條對照原文） ｜ Netflix ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DdT76cJiXqJ（2026-09-15）
> 註：貼文本身沒附原文連結，原文是依貼文主題（cold start、CLIP、五種畫布合併）以搜尋比對的，吻合度高但未經作者確認。

## 一句話重點
兩個各自在線上 A/B 沒顯著效果的改動（CLIP embedding 讓模型看懂素材內容；五個 canvas 的模型合併成一個），合起來才出現顯著提升，是 cold start 的複合效應案例。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- Netflix 個人化模型過去把每個 artwork / video preview 當不透明 ID，只學「member 點了哪個」，看不懂圖片或影片內容。
- 新片上線沒有互動資料，模型只能退回「哪個最熱門就推哪個」，典型 cold start。
- 兩個修法：(1) CLIP embedding 讓模型「看懂」圖，把視覺特徵接進 asset representation；(2) 把分散在五種畫布尺寸（billboard、vertical-box、short-panel 等）、各自獨立訓練的模型合併成統一模型。
- 兩個方向各自線上 A/B 都失敗，合在一起卻有明顯提升。（貼文後續內容未取得。）

## 原文重點
### 背景與問題
- Netflix 為會員個人化 artwork 與 video preview（統稱 assets）；舊模型把每個 asset 當 opaque ID，新片上線 asset 無歷史，只能加大 exploration、退回忽略個人口味的 popularity heuristic，等互動累積後個人化才接手。
- 痛點在 Netflix 十年來最大的 TV home-screen 改版：short-panel 一夕之間成為主導 canvas，卻是歷史資料最少的 canvas。
- 涵蓋三個 production 系統：artwork 個人化、query-aware artwork ranking、video preview 個人化，外加選 embedding 的便宜 proxy 做法。

### 兩個方法
1. Content-aware embeddings：
   - 對 artwork 用預訓練 CLIP 圖像 embedding（768 維），與 asset 的 learned ID embedding concatenate 後過 MLP 得 asset representation；新 asset 一建立就有 embedding，偏好以影像 embedding 空間表達，可跨 title 轉移（例：偏好某喜劇演員的 artwork，新片中該演員為主的 asset 自動被偏好）。
   - 對 video preview：舊的 SeqCLIP（逐 frame CLIP 後平均，抓不到聲音）→ MediaFM（Netflix 首個自家多模態 foundation model，在 8000 萬個 shot 上訓練；每個 shot 融合視覺[SeqCLIP]、音訊[預訓練語音/音訊 embedding]、文字[caption 經大型文字模型]），整合方式與 CLIP 相同，無需新基礎設施。
2. Model consolidation：把五個 canvas（billboard、vertical-box、horizontal-panel、short-panel、landscape-panel）專屬模型合為一個；ID-based 模型不知道同一場景不同裁切是相關的，故訊號無法跨 canvas；CLIP 對 crop / resize / aspect ratio 大致不變，同場景不同畫布的圖 embedding 相近，讓訓練訊號跨 canvas 共用，資料少的 canvas 收益最大。

### 關鍵設計：reward-based weighting
- 合併後的難題：各 canvas impression 量差很多、各互動類型對長期體驗價值不同；直接用 raw count 會讓高流量 canvas 與高頻互動主導，手調權重則變成任意超參數與無止境的線上掃參。
- 做法：依互動類型的 long-term reward 分數（ρ，承襲 Netflix long-term reward modeling）對每個正樣本加權；因互動類型在各 canvas 分布不均，自動重平衡 canvas 混合，貢獻與其帶來的長期價值而非 impression 數成比例，無須手設權重。

### 離線評估：IPS
- 用現行 production policy 的 log 評新模型有偏；改用專屬 exploration 流量 slice（隨機 policy、從已知分布抽 asset，serving 時精確記錄 propensity）做 inverse propensity scoring，得無偏的候選 policy 報酬估計；以相對 production baseline 的比值呈報，須先贏 IPS 才給 A/B 流量。原文稱 propensity 為構造已知而非事後估計，是離線數字貼近線上結果的最大原因。

### A/B 結果
- Artwork 三個變體（對舊五模型 production）：V1 = 五個 per-canvas 模型各加 image embedding；V2 = 統一模型但只用 ID；V3 = 統一模型 + embedding。離線 IPS：兩種想法都在資料最稀疏的 short-panel 與 landscape-panel 有幫助，V3 最強；±1% 內視為不顯著，V1/V2 多數落在此帶內。
- 線上 A/B（所有裝置平台、至少 4 週）：V1、V2 皆持平不顯著，只有 V3 顯著提升，現已在 production。
- V3 在 short-panel 的 lift 為 5.691%（原文未明確標單位/指標，行文脈絡為離線 IPS 圖），大於 V1 與 V2 加總，原文稱為複合而非相加。
- Home-screen 改版：上線前先出貨 V3，以為期一個月、保留小比例舊模型對照組的 holdback A/B 測；discovery 核心指標與 streaming hours 皆顯著提升，且大於 steady-state ablation。
- Video preview（5 週線上 A/B、所有裝置）：MediaFM > SeqCLIP > ID-only，離線 IPS 與線上排序一致；MediaFM 在核心 streaming 指標對 ID-only 顯著提升且勝 SeqCLIP；TV 增益最大；音訊與 timed text 提供額外價值；MediaFM 已成為所有平台的預設 video preview embedding。

### 架構：Netflix Embedding Store
- Netflix AI Platform 的一部分，託管 title、game、member profile、多媒體 asset 的 dense embedding；foundation model 編碼一次，所有下游（artwork、query-aware ranker、video preview 等）以同一介面取用，且訓練與線上 inference 取得完全相同的 embedding，避免 training-serving skew。
- 解耦 foundation model 更新與個人化模型部署：新 embedding 或新版本可獨立註冊、catalog 範圍 backfill、驗證，下游僅憑設定即可使用，不需改 code 或協調發版。
- 下一步：朝統一的 image/text/video 共享語意空間發展，支援跨模態檢索與跨 surface 的統一 asset ranking。

### 其他
- Linear probe 篩選：對固定 title 集，用 exploration 資料取各 title 經 propensity 校正後的 debiased popularity winner 當二元標籤（贏家 1、其餘 0），只用 asset embedding（不含 title、cast、metadata）訓練線性分類器（binary cross-entropy）；刻意線性且僅用 embedding，以隔離 embedding 編碼了多少熱門驅動因素，以隨機猜測為基準。先用它篩掉大批候選、剩 SeqCLIP 與最佳 MediaFM 兩個進入完整離線與線上評估；三種訊號（probe accuracy、離線 IPS、線上 A/B）排序一致，因此現在每個新版 MediaFM 發布前都先過 linear probe。
- Query-aware ranking：CLIP 的圖文共享空間，用 query 的 CLIP 文字 embedding 與 asset 的 CLIP 圖像 embedding 的 cosine similarity，與原個人化分數以權重 α（0-1，經線上 A/B 調）混合；搜尋時意圖明確（如找某演員）應優先呈現該演員的 artwork；因 CLIP embedding 已在 asset representation 內，幾乎沒有額外建模成本。

### 取捨
- 單獨上任一項看不到收益；原文教訓是「先找第二個阻擋因素，再下結論說 content feature 沒用」（V1 缺足夠資料學會用 embedding，V2 有大量資料但只有 ID 資料而新 asset 沒有）。（補充：若只逐項 A/B，可能誤砍有價值的改動。）
- 統一模型需要 reward 加權處理 canvas 間資料量不均。

## 面試怎麼用
- Cold start 題（推薦、廣告、搜尋）：用 content embedding 讓新 item 立即可用，而非等互動累積；並列 popularity fallback 為對照。
- 實驗設計論點：改動間有交互作用時，單因子 A/B 可能全部不顯著；需要考慮組合測試或 ablation 矩陣。
- ML 平台論點：Embedding Store 解耦 foundation model 與下游模型的發版節奏。
- 低成本驗證：用 linear probe 當 proxy task 先篩候選，再花大成本做線上實驗。
- 模型數量治理：多 surface 獨立模型 vs 統一模型，資料稀疏的 surface 受益於共享。

## 相關筆記
- ../../hellointerview-learn/patterns/scaling-reads.md
- ../../hellointerview-breakdowns/fb-news-feed.md
- ../../hellointerview-breakdowns/youtube.md
