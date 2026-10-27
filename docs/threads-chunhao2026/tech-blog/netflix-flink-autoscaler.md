# A Tale of Two Flink Autoscalers
> 原文：https://netflixtechblog.com/a-tale-of-two-flink-autoscalers-e9f6a1b1492b ｜ Netflix / 2026-09（InfoQ 報導日 2026-09-07） ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/Dc3iu_KjCVY（2026-09-04）
> 🗄 原站擋自動讀取，內容依 Internet Archive 公開存檔整理（2026-10 起不再以此方式讀取被擋的網站）。

> 取得方式備註：貼文沒附連結；原文經 Wayback Machine 存檔（https://web.archive.org/web/2026/https://netflixtechblog.com/a-tale-of-two-flink-autoscalers-e9f6a1b1492b）核對，下列「原文重點」已逐條對照原文（作者 Samuel Yeboah、Francesco Di Chiara、Mingliang Liu）。

## 一句話重點
Netflix 自建 autoscaler 從 container 外看 cluster 指標，對 backpressure / I/O 卡住的 job 是盲的；OSS Flink autoscaler 用每個 operator 的 True Processing Rate 在 job graph 內部算 per-vertex parallelism，因此逐步遷移。

## 作者的解讀（貼文重點）
- 自建 autoscaler 跑多年，致命盲點：job 完全卡住它卻看不出來；問題不在程式碼，在指標選擇。
- CPU 是個謊言：串流 job 卡住多半是 backpressure 或 I/O，不是 CPU 過載，這類瓶頸對外部觀察者不可見。
- 正確訊號是 TPR = 觀測 throughput ÷ busy fraction；70% busy 處理 700 筆/秒的 operator，TPR 為 1,000 筆/秒，才是真實容量。
- 外部觀察 vs 內部理解：自建版在 container 外看 CPU；OSS 版在 job graph 內、以每個 subtask 為單位計算；同一個 job 兩套判斷可能完全不同。

## 原文重點
### 背景 / 規模
- Netflix 自 2017 起用 Flink 做串流處理；2026 年營運 30,000+ Flink jobs、橫跨多個 AWS region。多數 job 由管理平台 Data Mesh 產生，少數成長中的 custom jobs 由各團隊自建（個人化、Ads、Live）。負載隨日週期、上線、區域 failover 波動。
- 縮放成本不低：預設要 savepoint → 優雅停止 → 以新規模重啟，大型 stateful job 要數分鐘；所以靜態配峰值浪費、配平均則 surge 時 lag。

### 舊 autoscaler（約 2019，跑在 Mantis 上）
- 自身是個串流 job，從 Atlas（telemetry 平台）消費 cluster 層級的 CPU、網路、Kafka lag、input rate、consume rate；綜合 lag 推算的追趕時間、CPU/網路門檻、歷史表現、近期 input rate 迴歸來決定擴容或縮容；把 TaskManager 總數當成單一旋鈕。
- 優點：獨立於 Flink 平台、不受 Flink 自身問題影響；因為本身是串流 job，每個 autoscaler node 處理一部分 job，免寫 sharding。
- 成效：數千條 pipeline 資源用量降 25%-45%。
- 根本限制：job 內所有 operator 共用同一個 scaling 決策；對有分支、join、TB 級 state 的 stateful pipeline 不足，因為資料流不同部分需求不同；也無法看見 operator 內部的 metric 盲點。
- 具體事故：job 可能完全忙碌卻不反映在 CPU 上而卡在劣化狀態；近期一次網路遷移悄悄改變部分流量的回報方式，Atlas 部分指標不再準確，缺口直到之後在 production 才浮現。

### OSS Flink autoscaler
- 用 throughput 與 busy time 估計每個 operator 的 true processing rate（TPR，全忙時能維持的吞吐）；Flink 每個 subtask 回報「每秒實際工作比例」，與 backpressure / idle 時間分開。從 source 起走 job graph，用各 operator 的 TPR、input/output ratio、target utilization 算每個 vertex 所需 parallelism，使無 operator 成為瓶頸。
- 範例：700 records/s、70% busy → TPR 1,000 records/s。
- 兩者契約不同：OSS 版可縮放 stateful、多 operator 的 job，且每個 job 可自帶設定（stabilization period、門檻等）。（DS2 / FLIP-271 出處：原文未提，屬外部知識，未核對。）

### Netflix 的客製工程
- OSS 版原綁在 Flink Kubernetes Operator，但 Netflix 平台跑在自家 control plane；社群後來把核心邏輯拆成獨立 library，並重構四個介面（context、state store、event handler、realizer）讓 Netflix 插入自家生態。
- 服務是 Spring Boot + Temporal：orchestrator workflow 約每分鐘向 control plane 輪詢啟用 autoscaling 的 job，每個 job 起一條長駐 workflow，向其 JobManager 拉 per-vertex metrics、跑 OSS 評估演算法，有決策就交 realizer 經 control plane 執行。
- 為何 workflow-per-job：最初單一 batch loop 跑全部 job，一個慢或壞的 job 會卡住後面所有 job；改 per-job durable workflow 後隔離 blast radius，失敗各自重試。
- 三個工程缺口：(1) 高 parallelism 的 metric 收集：JobManager 快取暫態 metric 名稱並一次清理、加 server-side filtering，使 autoscaler 可處理至 3,000 subtasks（先前約 1,000 以上就吃力）；部分在內部 fork，部分上游（如 FLINK-36172）。(2) 保留 forward chaining：forward 連接的兩個 vertex 必須同 parallelism，單獨縮放 Flink 不會報錯而是默默把該邊變成 network shuffle；fork 偵測 forward-connected subgraph 並整體縮放。(3) 尊重 sink 上限：偵測 async-sink backpressure（fork 變更），避免擴容進吃不下的 sink。
- Realizer 動作前的安全檢查：company-wide region failover 疏散中的 region 不縮容、確認磁碟足夠容納 checkpoint state、較大 cluster 加少量 standby buffer。
- target utilization 設 0.45，低於社群預設 0.7；縮太狠會 CPU 飽和、lag 飆高，且重啟後 metric window 與 stabilization period 都要重建，故以些許效率換穩定、減少 rescale 次數。

### 結果與未解
- OSS 版去年對 custom jobs GA；client telemetry and logging 團隊年化 Flink 運算支出降 58%、約省 US$1.1M/年。三因素：依日夜/週末流量動態調整而非配峰值、持續調整取代人工優化、統一 container 規格改善 bin-packing 與縮放粒度。
- 目前 scaling stateful job 最大剩餘成本是重啟與 state recovery，非 scaler 邏輯；Flink 2 disaggregated state（state 放外部儲存）可降低 rescale/recovery 對 state 大小的依賴，Netflix 已開始支援 Flink 2.2 並計畫實驗。
- 目標：把所有內部 scaler use case 遷到 OSS 版。
- 原文三點心得：metric 選擇比演算法精巧更重要；預設合理但保留 per-job 覆寫、隱藏需深度專業的旋鈕；Adopt then extend（採用社群方案、回饋修正、有計畫地遷移）。
- （原文未提 FLINK-38538 及「busy operator 受 output-ratio 影響」之未解項，已刪除。）

## 面試怎麼用
- Autoscaling 題（串流或一般服務）：論點「CPU 不是好訊號；用 backlog / lag 加上實際工作比例推真實容量」。
- 瓶頸辨識：backpressure 下上游看似閒、下游才是瓶頸，要 per-operator 而非 per-cluster 判斷。
- Stateful 服務的 scale 要保守（低 utilization target、rescale 成本高），並說明為何預設不是越高越好。
- 觀測性：外部黑箱指標 vs 內部白箱指標的取捨。
- （補充）build vs adopt：自建在規模下有天花板，社群方案加上自家 control plane 整合是常見落點。

## 相關筆記
- [Flink](../../hellointerview-learn/deep-dives/flink.md)
- [Kafka](../../hellointerview-learn/deep-dives/kafka.md)
- [Temporal](../../hellointerview-learn/deep-dives/temporal.md)
- [Metrics monitoring](../../hellointerview-breakdowns/metrics-monitoring.md)
