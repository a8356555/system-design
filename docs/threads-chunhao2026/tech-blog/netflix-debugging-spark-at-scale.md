# Running Apache Spark Experiments in My Sleep (and on a Plane)
> 原文：Netflix Technology Blog 文章，作者 Prashanth Gedde Narayanaswamy，2026-10-14；原站 URL 未取得，內容取自 https://noise.getoto.net/2026/10/14/running-apache-spark-experiments-in-my-sleep-and-on-a-plane/ 的摘要（非直接讀原站） ｜ Netflix / 2026-10 ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/DdWgWTbAHbz（2026-09-16）
> 註：貼文日期（9/16）早於 getoto 轉載日期（10/14），原文實際發表日未確認；貼文沒附原文連結，原文是依主題搜尋比對的。

## 一句話重點
有些 bug 只在 production 全量資料下出現，sample 抓不到；Netflix 的解法不是把單次 run 變快，而是用 branch 隔離把除錯變成「同時跑多組實驗」的平行系統。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- 有些 bug 只在 production full scale 出現，unit test 與小樣本完全抓不到。
- Netflix 工程師把「除錯」本身重新設計成一套平行實驗系統。
- 連飛機上斷斷續續的 wifi 都能拿來追進度。

## 原文重點
### 背景與問題
- member-sessionizer pipeline 每小時處理數百億筆 client events，聚合成 viewing sessions。
- 原本預計兩週的優化拖成兩個月：問題無法在 sample 資料重現；每次全量測試要數小時，一天只能試 3-4 次。
- Sampling 失敗的原因是 data skew：閒置的 Netflix 分頁整晚串流會產生數萬筆 telemetry，一般 session 只有少數幾筆；1% sample 會漏掉這些極端長尾 session。所以測試要用「一整小時未取樣的 production 資料」。

### 架構：branch-driven 平行實驗
- Dataflow（Netflix 建置/測試/部署 data pipeline 的 CLI）搭配 Maestro（workflow orchestrator）：push feature branch（例 `pgn/cap-experiment`）會用 sanitized branch name 標記部署的 workflow、tables 與 namespace，避免並行 run 互相碰撞。
- 一個 branch = 一個獨立實驗，參數化（cap size、shuffle partitions、feature flags）。五個循序 10 小時測試壓成一次最慢 job 的時間。
- 好處：per-branch table 自動 provisioning、event 結構改變時無痛更新；叢集競爭時有時只能同時跑 2-3 組而非 5 組，仍遠勝循序。

### 營運工具
- AI agent 處理雜務：改 scheduler config、觸發部署、輪詢指標、比較各變體 spill / failure 次數；封裝成可重用 skill `/sandbox-deploy-and-run <module> <scheduler-file> [PARAM=value]`。
- Workbench 雲端開發環境 + tmux，長任務不怕筆電睡眠或斷網。作者在 24 小時航班上於登機口啟動批次、用 AI agent 透過不穩定機上 Wi-Fi 看結果，完成 4-5 個實驗循環。

### 根因發現
- `collect_list` 會把整個 event bag 緩衝在記憶體；長 session 的 OOM 與單列重量相關，而非總資料量。
- 兩個放大因素：(1) 型別變更與 boxing：session ID 從 8-byte Long 變 UUID string；欄位包 Scala `Option` 迫使 typed Dataset 反序列化成 JVM 物件，增加配置與 GC 壓力。(2) 肥大屬性：未使用的 per-event 欄位（referrer URL、test allocations）每筆多數百 bytes，被 collect_list 放大。
- 反直覺：把 row 變窄反而增加記憶體壓力。表縮小後低於 Spark auto-broadcast 門檻，planner 改用 broadcast join；broadcast 把 build side 釘在 executor 記憶體。AQE 把九個 sort-merge join 悄悄改寫成 broadcast hash join，每個都低於 400 MB 限制，但累計單一 executor 釘住約 3.1 GB，超過 container 限制。

### 四項修正
1. 從不為 null 的欄位由 `Option` 改為原生型別：peak executor memory 從約 112% 降到約 58% slot 容量，無 spill。
2. 瘦身 event bag：移除未用欄位，session 不變的 metadata（app version、country）上移到 session header，每 session 存一次。
3. 在 Window stage 之前（而非之後）限制 session 大小。
4. 把 AQE runtime broadcast 門檻降到 10 MB（compile-time 門檻不變），釋放約 3.1 GB executor 記憶體。

### 教訓與取捨
- 規模型 bug 需全量測試；平行化優於單次優化。
- 記憶體受限工作負載，單列寬度比總量重要。
- Tuning 買到的是 headroom，不是架構改變；資料模型若允許無上限 row 成長，終究要重新設計。
- 維持單一實驗日誌，強制「每次只改一件事」；要用峰值 skew 驗證修正，離峰驗證會藏問題。

## 面試怎麼用
- Data pipeline / 大規模處理題：論點「skew 與長尾導致 sample 失效」，說明為何要在全量資料或 shadow 流量上驗證。
- Hot key / skew：單一 session 事件數無上限，需要在聚合前 cap（補充：對應 partition skew 與 hot key 處理）。
- 效能除錯：用 parallel experiments 取代 sequential tuning，以環境隔離（branch-tagged namespace）避免互相污染。
- 可觀測性/成本：Spark AQE 的自動優化可能反咬一口（broadcast 累積），說明自動 planner 的風險。
- 資料模型設計：避免無上限的 per-key 集合，必要時重新架構（stream processing / 增量聚合，補充）。

## 相關筆記
- ../../hellointerview-learn/patterns/scaling-writes.md
- ../../hellointerview-learn/patterns/long-running-tasks.md
- ../../hellointerview-breakdowns/metrics-monitoring.md
- ../../hellointerview-breakdowns/ad-click-aggregator.md
