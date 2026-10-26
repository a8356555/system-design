# Threads @chunhao2026 — 系統設計相關貼文全集

> 來源：https://www.threads.com/@chunhao2026 ｜ 全帳號 276 篇（2026-06-26 ~ 2026-10-21）。本檔收錄系統設計相關 64 組，每組 = 主文 + 作者同日接續留言，原文照錄；連結含登入後收集的連結預覽卡。
> 未收錄：PM / Business / UX / Podcast Blog、多數 Cross-domain 思維文、AI 工具類（Claude Code、MCP、RAG、OpenAI agents）、Git、Unit test、生活與職涯文。

## 目錄

- **System Design Interview**：Fan-out on Read vs Write、Uber、WhatsApp、LeetCode、Tinder
- **System Design**：Circuit Breaker、OAuth 2.0
- **Case Study**：Netflix System Design - Circ、GitHub Apps JWT、Apache Spark in Spotify
- **Tech Blog**：LinkedIn Engineering Blog、GPU 每秒幾百美元，Meta 怎麼讓它不閒著？、Spotify Engineering Blog、Netflix Tech Blog、GitHub Engineering Blog、System Design Newsletter、Netflix Tech Blog、Netflix Tech Blog、LinkedIn Engineering Blog、Netflix Tech Blog、Slack Engineering Blog、GitHub Engineering Blog、Meta Engineering Blog、Spotify Engineering Blog、Netflix Tech Blog、Dropbox Tech Blog、Netflix TechBlog、Netflix Tech Blog、LinkedIn Engineering Blog
- **Tool**：ZooKeeper、ElasticSearch、REST、gRPC、Docker、Apache Flink、CDN、JWT、DNS、Load Balancer、Database Index、ACID、Idempotency、Consistent Hashing
- **Comparison**：DynamoDB vs. Redis、Write-Through vs. Write-Back、ZooKeeper vs. Redis、Redis vs. DynamoDB vs. Mongo、Polling vs. WebSocket、K8s vs. Docker、Temporal vs. Airflow 淺談、Message Queue vs. Event Bus 、Message Queue vs. Event Bus 、Parallelism vs. Concurrency、Sharding vs. Partitioning、TCP vs. UDP
- **Small Quiz**：不想當考考男，但還是想嘗試看看軟體工程師 quiz 系列、四句話關於 database index，有一句是錯的。、四句話關於 OAuth 2.0，有一句是錯的。、解答來了、四句話關於 async/await，有一句是錯的。、四句話關於 Docker，有一句是錯的。、四句話關於 WebSocket，有一句是錯的。、四句話關於 REST API，有一句是錯的。
- **Cross-domain**：Occam’s Razor 與系統設計面試

## System Design Interview（5）

### 2026-09-19 — Fan-out on Read vs Write
[原文](https://www.threads.com/@chunhao2026/post/DdePGFsDCL2)

> <System Design Interview 系列> Fan-out on Read vs Write
>
> 在設計 feed 或通知系統時,多數人第一個問題都問錯了。真正該問的不是「要用哪個資料庫」,而是「這篇貼文要在誰寫入的時候被分發,還是等誰讀取的時候才去撈?」這決定了整個系統的效能曲線。

> 1. Fan-out on Write(push model)
> 使用者一發文,系統馬上把這篇貼文寫進每個 follower 的 feed/inbox。讀取瞬間完成,因為資料早就準備好了。代價是寫入成本會隨 follower 數量線性增加。
>
> 2. Fan-out on Read(pull model)
> 系統什麼都不預先計算。使用者打開 feed 的那一刻,才去查詢所有追蹤對象、即時合併排序。寫入永遠是 O(1),但讀取成本會隨你追蹤的人數增加,查詢也變重。
>
> 3. Celebrity 問題會打破純 push
> 如果一個帳號有幾百萬 followers,單純的 push 代表一次貼文要觸發幾百萬次寫入,瞬間造成 write 熱點。這就是為什麼 Twitter 過去採用混合架構:一般帳號用 push,高 follower 帳號用 pull,讀取時再合併。

### 2026-09-26 — Uber
[原文](https://www.threads.com/@chunhao2026/post/DdwJtKnjvv0)

> <System Design Interview 系列> Uber
>
> 大家都覺得 Uber 系統設計最難的地方是「怎麼配對司機跟乘客」，其實最硬的問題是別的。

> 1. 真正難的不是配對邏輯，是怎麼在 1000 萬個司機、每秒 200 萬次定位更新的規模下，還能即時查詢「誰在附近」。線性掃描整張表算距離不 scale。Uber 用 geohash 把座標編碼成 52-bit 分數，丟進 Redis 用 GEOADD/GEOSEARCH 做半徑搜尋，過期資料自動失效。
>
> 2. 定位頻率也不完全是後端的事。Client 會根據自己的速度、方向、是否接近待配對的請求，動態調整回報頻率。省下來的頻寬跟運算量，比你想像中的後端優化更有效。
>
> 3. 「同一個司機被兩個乘客同時搶走」這種 race condition，靠 process 內的記憶體鎖是沒用的。多台 instance 互相看不到彼此的鎖，而且 process crash 鎖狀態就消失。Uber 用 Redis distributed lock 鎖住 driverId，帶 10 秒 TTL，司機接單就釋放，沒接就自動過期。

連結：https://wondering.app/learn/system-design-uber-bx557f

### 2026-10-03 — WhatsApp
[原文](https://www.threads.com/@chunhao2026/post/DeCNymBDWN-)

> <System Design Interview 系列> WhatsApp
>
> 某個即時通訊系統要保證訊息不丟、又要快，工程師最先想到的方法通常是：每個 user 一個 durable queue，保證訊息一定送到。WhatsApp 的 system design breakdown 直接把這條路堵死了，理由很實際。

> 1. Kafka per user 聽起來很合理，但每個 topic 的 overhead 大概是 50KB。十億用戶等於 50TB+ 的 metadata，還沒算訊息內容本身。Durable queue 不是不好，是 per-unit cost 在這個規模下直接爆掉。
>
> 2. 真正的解法不是找一個更輕量的 pub/sub 取代它，是把兩件事拆開：即時推送跟保證送達，根本不該走同一條路徑。Redis Pub/Sub 負責 push，at-most-once，單台 instance 可以撐到 100K updates/sec、27% utilization，輕量但會丟。
>
> 3. 保證送達的工作交給 Inbox table，而且寫入順序很關鍵：先寫進 Inbox，再 publish 到 Pub/Sub。就算這次沒人在線上收到、訊息真的丟了，使用者重新連線時還是能從 Inbox 撈回來。

### 2026-10-12 — LeetCode
[原文](https://www.threads.com/@chunhao2026/post/DeZdIQyEUAJ)

> <System Design Interview 系列> LeetCode
>
> 能跑陌生人寄來的 code，還要在 5 秒內判定對錯，同時撐住十萬人即時比賽排名，這是「設計 LeetCode」這題真正藏著的系統設計難題。
>
> 1. Submission 結果不是 sync 等出來的。API 收到 submission 先回一個 job id，丟進 SQS 排隊，worker 執行完才寫回 DB 和 Redis，client 每秒 poll /check/:id。犧牲一點即時性，換來 API 不會被慢 container 卡住，而且失敗可以 retry。

> 2. Leaderboard 不是直接查 DB。用 Redis sorted set，ZRANGE ... REV WITHSCORES 直接拿排名，client 每 5 秒 poll 一次。DB 每 5 秒被幾萬人同時查排名一定垮，5 秒的 staleness 換整個系統活下來。
>
> 3. Scaling 也用同一招。平時 leaderboard 每 10 秒更新一次就好，只有比賽最後幾分鐘才加快到 2 秒。不是做不到全程即時，是全程即時的成本不值得。
>
> 4. 連 sandbox 的選擇也是效率優先。跑陌生人的 code，VM 最安全但太重太慢，serverless 有 cold start，最後選 container，用 read-only filesystem、resource limit、5 秒 timeout、network isolation、seccomp 五層限制去補隔離性不如 VM 的缺口。

連結：https://www.hellointerview.com/learn/system-design/problem-breakdowns/leetcode

### 2026-10-17 — Tinder
[原文](https://www.threads.com/@chunhao2026/post/DemOZTnDOVq)

> <System Design Interview 系列> Tinder
>
> 兩個人在同一毫秒同時向對方滑右，系統要怎麼確保這個 match 不會被漏掉，這是「設計 Tinder」裡需要 strong consistency 的地方。
>
> 1. 兩個人幾乎同時滑右，如果用「先讀再寫」分別處理兩次滑動，很可能雙方都讀不到對方剛寫的那一筆，match 就這樣消失不見。

> 2. 想靠 Cassandra LWT 解決?它用 Paxos 做到單一 partition 內的原子性，但 overhead 不小，而且兩個人的滑動天生不會落在同一個 partition，除非故意把 partition key 設計成 smaller_id:larger_id，強迫兩筆資料待在一起。
>
> 3. 真正的解法是 Redis + Lua script。Key 設計成 swipes:user1:user2，一個 Lua script 同時完成「寫入這次滑動」跟「檢查對方是否也滑過」，整個操作是原子的，而且 in-memory，速度遠勝 Cassandra LWT。
>
> 4. 這份 Redis 資料可以很過期，因為 Cassandra 才是真正的 durable 來源，Redis 只是用來解決「同時寫入」那一瞬間的一致性問題，不是長期儲存。

連結：https://www.hellointerview.com/learn/system-design/problem-breakdowns/tinder

## System Design（2）

### 2026-10-09 — Circuit Breaker
[原文](https://www.threads.com/@chunhao2026/post/DeRsdzkE4RD)

> <System Design 系列> Circuit Breaker
>
> Circuit breaker 的「fail fast」，保護的從來不是這一次的請求，是你系統裡其他還健康的部分。
>
> 1. 沒有 circuit breaker，一個壞掉的依賴會拖垮整個系統。下游服務變慢或掛掉時，呼叫方持續發請求並等待 timeout，這些請求會一直佔著呼叫方的 thread 跟連線資源，原本只有一個依賴不健康，卻可能演變成整個系統的 cascading failure。

> 2. 具體場景：如果 service A 同時呼叫 B 跟 C，B 掛了但沒有 circuit breaker，A 的 thread 可能全部卡在等 B 逾時，連帶讓呼叫 C 的請求也發不出去，即使 C 完全正常。
>
> 3. Circuit breaker 用三個狀態解決這件事：Closed 是正常狀態；失敗率超過門檻就切到 Open，之後的請求直接失敗，連呼叫都不會發出去，這就是「fail fast」；冷卻一段時間後進入 Half-Open，放少量請求試探下游是否恢復。
>
> 4. 常見設定像 Netflix Hystrix（現在多用 resilience4j）是滑動視窗 20 個請求，失敗率超過 50% 就跳開，等 5 秒後再試探，這樣能防止一個要花 30 秒才 timeout 的慢依賴，把呼叫方的 thread pool 榨乾。
>
> 5. 這也是為什麼 circuit breaker 不能只靠 retry 取代。對一個真的掛掉的服務一直 retry，只會在它最需要喘息的時候疊加更多負載，而且完全沒有保護到呼叫方自己的資源，fail fast 保護的正是這件事。

連結：https://wondering.app/learn/circuit-breaker-fail-fast-402497fa2b0ce164685087b6

### 2026-10-11 — OAuth 2.0
[原文](https://www.threads.com/@chunhao2026/post/DeW3Lx9gapz)

> <System Design 系列> OAuth 2.0
>
> 實作 OAuth 2.0 的時候，這幾個坑你應該提前知道，不然很容易寫出一個「看起來能用，但其實不安全」的整合。
>
> 1. 先搞清楚 OAuth 2.0 解決的是 authorization，不是 authentication。它證明的是「app 拿到一個有特定 scope 的 token」，不是「使用者是誰」，如果你的系統需要知道使用者身份，該用的是建立在 OAuth 上面的 OpenID Connect，不是 OAuth 本身。

> 2. 實作 authorization code flow 時，access token 應該全程不經過瀏覽器，由後端用 code 加 client secret 去換。如果你發現 token 出現在前端的 URL 或 JS 變數裡，那其實是舊的 Implicit flow 的做法，現在已經不建議用。
>
> 3. Access token 要短效，refresh token 才長效。常見的坑是把 refresh token 存進瀏覽器的 localStorage，因為它長效又權力大，一旦被 XSS 偷走，等於給了攻擊者長期權限，應該存在後端。
>
> 4. Scope 要求越窄越好，不要圖方便要求過寬的權限。像 Google 的 gmail.readonly 只能讀信不能寄信，審核第三方 app 要求的權限時，該看的是它要了哪些 scope，不是「有沒有連上 Google 帳號」。

連結：https://wondering.app/learn/oauth-20-authorization-code-flow-6815ce6d1c3e04b127934714

## Case Study（3）

### 2026-10-14 — Netflix System Design - Circuit Breaker
[原文](https://www.threads.com/@chunhao2026/post/DeeijLkjI_M)

> <Case Study 系列> Netflix System Design - Circuit Breaker
>
> 一個每天要處理數百億次呼叫的系統，靠的不是「把請求排隊處理完」，是「直接拒絕」。這是 Netflix Hystrix 教我們的事。
>
> 1. Netflix 自己的說法很直接：在高流量網站上，一個後端依賴變慢，可能在幾秒內就把所有 application 資源榨乾。這個問題從 2011 年開始被 Netflix API team 認真處理，2012 年 11 月正式發布 Hystrix。

> 2. 真實的故障機制是：依賴變慢時，呼叫方的 thread 會卡在等回應，請求持續堆積，直到整個 thread pool 被佔滿，連處理跟這個依賴完全無關的新請求都做不到。
>
> 3. Hystrix 的核心解法不只是「電路斷開」，是 thread pool isolation。每個依賴都有自己獨立的 thread pool，一個依賴變慢只會榨乾它自己的 pool。Pool 滿了就直接拒絕新請求，不是排隊等待，這才是真正的「fail fast」。
>
> 4. 具體門檻：10 秒的滾動視窗內只要有 20 個以上請求，且錯誤率超過 50%，電路就跳到 Open，短路請求 5 秒，之後才放一個請求試探是否恢復。

連結：https://wondering.app/learn/netflix-hystrix-circuit-breaker-thread-p-f1cec347e5d6d21bc6d0a3ec

### 2026-10-16 — GitHub Apps JWT
[原文](https://www.threads.com/@chunhao2026/post/Dejwd3WgWIM)

> <Case Study 系列> GitHub Apps JWT
>
> GitHub App 要呼叫 API 前，要先證明「我是誰」跟「我能碰什麼」，而 GitHub 的做法是把這兩個問題，拆成兩層完全不同的 token 來回答。
>
> 1. GitHub App 要打 API 之前，要先用自己的 RS256 私鑰簽一個 JWT，帶著 app 的 ID 當 iss claim，GitHub 用對應的公鑰驗證簽名，私鑰本身完全不需要交給 GitHub。
>
> 2. 這個 JWT 效期最多只能設 10 分鐘，而且它唯一的用途是拿去換一個「installation access token」，真正拿去打 API 的是這個效期 1 小時的 token。JWT 回答的是「我是哪個 app」，installation token 回答的是「我能存取哪個安裝」，這是兩個分開的問題。

> 3. 一個容易被忽略的細節：GitHub 官方建議把 JWT 的 iat（簽發時間）故意設成往前推 60 秒，因為如果你的伺服器時間比 GitHub 快一點，驗證時可能會被判定成「還沒生效」而直接拒絕，這是對抗 clock drift 的實務保險。
>
> 4. 為什麼用 RS256 不是 HS256：驗證方只需要公鑰就能驗證簽名，私鑰完全不用分享出去。如果用 HS256，GitHub 等於要跟每個開發者共用同一組密鑰，風險跟管理複雜度完全不同等級。
>
> 5. 這套設計真正要解決的問題，是把私鑰的使用次數壓到最低。如果每次打 API 都要用私鑰簽一次新 JWT，私鑰暴露的次數就跟 API 呼叫量成正比。拆成兩層之後，私鑰只在換 installation token 這個動作用到一次，之後 1 小時內的所有呼叫都靠風險較低的那個 token。

連結：https://wondering.app/learn/github-apps-jwt-token-57ac5f9f7a07381136e0e41c

### 2026-10-18 — Apache Spark in Spotify
[原文](https://www.threads.com/@chunhao2026/post/Deo6A1SD6mx)

> <Case Study 系列> Apache Spark in Spotify
>
> 你每週一打開 Spotify 看到的 Discover Weekly，其實不是什麼厲害的演算法，而是一個跟時間賽跑的規模問題。
>
> 1. Spotify 有數億用戶，每個人週一都要拿到一份重新算過的 30 首歌清單。代表系統得在固定時間窗口內，掃過全站所有人的聽歌紀錄，才能找出跟你口味相近的人在聽什麼。
>
> 2. 這種「掃過所有人的資料再分群比對」的工作量，用單機程式跑的話，光讀完資料可能就要好幾天，根本來不及在週一早上準時發布。

> 3. Apache Spark 解決的正是這個問題。把同一份龐大資料集切成很多份，分散到成百上千台機器同時算，再把結果合併回來，是標準的 distributed computing 套路。
>
> 4. Spark 會盡量把中間結果留在記憶體裡，而不是像早期的 Hadoop MapReduce 一樣，每算完一步就寫回硬碟。像 Discover Weekly 這種需要反覆比對相似度的流程，這個差異就是「準時發布」跟「拖到下午才上線」的區別。
>
> 「個人化」聽起來像是演算法的功勞，但它背後其實是一場跟時間賽跑的資料處理工程。
>
> 大家工作中有沒有遇過那種「資料量大到單機根本跑不完」，逼你開始認真研究 distributed computing 的經驗？
>
> 附上學習來源： https://wondering.app/learn/apache-spark-for-engineers-5-real-world-c91d611aed5f199957b95a60 @wonderingapp

連結：https://wondering.app/learn/apache-spark-for-engineers-5-real-world-c91d611aed5f199957b95a60

## Tech Blog（19）

### 2026-07-23 — LinkedIn Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/DbI44rlAZ6L)

> <Tech Blog 系列>  LinkedIn Engineering Blog
>
> LinkedIn 有 10 億個 users。語義搜尋本身不難，難的是怎麼在 ms 內跑完，還要保持準確。
>
> 他們建了 MUSE 來解這個問題。有幾個架構決策值得深入看。

> 語義搜尋怎麼運作？
>
> 傳統搜尋靠 keyword，語義搜尋靠 vector。
>
> 每份履歷、每個查詢，都被模型轉成一組數字（vector）。意思相近的東西，向量在數學空間裡也靠近。
>
> 「資深 ML 工程師」和「機器學習技術主管」的向量很接近。「會計師」就差很遠。
>
> 搜尋從「有沒有這個字」，變成「意思夠不夠近」。

### 2026-08-04 — GPU 每秒幾百美元，Meta 怎麼讓它不閒著？
[原文](https://www.threads.com/@chunhao2026/post/DbnuDJ0krLA)

> <Tech Blog 系列>  GPU 每秒幾百美元，Meta 怎麼讓它不閒著？
>
> AI training 的流程看起來很簡單：
> GPU 拿一批資料 → 做運算 → 存結果 → 拿下一批。
>
> 如果下一批資料還沒準備好，GPU 就只能 idle。
> 而 GPU 每秒幾百美元，idle 就是在燒錢。
>
> Meta 分析後發現，storage 是瓶頸。他們做了幾件事：

> 一、三層 metadata 查詢壓成一層
> 讀一個檔案前，系統要先查「這個檔案放在哪裡」。
> 舊的架構分三層查詢，每層可能跨 region，加起來幾百 ms 才能開始讀資料。
> 改成一個 flat schema，複雜度變 O(1)。
>
> 二、刪除 proxy 中間人
> 舊系統所有讀取都要經過一台 centralized proxy server，就像每筆訂單都要先通過一個中間人。
> 每多一個中間人就又多 latency。
> 改成 client SDK 直接連 storage server，減少中間人的數量。

> 昨天遠從倫敦到舊金山，和朋友在 San Mateo 約了一間韓式叫 Daeho，沒想到這間這麼有名，我光是說要吃韓式，大家都知道要來吃這間。
>
> 晚餐時，他們都說這裡很無聊，問我幹嘛浪費一週的時間來這裡玩，我說想來體驗一週在矽谷黑客松的感覺，蠻酷的，有種劉姥姥進大觀園感。
>
> 於是今天我坐在 Visa 的辦公室寫下了這篇廢文，以此紀念黑客松的第二天。

### 2026-08-11 — Spotify Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/Db5vtTWjerH)

> <Tech Blog 系列>  Spotify Engineering Blog
>
> Spotify 有 70,000+ 個 dataset，光靠 expert 直接回答問題根本 scale 不了。
>
> 解法：在 LLM 前加一層 context layer，讓 domain expert 的知識可以複製給 2,100+ 個 user。
>
> 五個核心 components：

> 1. Cluster model，由 domain expert 擁有
> 每個 domain（廣告、podcast、音樂）有自己的 cluster。Expert 負責 encode 知識，LLM 負責推理。
>
> 2. Annotated datasets，不只是 raw schema
> 每個 dataset 加上 column 語意、cardinality、sample values。Schema 有了意義才有用。
>
> 3. 精選的 question-SQL pairs，不是直接用 log
> 從 query log 自動產生的範例？Expert 只接受 12.5%，其他 87.5% 是 debug one-off 或錯誤 pattern，直接餵給 model 只會讓它學壞。

### 2026-08-11 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/Db5xcCCDnzY)

> <Tech Blog 系列> Netflix Tech Blog
>
> Netflix 管理超過 15 PB 的 timeseries 壓縮資料，最近的資料需要毫秒級讀取，歷史資料只需要便宜地存在。他們做 tiered storage 的過程，幾乎全部繞著 immutability 轉。
>
> See Wondering course: https://wondering.app/learn/tiered-storage-designing-for-immutable-d-18b8ee3e6a5469fef5bcf336

> 1. 熱/冷資料的問題
> Recent data 需要快速讀取，historical data 只需要存著就好。把兩者用一樣的方式儲存，等於用 SSD 的價格存沒人碰的資料。
>
> 2. Kafka + Flink + S3
> 建了一條 streaming pipeline，把 cold data 從 Cassandra 搬到 S3，再加一層自訂的 read layer。P50 約 150ms，P99 約 500ms。功能沒問題，但需要維護一整套獨立的 infrastructure。
>
> 3. Insight
> 歷史 timeseries 資料永遠不會改變。Cassandra 所有為 mutable data 設計的機制，包含 compaction、read repair、speculative retry，在資料凍結後全都變成純粹的 overhead。

連結：https://netflixtechblog.medium.com/timeseries-tiered-storage-journey-kafka-flink-streams-to-native-cassandra-cold-reads-e59d597c9d60 ｜ https://wondering.app/learn/tiered-storage-designing-for-immutable-d-18b8ee3e6a5469fef5bcf336

### 2026-08-12 — GitHub Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/Db8UeM2iTS3)

> <Tech Blog 系列> GitHub Engineering Blog
>
> AI 讓寫 code 變便宜了，但 own code 的成本沒有變。GitHub Engineering 規模不小，但他們面對的瓶頸跟每個工程團隊一樣。
>
> 1. 討論的成本比 patch 本身還高。花 40 分鐘辯論要不要加一個 `last_active_at` 欄位，AI 早就把 patch 寫完了。瓶頸已經不在實作，而在討論。
>
> 2. 把 generated patch 當成 price check，而不是 deliverable。看它有沒有蔓延到不該碰的 package、有沒有辦法寫測試、有沒有觸發新的產品決策。artifact 就是成本的線索。
>
> 3. 寫 code ≠ own code。加一個從既有後端資料來的顯示欄位？便宜。改 authorization 邏輯、data retention 語義、billing 或 privacy？永遠不便宜，不管 code 有多快生出來。

> 4. 有些類別的改動，成本是永久的。Authorization、privacy、compliance、billing，這些是法律和產品決策，只是藏在 code 裡。AI 幫你更快寫出來，不代表更容易 review 或 maintain。
>
> 5. 把「這在 scope 嗎？」換成「這要付多少成本？」。做最小的 patch，放在 feature flag 後面，要求測試，記錄所有碰到的 file。從估算改成看證據：「這要這麼多成本，我們要付嗎？」
>
> AI 讓瓶頸從「寫」移到了「own」。就連 GitHub 都在面對同一個問題，這不是小公司的 growing pain，這是新常態。能快速排除不確定性的工程師，才是真正有競爭力的那個。
>
> 你們團隊在 AI 工具進來之後，評估改動的方式有改變嗎？

### 2026-08-14 — System Design Newsletter
[原文](https://www.threads.com/@chunhao2026/post/DcBi5IBCj2d)

> <Tech Blog 系列> System Design Newsletter
>
> Fine-tune 一個 3B 模型，一顆 GPU，74 分鐘。在特定任務上，它 outperform 了 frontier model，成本也低得多。AI 在 PROD 的未來是 hybrid。
>
> 1. 在特定 domain，小模型可以 outperform frontier model
> 把小模型 fine-tune 在特定 domain，可以在那個 domain outperform frontier model。Frontier model 優在廣度，fine-tuned 小模型優在深度。
>
> 先附上學習資源，可以試試看用 Wondering 來讀完這篇 tech blog：
> https://wondering.app/learn/fine-tuning-small-language-models-7edefb8c4dcb856d90912133

> 2. 為什麼公司要自己訓練小模型
> 成本低 25–60 倍，latency 從幾秒降到不到一秒。healthcare 和 finance 的 data privacy 法規，讓很多公司無法把資料送到外部 API。
>
> 3. LoRA：一顆 GPU 跑一小時
> Low-Rank Adaptation 凍結大部分 weights，只 fine-tune 小型 adapter layer。進入門檻比大多數團隊以為的低很多。
>
> 4. Distillation：讓大模型來教
> 不需要幾百萬筆人工標注資料。用 frontier model 幫你生成 training data，再拿這些資料訓練小模型。小模型繼承了大模型的推理能力，成本卻低得多。

連結：https://wondering.app/learn/fine-tuning-small-language-models-7edefb8c4dcb856d90912133

### 2026-08-19 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/DcOZHciDJ6h)

> <Tech Blog 系列> Netflix Tech Blog
>
> Netflix 推薦系統以前靠幾千個人工特徵撐著，像是觀看時間、類型偏好、時段信號，每個都要精心維護。GenRec 把這一切換成了一個 prompt。
>
> 這不只是換了一個 model，是換掉了整個 ML 基礎架構的思路。
>
> 5 個關鍵轉變：

> 附上原文：https://netflixtechblog.com/genrec-towards-llm-native-recommendation-at-netflix-f20be6f643e3
>
> 想更好吸收文章嗎？ 來試試看 @wonderingapp  https://wondering.app/learn/llm-native-recommendation-systems-06503067b7831e59eaf131b3
>
> 1. Feature engineering → context engineering
> 不再是數值特徵向量，而是把 user 的觀看歷史轉成自然語言。工程師的工作從「選特徵」變成「設計 prompt」，哪些事件保留、哪些壓縮、哪些捨棄，全部在 token budget 裡決定。

連結：https://netflixtechblog.com/genrec-towards-llm-native-recommendation-at-netflix-f20be6f643e3 ｜ https://wondering.app/learn/llm-native-recommendation-systems-06503067b7831e59eaf131b3

### 2026-08-21 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/DcTdHu2D6pP)

> <Tech Blog 系列> Netflix Tech Blog
>
> 看完這篇 Netflix ad event pipeline 的演進，最讓我印象深刻的不是架構本身，而是每個地方他們都選了「夠精準的保證」，而不是「理論上最高規格的解法」。
>
> 整理了 6 個關鍵設計：

> 附上原文： https://netflixtechblog.medium.com/behind-the-scenes-evolving-netflixs-ads-event-pipeline-for-live-part-ii-826ebf9ad9fb
>
> 學習資源： https://wondering.app/learn/real-time-ad-event-pipelines-lessons-fro-5fd85f5f4233ef2117ea104b
>
> 1. 把同步寫入從 critical path 上移除
> 每次廣告出現，原本都需要先同步寫入 Metadata Registry，等 acknowledgment 回來才能送廣告。新做法是 ad server 只管把 response 丟進 Kafka，剩下的留給下游 Flink job 做串流 join，Registry 不在 serving 的路徑上了。

連結：https://netflixtechblog.medium.com/behind-the-scenes-evolving-netflixs-ads-event-pipeline-for-live-part-ii-826ebf9ad9fb ｜ https://wondering.app/learn/real-time-ad-event-pipelines-lessons-fro-5fd85f5f4233ef2117ea104b

### 2026-08-26 — LinkedIn Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/DcgTzJ0jU0D)

> <Tech Blog 系列> LinkedIn Engineering Blog
>
> LinkedIn 的 AI code review 系統每週處理 79,000 筆 review，跨 7,500 個 repo，整體建議採納率 63.9%。這不是 demo，是跑在 production 的規模。
>
> 幾個工程師值得細看的設計：

> 1. Multi-agent 共識機制
> 多個專門化 agent 同時 review 同一個 PR，只有不同 agent 的 findings 重疊才算高信心建議。沒有任一個 model 被單獨信任。
>
> 2. 三層 context 架構
> org-wide policies → repo-level standards → case-specific guidance，把 codebase 特有的知識層層疊加進 prompt。這是 general model 不具備的。
>
> 3. 採納率因類別差距極大
> Concurrency bug：100%。Logic error：80%。Security：40.6%。AI 最有價值的地方，恰好是人類 reviewer 最容易放掉的地方。

### 2026-08-27 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/Dci51VaDSCs)

> <Tech Blog 系列> Netflix Tech Blog
>
> Netflix 分享了他們 real-time graph 的 query serving layer，8B nodes、150B edges，single-hop P50 15-30ms，3-hop P99 100-150ms。讀完之後有幾個設計決策讓我覺得很值得記下來。

> 1. BFS 而不是 DFS — 每一層的 nodes 一次平行處理，把 N 個 sequential network calls 壓成幾個 parallel batch。例如先拿到所有 profiles，再一次拿所有 viewing histories，兩個 round trip 搞定。
>
> 2. 16-24 threads，卻能承載 thousands 的 concurrent queries — async-first 架構讓 threads 永遠不 block 在 I/O 上，dispatch 完就走，callback 回來再接。這個設計完全打破了「concurrency ≈ thread count」的直覺。
>
> 用 Wondering 來讀： https://wondering.app/learn/netflix-real-time-distributed-graph-quer-370e7a16011a4b9e610b1059

連結：https://wondering.app/learn/netflix-real-time-distributed-graph-quer-370e7a16011a4b9e610b1059

### 2026-08-28 — Slack Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/Dcldi5zAggO)

> <Tech Blog 系列> Slack Engineering Blog
>
> Slack 跑了 200+ 次實驗，想搞清楚 AI agents 在測試裡到底該扮演什麼角色。
>
> 結論不是「agents 取代 E2E tests」，而是它根本就是另一回事。
>
> 五個重點整理和大家分享：

> 附上原文：
> https://slack.engineering/agentic-testing-where-agents-fit-in-the-e2e-testing-stack/
>
> 用 Wondering 來讀： https://wondering.app/learn/agentic-testing-where-ai-agents-fit-in-y-9a3e691e60643cd0318f2b2e
>
> 1. Tests enforce journeys，Agents verify goals
> 傳統 E2E test 寫死點擊路徑；agent 是給一個目標，自己觀察 UI 狀態、決定怎麼走。實驗裡 80% 的 agent runs 走了不同的操作路徑，但最後都到達同樣的結果。

連結：https://slack.engineering/agentic-testing-where-agents-fit-in-the-e2e-testing-stack/ ｜ https://wondering.app/learn/agentic-testing-where-ai-agents-fit-in-y-9a3e691e60643cd0318f2b2e

### 2026-08-30 — GitHub Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/Dcqm_RkgdXR)

> <Tech Blog 系列> GitHub Engineering Blog
>
> Coding agent 開好一個 PR，1,700 行的 diff，沒人敢 review。
>
> 這才是 AI 輔助開發真正的瓶頸。不是生成速度，是 review queue 塞住了。
>
> GitHub 的解法是 gh-stack，把 monolith PR 切成有依賴順序的 stack。
>
> 以 product search 功能為例，切成了 4 層：

> L1：先建 typed catalog + seed data。打地基，data owner 只需要看這層。
> L2：加 /api/products/search endpoint。純後端邏輯，backend reviewer 接手。
> L3：整合 chat API + grounding。對話邏輯獨立一層，不夾雜前後端。
> L4：最後加 UI components + citations。前端 reviewer 只需要看最上層。
> 每層有自己的 PR，每個 reviewer 只看自己熟悉的部分。
>
> 讀 stack 有個 pattern：從頂層讀下來了解全貌，從底層往上 review 確認實作。兩個方向各有用途。

### 2026-08-31 — Meta Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/DctJ9xSj692)

> <Tech Blog 系列> Meta Engineering Blog
>
> 「端對端加密」跟「偵測詐騙訊息」聽起來根本互相矛盾。
> WhatsApp 選擇同時做到這兩件事。做法是把 ML 推論完全搬到用戶的裝置上。
>
> 五層設計的細節如下：

> 1. On-device inference：ML 模型下載到裝置本地執行，訊息內容完全不離開裝置，WhatsApp server 從頭到尾看不到任何明文。
>
> 2. Differential privacy：就連「警告觸發了幾次」這種 aggregate 數字，離開裝置前也會加上校準過的隨機雜訊。數學上保證無法從 aggregate 資料推回個別使用者的行為。
>
> 3. TEE（Trusted Execution Environment）：aggregate 遙測資料在硬體隔離的執行環境中處理，連 Meta 工程師自己也無法檢視原始資料，OS 也無法干涉執行過程。

### 2026-09-01 — Spotify Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/DcvtilziDyC)

> <Tech Blog 系列> Spotify Engineering Blog
>
> Data lake 存著 exabytes 的資料，但每次查一個 user 的資料都要好幾秒，因為 Trino、BigQuery 這類 SQL engine 光 scheduling 就要幾秒，還沒開始讀資料。
>
> Spotify 工程師用 Random Access Parquet (RAP) 解決了這個問題，讓同一份 Parquet 檔案同時服務 batch analytics 和 online query。
>
> 七個重點整理：

> 1. 問題不在 GCS 速度
> GCS 單次請求 30–100ms，速度沒問題。瓶頸是 SQL query engine 的 scheduling overhead，即使只查一行資料，也要等好幾秒才開始讀。
>
> 2. External index 直接定位，不 scan
> Parquet 內建的 Bloom filter 只能說「這個 key 不在這裡」，沒辦法告訴你它在哪。RAP 的 external index 是 definitive 的：給定一個 key，直接回傳對應的 file ordinal 和 row numbers，完全跳過 scan。
>
> 3. Sort by key，讓同一 user 的資料連續
> 把資料按 key 排序，確保同一個 key 的 rows 集中在同一個 page 裡。一次 ranged read 就能拿到所有需要的資料，不用跨多個 page。

### 2026-09-04 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/Dc3iu_KjCVY)

> <Tech Blog 系列> Netflix Tech Blog
>
> Netflix 用自建的 Flink autoscaler 跑了好幾年，但它一直有個致命盲點：job 完全卡住，它卻看不出來。
>
> 問題不在程式碼，而在於它選的指標。
>
> 1. CPU 是個謊言
> 串流 job 卡住，最常見的原因是 backpressure 或 I/O，不是 CPU 過載。偏偏這類瓶頸對外部觀察者來說完全不可見——Netflix 的 autoscaler 就這樣一直被蒙在鼓裡。

> 2. 正確的訊號是 True Processing Rate（TPR）
> TPR = 觀測 throughput ÷ 實際做事的時間比例（busy fraction）。以 70% busy rate 處理 700 筆/秒的 operator，TPR 是 1,000 筆/秒，這才是真實容量。
>
> 3. 從外部觀察 vs. 從內部理解
> Netflix 自建版本在 container 外面看 CPU，OSS 版本從每個 subtask 的層級在 job graph 內部計算。同樣一個 job，兩套 autoscaler 的判斷可以完全不同。

### 2026-09-06 — Dropbox Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/Dc8rJsVjFgy)

> <Tech Blog 系列> Dropbox Tech Blog
>
> AI 時代資料量爆炸，大家直覺是擴充容量、買新設備。
> Dropbox 的做法是：先把現有 fleet 壓榨到極限，才考慮買新硬體。
>
> 他們做了四件事：

> 1. Deep Sleep
> 把閒置的 hard drive 調到 standby，或直接關掉整台 server。需要時幾分鐘內就能恢復。不需要「以備不時之需」就讓硬體一直跑著，待機成本幾乎是零。
>
> 2. Workload Balancing
> 持續監控整個 fleet 的資源分布，把工作搬到低使用率的機器。局部的 bottleneck 不會逼你擴充容量，重新分配資源就解決了。
>
> 3. SMR 硬碟
> Shingled Magnetic Recording 讓 track 互相重疊，比傳統 PMR 密度更高。同樣容量需要更少硬碟，連帶省下 cabling、電力跟冷卻。這技術在 blob storage（資料大多只寫一次）特別適用，因為 random write 慢的缺點在這場景幾乎不影響。
>
> 4. 用實際 failure rate 決定換機時機
> 不跟廠商的固定替換週期走，而是追蹤每年的實際故障率。能修就修，讓每台機器的壽命發揮到極致。

### 2026-09-15 — Netflix TechBlog
[原文](https://www.threads.com/@chunhao2026/post/DdT76cJiXqJ)

> <Tech Blog 系列>  Netflix TechBlog
>
> Netflix 最近分享了一個關於 cold start 的有趣案例，他們測了兩個獨立的優化方向，結果線上 A/B test 都各自失敗，但合在一起卻做出明顯的成效提升。

> As always, 附上 @wonderingapp 的連結
> https://wondering.app/learn/solving-cold-start-with-multimodal-embed-394e61756df9254b3676dcc2
>
> 1. Netflix 的個人化模型過去把每個 artwork/video preview 都當成一個不透明的 ID，只學「member 點了哪個」，卻看不懂圖片或影片裡實際的內容。新片剛上線時完全沒有互動數據，模型只能回退到「哪個最受歡迎就推哪個」，這是典型的 cold start 問題。
>
> 2. 他們提出兩個修法：第一是讓模型用 CLIP embedding「看懂」圖片內容，把視覺特徵直接接進 asset representation。第二是把過去分散在五種畫布尺寸（billboard、vertical-box、short-panel 等）、各自獨立訓練的模型合併成一個統一模型。

連結：https://wondering.app/learn/solving-cold-start-with-multimodal-embed-394e61756df9254b3676dcc2

### 2026-09-16 — Netflix Tech Blog
[原文](https://www.threads.com/@chunhao2026/post/DdWgWTbAHbz)

> <Tech Blog 系列> Netflix Tech Blog
>
> 有些 bug 只有在 production full scale 才會出現，unit test 跟小樣本完全抓不到。Netflix 一位工程師把「除錯」這件事本身重新設計成一套平行實驗系統，連飛機上斷斷續續的 wifi 都能拿來追進度。

> 一樣附上 @wonderingapp 的課程： https://wondering.app/learn/debugging-production-scale-spark-pipelin-ba1f3721343bfc577e07239d
>
> 你都是怎麼用 @wonderingapp 的？快和我分享！😁

連結：https://wondering.app/learn/debugging-production-scale-spark-pipelin-ba1f3721343bfc577e07239d

### 2026-09-17 — LinkedIn Engineering Blog
[原文](https://www.threads.com/@chunhao2026/post/DdZESpEAbCi)

> <Tech Blog 系列> LinkedIn Engineering Blog
>
> LinkedIn 最近重建了 Premium 產品線，把原本分散給中小企業主的 sales、marketing、hiring 工具整合成一個系統。有趣的是，真正的難題不在 AI 功能本身，而在底層的資料架構。

> 來用 @wonderingapp 來幫你閱讀更多技術文章！
>
> https://wondering.app/learn/how-linkedin-unified-ai-products-around-ca34549d772b5730b636a2e2
>
> 1. 問題其實是組織問題。Sales、marketing、talent 分屬不同部門，各自做了各自的 AI 功能，使用者得在三個不同介面之間切換，功能重疊但資料互不相通。
>
> 2. LinkedIn 沒有選擇「幫每個團隊多做一個 AI feature」，而是先定義一個共用的 Target Audience（TA）graph，讓所有下游功能都讀同一份資料，而不是三個團隊各養一份。

連結：https://wondering.app/learn/how-linkedin-unified-ai-products-around-ca34549d772b5730b636a2e2

## Tool（14）

### 2026-08-29 — ZooKeeper
[原文](https://www.threads.com/@chunhao2026/post/DcoDgCqk2w_)

> <Tool 系列>  ZooKeeper
>
> 很多工程師知道 Kafka 和 HBase 都依賴 ZooKeeper，但說不清楚它實際在做什麼。
> 這裡整理它在真實系統裡的五個核心使用場景。

> 附上學習來源： https://wondering.app/learn/zookeeper-for-engineers-the-5-core-use-c-9aa3adc4755c87c0a548d303
>
> 1. Distributed Configuration Management
> 把 config 存在 znode，client 設 watcher，config 一變就即時收到通知，不需要 polling。
> Kafka 就是靠這個讓 broker 即時收到 topic 設定的變更。
>
> 2. Leader Election
> 用 ephemeral sequential znode 實作選主：sequence number 最小的節點當 leader，
> leader 死掉後 node 自動消失、重新選舉自動觸發。
> HBase HMaster、Kafka controller broker 都是這樣選出來的。

連結：https://wondering.app/learn/zookeeper-for-engineers-the-5-core-use-c-9aa3adc4755c87c0a548d303

### 2026-09-02 — ElasticSearch
[原文](https://www.threads.com/@chunhao2026/post/DcyX7Bjgem5)

> <Tool 系列> ElasticSearch
>
> 五個你應該用 Elasticsearch 的場景，還有一個常見的誤區：

> 1. Full-text search
> Postgres 的 LIKE 查詢開始出現在 p99 的時候，就是 Elasticsearch 登場的時機。它的 inverted index 讓你在幾百毫秒內做 fuzzy match、autocomplete、多語言搜尋。
>
> 2. Log aggregation（ELK Stack）
> services 超過五個之後，SSH 進 pod 查 log 不夠用。把 log 透過 Filebeat 送進 ES，一個請求跨十個服務的 trace 可以在同一個畫面裡看完。
>
> 附上學習來源：
> https://wondering.app/learn/elasticsearch-for-engineers-top-5-use-ca-5fce3b8d1be886afbfb285dc

連結：https://wondering.app/learn/elasticsearch-for-engineers-top-5-use-ca-5fce3b8d1be886afbfb285dc

### 2026-09-03 — REST
[原文](https://www.threads.com/@chunhao2026/post/Dc03ESrAjaL)

> <Tool 系列> REST
>
> 設計 API 的時候，REST 到底代表什麼？
>
> 五個實際開發時重要的概念：

> 1. Stateless： 每個 request 都必須帶齊所有資訊，server 不記住任何 client 的狀態。這讓你可以水平擴展 server，任何一台 instance 都能處理任何請求，不需要 sticky session。
>
> 2. 資源用名詞，不用動詞： URL 代表的是一個「東西」，不是一個「動作」。/orders/123 是 REST 的思維；/getOrder?id=123 不是。設計 API 時先問自己：這個 endpoint 代表哪個 resource？
>
> 3. HTTP verb 對應操作： GET 讀取、POST 建立、PUT/PATCH 更新、DELETE 刪除。用對了 verb，API 就有一致性，client 不需要猜測對應的操作是什麼。

### 2026-09-05 — gRPC
[原文](https://www.threads.com/@chunhao2026/post/Dc6FAlljoKa)

> <Tool 系列> gRPC
>
> gRPC 不是「比較快的 REST」。加入新公司開始用它之後，才真正理解它在解決的是不同的問題。
>
> 3 個重點整理 + 4 點值得注意的地方：

> 1. 自動產生 type-safe 的 client/server stub
> .proto 檔是唯一的 API contract。跑一次 protoc，Go、Java、Python 的 client 跟 server stub 就全部自動生成。不用手寫 HTTP client、不用維護文件、不用擔心欄位名稱拼錯。API drift 直接變成 compile error，不會等到 production 才 raise error。
>
> 2. HTTP/2 multiplexing，一條連線做完所有事
> gRPC 強制要求 HTTP/2，不是 optional 的升級。gRPC 因為 HTTP/2，多個 request 可以在同一條連線上並行，header 還自動壓縮。微服務之間 call 量一高，少掉的 connection overhead 很可觀。

### 2026-09-07 — Docker
[原文](https://www.threads.com/@chunhao2026/post/Dc_O8UECIVV)

> <Tool 系列> Docker
>
> 開始用 Docker 的時候，最容易卡住的不是概念，是不知道該跑哪些指令。
>
> 整理了 5 個工程師每天都會用到的核心概念 + 對應指令：

> 1. Container 不是更輕的 VM
> 是共用 host kernel 的隔離進程。啟動幾秒內、大小比 VM 輕得多（MB 起跳 vs GB 起跳）。
> - `docker run postgres:15` — 幾秒起一個 Postgres，不用安裝、不污染本機
>
> 2. Image 是 layer 堆起來的
> 每一行 Dockerfile 指令都是一層 cache。
> `COPY package.json` 要放在 `COPY . .` 前面，不然每次改 code 都會重跑 `npm install`。
> - `docker build -t myapp .` — 建 image
> - `docker images` — 看所有 local image
>
> 3. Container 預設是短暫的（ephemeral）
> 不掛 volume 的話，container 被刪掉後裡面寫的資料就消失了。
> - `docker run -v $(pwd)/data:/var/lib/postgresql/data postgres`

### 2026-09-08 — Apache Flink
[原文](https://www.threads.com/@chunhao2026/post/DdBzS0qCbmA)

> <Tool 系列> Apache Flink
>
> 後端工程師必知的 5 個 Flink 應用場景，每個都有真實的 production 案例。

> 1. 即時詐欺偵測
> 同一張卡在紐約刷完，10 分鐘後又在倫敦出現。Flink 在 50ms 內偵測到這個 velocity anomaly，在授權完成前就觸發阻擋。傳統 batch job 最快也要 nightly report 才發現。
>
> 2. 即時 ETL / CDC Pipeline
> MySQL 的 orders table 更新，透過 Debezium + Kafka，1 秒內同步到 data warehouse。data analysts 不用等 2 小時的 batch window，dashboard 上看到的是真正即時的數字。
>
> 附上學習來源：https://wondering.app/learn/apache-flink-for-engineers-5-real-world-68b1aef72f7c3f14aa49a198

連結：https://wondering.app/learn/apache-flink-for-engineers-5-real-world-68b1aef72f7c3f14aa49a198

### 2026-09-21 — CDN
[原文](https://www.threads.com/@chunhao2026/post/DdjXMgwCQyi)

> <Tool 系列> CDN
>
> 我一直以為 CDN 就是拿來擋靜態檔案流量的快取層，直到最近重新梳理一次架構才發現，這個認知已經跟不上時代了。

> 1. Edge caching 不是重點，PoP 分布才是重點。Cloudflare 全球節點已經超過 330 個城市，代表原本要跨海才能拿到的內容，現在可能 <50ms 就到手，這才是真正在省的東西。
>
> 2. Origin offload 決定了你的服務在流量尖峰時死不死。cache hit ratio 到 95% 以上，代表尖峰流量真正打到 origin 的只剩 5%，其他都被邊緣接住了。
>
> 3. TTL 跟 purge 是兩套不同的武器。Cache-Control 決定平常的新鮮度，但真正改內容時要用 purge API 強制失效，而且要注意 purge 不是原子性的，全球節點不會同時生效，剛清完快取那幾秒還是有機會看到舊內容。
>
> 附上 @wonderingapp 連結： https://wondering.app/learn/cdn-for-engineers-beyond-static-caching-04dcefa25fa3847037d420c5

連結：https://wondering.app/learn/cdn-for-engineers-beyond-static-caching-04dcefa25fa3847037d420c5

### 2026-09-22 — JWT
[原文](https://www.threads.com/@chunhao2026/post/Ddl5BkJk0YA)

> <Tool 系列> JWT
>
> 微服務拆到 10 幾個 service 之後，你要怎麼讓每一個都知道「這個使用者是誰」，而不用每次都問一次 auth service？JWT 就是為了解決這件事而生的。
>
> 1. 核心價值是 stateless 驗證。signature 讓任何一個 service 都能在不查中央 session store 的情況下驗證身份，這在微服務規模下是巨大的效能跟解耦優勢。

> 2. 但 stateless 是把雙面刃。JWT 的結構是 header.payload.signature，payload 只是 base64url encode，不是加密。任何人拿到 token 丟進 jwt.io 就能直接看到內容，所以千萬別把敏感資料塞進 payload。
>
> 3. 為了縮小 token 洩漏的影響範圍，實務上會搭配 access token（短效，例如 15 分鐘）+ refresh token（長效但存放更謹慎，例如 httpOnly cookie）的組合。
>
> 4. 這也連到 JWT 最大的坑：revocation。因為是 stateless，你沒辦法在 exp 之前主動讓一顆 token 失效。使用者按下登出，很多時候只是前端把 token 刪掉，如果有人在那之前複製了 token，它依然有效。要解就得引入 blocklist 或壓縮 TTL，等於又把一部分 state 加回系統。
>
> 附上 @wonderingapp 連結： https://wondering.app/learn/jwt-78e3ddd0799145d267f9d984

連結：http://jwt.io/ ｜ https://wondering.app/learn/jwt-78e3ddd0799145d267f9d984

### 2026-09-24 — DNS
[原文](https://www.threads.com/@chunhao2026/post/DdrCqs6ExDc)

> <Tool 系列> DNS
>
> 你設計系統的時候有把 DNS 算進 load balancing 策略嗎？其實在請求連到你的 LB 之前，DNS 就已經做完第一輪的流量分配了。

> 1. DNS 本身就是一種 load balancer。Round-robin DNS、GeoDNS、weighted 或 latency-based routing（像 Route 53）能在「連到哪個 IP」這一步就做流量分配，比 application-layer LB 更早介入。
>
> 2. 解析鏈是 browser → OS → resolver → root → TLD → authoritative，每一層都會 cache。這也是為什麼大多數請求根本不會打到你的 authoritative server，都被前面的 cache 擋掉了。
>
> 3. Lookup 延遲是隱藏的效能成本。一次 cold lookup 可能吃掉 20-120ms，高頻 API 呼叫如果沒有重複利用 connection，重複做 DNS lookup 就是隱藏的效能殺手。
>
> 附上 @wonderingapp 連結： https://wondering.app/learn/dns-fd2af01faaa1f611f6c9f591

連結：https://wondering.app/learn/dns-fd2af01faaa1f611f6c9f591

### 2026-09-27 — Load Balancer
[原文](https://www.threads.com/@chunhao2026/post/Ddy0QJgDgOq)

> <Tool 系列> Load Balancer
>
> 設計系統的時候，load balancer 選 L4 還是 L7，其實不是「哪個比較好」，是「你要犧牲什麼換什麼」。

> 1. L4 只看 TCP/UDP 的 IP 跟 port，不解析封包內容，延遲低、吞吐量高，像 AWS NLB 這類 L4 LB 能撐到每秒數百萬個連線。
>
> 2. L7 能讀 HTTP header、URL path、cookie，依內容做路由決策，例如把 /api/* 跟 /static/* 導到不同後端群組，這是 L4 完全做不到的。
>
> 3. 選 L4 還是 L7，本質是效能跟靈活性的取捨：L4 快但笨，L7 聰明但要多花 CPU 去解析內容跟終止 TLS。

### 2026-09-28 — Database Index
[原文](https://www.threads.com/@chunhao2026/post/Dd1aIdrj2p9)

> <Tool 系列> Database Index
>
> 加 index 前先想清楚：這欄位值分佈夠不夠散？查詢會不會只用到部分條件？不然 index 可能白建，甚至讓寫入變慢。
>
> 1. 先看 cardinality：欄位唯一值夠不夠多才值得建 index。像 true/false 這種欄位建了 index 幾乎沒用，因為查詢結果還是要撈出表裡一大半資料，query planner 很可能直接放棄用它，改全表掃描。

> 2. 記得 index 是拿讀換寫，不是純加分。每次 INSERT/UPDATE/DELETE 都要同步維護每一個相關 index，掛越多 index，寫入越慢，一張表如果有 5 個 index，寫入吞吐量可能明顯下降。
>
> 3. 複合 index 要注意「最左前綴」規則。(a, b) 的複合 index，只用 b 當條件完全用不到，一定要從 a 開始查才吃得到，設計順序前先想清楚查詢會怎麼過濾。
>
> 4. 想省一次回表，就設計 covering index。如果 index 已經包含查詢需要的所有欄位，資料庫可以只讀 index 就回答完，不用再回原表撈資料，讀多的 query 效能差異很明顯。
>
> 5. 別忘了底層結構：大多數 index 是 B-tree，維持排序狀態讓查詢跟 range scan 都是 O(log n)。一張千萬列的表沒 index 要掃 1000 萬列，走 index 可能幾十次比較就找到。

### 2026-09-29 — ACID
[原文](https://www.threads.com/@chunhao2026/post/Dd39y-HkZ-T)

> <Tool 系列> ACID
>
> 討論「這個資料庫有沒有 ACID」之前，你應該先問一句：isolation level 設的是哪一種？因為同樣叫 ACID，不同 isolation level 對併發異常的容忍度完全不一樣。

> 1. Isolation level 才是真正決定「併發時會發生什麼」的旋鈕。多個並行 transaction 互相看不到對方還沒 commit 的中間狀態，但隔離的程度決定了能容忍多少種異常，像 dirty read、non-repeatable read、phantom read，都是 isolation level 沒設對才會出現的症狀。
>
> 2. 很多線上的併發 bug，其實不是「ACID 沒生效」，是 isolation level 設定不當。多數資料庫預設不是最嚴格的 SERIALIZABLE，而是像 READ COMMITTED 這種允許部分異常存在的等級，用預設值卻期待「完全不會有併發問題」，就是踩坑的起點。
>
> 3. Atomicity 保證的是全部成功或全部失敗，不是併發正確性。轉帳的扣款跟入帳只要一步失敗就整個 rollback，但這件事跟兩個併行的轉帳會不會互相干擾是完全不同的問題，靠的是 isolation，不是 atomicity。

### 2026-09-30 — Idempotency
[原文](https://www.threads.com/@chunhao2026/post/Dd6jueIAXb6)

> <Tool 系列> Idempotency
>
> 設計 retry-safe API 的時候，你需要的是 idempotency key。
>
> 1. 先確認：這個操作本身是不是 idempotent。「把餘額設成 100」重複執行結果不變，但「把餘額加 100」不是，重複執行餘額會一直增加。很多工程師會直接假設自己的 API 是 idempotent，卻沒真的檢查過。
>
> 2. HTTP method 的 idempotent 保證是規範定義的，不是自動發生的。GET、PUT、DELETE 依規範是 idempotent，POST 不是。直接把「timeout 就 retry」套用到 POST endpoint，卻沒額外處理，就是踩坑的起點。

> 3. 實務上用 idempotency key 補上這個保證。Client 幫每個邏輯操作生成一個唯一 key，跟著 request 一起送；server 記住 key 跟對應結果，同一個 key 再打一次，直接回傳上次結果，不會重複執行。
>
> 4. Stripe 的付款 API 就是最好的例子。POST request 要求帶 Idempotency-Key header，就是為了讓網路 timeout 後的重試不會導致重複扣款，這是設計 retry-safe API 時該學的具體做法，不是抽象概念。
>
> 5. 這件事在分散式系統裡更重要，因為 exactly-once delivery 幾乎是不可能的保證。message queue、retry 都是 at-least-once 為前提設計的，idempotency 是唯一讓「處理兩次」跟「處理一次」結果一樣的方法。
>
> 設計 API 前先問「這個操作重試安全嗎」，答案是否定的時候，idempotency key 就是你補上保證的工具，不是可選項。

### 2026-10-07 — Consistent Hashing
[原文](https://www.threads.com/@chunhao2026/post/DeMlV1mApSu)

> <Tool 系列> Consistent Hashing
>
> 設計分散式系統的 sharding 策略時，光用 consistent hashing 還不夠，virtual node 才是真正讓它均勻分佈的關鍵。
>
> 1. 先講清楚 consistent hashing 解決的問題：naive 的 hash(key) % N，只要節點數一變，幾乎所有 key 的歸屬都會跟著變。從 4 台加到 5 台，大約要搬 80% 的 key，這對 cache 是瞬間大量 miss，對分散式資料庫是大量資料搬移。

> 2. Consistent hashing 把節點跟 key 都丟到一個環上，每個 key 歸屬給「順時鐘方向第一個遇到的節點」。加或減節點，只影響環上緊鄰的那一小段，理論上只有大約 1/5 的 key 需要搬動。
>
> 3. 但只有這樣還不夠。一個實體節點在環上只放一個點，很容易分到特別長或特別短的區間，造成負載不均，這是實務上最容易被忽略的坑。
>
> 4. Virtual node 解決的正是這個問題。讓每個實體節點對應到環上多個虛擬點，把負載打散得更均勻，節點增減時的衝擊也更平滑。Amazon Dynamo 論文跟 Cassandra 都是用這個技巧。
>
> 5. 而且 consistent hashing 跟 virtual node 都只決定「這個 key 歸哪個節點」，不管複寫。資料要留幾份備份、怎麼保證持久性，是完全另一層要處理的問題，不要混在一起想。

連結：https://wondering.app/learn/consistent-hashing-virtual-node-0ec75ea28b07793107896079

## Comparison（12）

### 2026-08-13 — DynamoDB vs. Redis
[原文](https://www.threads.com/@chunhao2026/post/Db-8VaZE2I3)

> <Comparison 系列> DynamoDB vs. Redis
>
> Rate limiter 場景，Redis 低於 1ms，DynamoDB 幾個 ms。答案很明顯。後來要 cross-region replication 加上 GSI querying，答案換了。

> 1. Latency floor
> Redis 全在 memory，讀取通常低於 1ms。DynamoDB 的目標是 single-digit ms。多數場景差距可以忽略，但 fraud detection、real-time bidding、遊戲這種 latency 會 per-hop compound 的情況就差很多了。
>
> 2. Data structures
> DynamoDB 存的是 key-value 或 document item。Redis 內建 sorted set、bitmap、stream、pub/sub、HyperLogLog。Leaderboard 在 Redis 是 ZADD + ZREVRANGE 搞定，DynamoDB 要設計 GSI 加 sort key，ranking 邏輯還是不如 Redis 原生。

### 2026-08-14 — Write-Through vs. Write-Back Caching
[原文](https://www.threads.com/@chunhao2026/post/DcBlwN0D8ZX)

> <Comparison 系列> Write-Through vs. Write-Back Caching
>
> 選錯 cache 寫入策略，可能 crash 時資料丟失，也有可能資料庫被寫入壓垮。
>
> 兩種策略都落在 application 和 database 之間，差別只在於：database 什麼時候被更新。
>
> 留言附上學習來源。

> Write-Through 怎麼運作
> 每次寫入，資料同時寫進 cache 和 database，caller 要等兩邊都確認才拿到回應。Cache 和 database 永遠同步，即使 cache 掛掉，database 裡已經有完整的資料，不會丟 write。
>
> Write-Back 怎麼運作
> 寫入先進 cache，馬上回應 caller。Database 的更新是延遲的，由 background process 批次把 dirty entries flush 進去。寫入延遲低，但會有一個短暫的窗口，database 是落後的，如果 cache 在 flush 之前 crash，那些 writes 就消失了。

### 2026-08-15 — ZooKeeper vs. Redis
[原文](https://www.threads.com/@chunhao2026/post/DcD90GnARHo)

> <Comparison 系列> ZooKeeper vs. Redis
>
> 想實作 distributed lock，ZooKeeper 和 Redis 都能做到。但當你的 process 因為 GC 暫停了 30 秒，哪個 lock 還能撐住？
>
> 留言附上學習資源。

> ZooKeeper 怎麼運作
> ZooKeeper 有一個類似檔案系統的 tree structure，每個節點叫做 znode。要實作 distributed lock，所有競爭者都在同一個路徑下（例如 `/locks/my-lock`）建立 ephemeral sequential znode。
>
> - Ephemeral：這個 znode 跟著 session 存活。ZooKeeper 和每個 client 維持一個 heartbeat connection，client 一旦 crash 或斷線太久，session 過期後，ZooKeeper 會自動把它的 znode 刪掉，不需要 TTL，也不怕 clock drift。
> - Sequential：ZooKeeper 會幫 znode 加上單調遞增的序號，例如 `my-lock-0000000001`、`my-lock-0000000002`。

### 2026-08-15 — Redis vs. DynamoDB vs. MongoDB vs. Cassandra
[原文](https://www.threads.com/@chunhao2026/post/DcD_CTaidus)

> <Comparison 系列> Redis vs. DynamoDB vs. MongoDB vs. Cassandra
>
> 四個 database，一個標籤「NoSQL」，解決的問題卻幾乎完全不同。
>
> Redis 怎麼運作
> 把資料存在 memory 裡，用 sorted set、stream、string 等 typed structure 管理。每次操作都是 RAM lookup，這是它做到 sub-millisecond latency 的根本原因。
>
> DynamoDB 怎麼運作
> AWS 的 fully managed key-value + document store。設計階段就要定好 access pattern（partition key + sort key），DynamoDB 的效能保證建立在這個前提上。
>
> 先附上學習資源
> https://wondering.app/learn/nosql-database-selection-redis-dynamodb-17ce8edb7d704fa198c0941e 
>
> 讓你的學習歷程記錄在 Wondering 裡！

> MongoDB 怎麼運作
> 存 JSON-like document，有豐富的 query language 和 aggregation pipeline。Schema 是 flexible 的，同一個 collection 裡的 document 不需要有相同的 fields。
>
> Cassandra 怎麼運作
> Wide-column store，沒有 master node，所有 node 平等。Table design 是 query-driven 的：你為特定的 query path 設計 table，不是為了 entity。

連結：https://wondering.app/learn/nosql-database-selection-redis-dynamodb-17ce8edb7d704fa198c0941e

### 2026-08-16 — Polling vs. WebSocket
[原文](https://www.threads.com/@chunhao2026/post/DcGpgl3gN68)

> <Comparison 系列> Polling vs. WebSocket
>
> 選錯方向，不是讓 server 被空 request 每幾秒打一次，就是為一個每分鐘才更新的功能跑一整套 WebSocket 基礎設施。
>
> 留言附上學習資源。

> Polling 怎麼運作
>
> Client 定時問 server：「有新資料嗎？」Short polling 固定間隔發 HTTP request，不管有沒有資料都回應。Long polling 把連線撐著等，server 有資料才回應，client 立刻重連。兩者都是 stateless，任何 HTTP proxy 都能直接用，不需要額外設定。
>
> WebSocket 怎麼運作
>
> 從帶 Upgrade header 的 HTTP request 開始，握手後升級成持久的全雙工 TCP 連線。連線建立之後，任何一端都能隨時 push 資料，不用等對方先問。WebSocket frame header 只有 2–10 bytes，比一般 HTTP header 的 200–800 bytes 輕很多。

### 2026-08-16 — K8s vs. Docker
[原文](https://www.threads.com/@chunhao2026/post/DcGr2eTEvpO)

> <Comparison 系列> K8s vs. Docker
>
> 每個工程師都有那個時刻：Docker Compose 不夠用了，但 Kubernetes 看起來太重了。但這道題其實不只有兩個選項。
>
> Docker 怎麼運作：
> Docker 把 application 和 dependencies 封裝成 OCI container image。Docker Compose 在單台機器上管理多個 container，是本地開發的標準工具。但兩者都不是為 production orchestration 設計的。
>
> Kubernetes 怎麼運作：
>
> 附上學習來源：
> https://wondering.app/learn/kubernetes-vs-docker-when-to-use-each-ecff9d5960fbf8f8105e38d8

> Kubernetes 是功能最完整的 orchestration 平台，運行在 containerd 上（不是 Docker daemon，但你還是用 Docker 來 build image）。可以自己架，也可以用 managed 版本：AWS EKS、Google GKE、Azure AKS。強大、cloud-agnostic，但需要專門的 ops 能力。
>
> AWS ECS
> Amazon Elastic Container Service 是很多 AWS 團隊在換 K8s 之前會先評估的選項。定義好 Task Definition，ECS 負責 scheduling、scaling 和 failover，不需要自己維護 control plane。搭配 Fargate 可以做到 serverless container，連 infrastructure 都不用管。對已經在 AWS 上的團隊來說，ECS 常常是最省力的路。

連結：https://wondering.app/learn/kubernetes-vs-docker-when-to-use-each-ecff9d5960fbf8f8105e38d8

### 2026-08-20 — Temporal vs. Airflow 淺談
[原文](https://www.threads.com/@chunhao2026/post/DcQ6sx9greu)

> <Comparison 系列> Temporal vs. Airflow 淺談
>
> 工程師拿 Airflow 來「orchestrate workflows」，然後花好幾個月跟它搏鬥，因為 workflow 要跑幾天、要等外部事件、或是要從 crash 中途恢復。
>
> 這兩個工具在解不同的問題：

> 想更簡單 pick up 兩個工具的內容嗎？
> 來用 Wondering pick up 這些 tech stacks！
> https://wondering.app/learn/temporal-vs-airflow-choosing-the-right-w-16b022e378697133dd3211d0
>
> Temporal 怎麼運作
>
> Temporal 是 durable execution engine。你用一般程式碼（Go、Java、Python、TypeScript）寫 workflow，Temporal 保證它完成，就算 worker 在執行途中 crash 掉。每個步驟都記錄為 event log。Worker 在第 47 步死掉？Temporal 重播 event history，從中斷的地方繼續執行。

連結：https://wondering.app/learn/temporal-vs-airflow-choosing-the-right-w-16b022e378697133dd3211d0

### 2026-08-22 — Message Queue vs. Event Bus vs. Message Broker
[原文](https://www.threads.com/@chunhao2026/post/DcWMC_-iGCP)

> <Comparison 系列> Message Queue vs. Event Bus vs. Message Broker
>
> 曾經把這三個詞混著用，用了很久才搞清楚它們根本不是同一層的東西。整理一下，希望可以幫到同樣困惑的人。

> Message Queue 是一種溝通模式。Producer 發一條訊息，只有一個 Consumer 會收到並處理，ack 之後訊息消失。這個模式適合任務分發，多個 worker 同時拉任務，但每條訊息只被一個人處理一次。
>
> Event Bus 也是模式，但邏輯相反。Publisher 發出一個 event，所有 subscriber 都會收到一份副本，各自獨立處理。Publisher 不知道有誰在監聽，也不在乎，兩邊完全解耦。
>
> Message Broker 則是你實際部署的基礎設施，不是模式本身。它負責路由、持久化、重試。重點是：一個 broker 可以同時支援 queue 和 pub/sub 兩種模式，端看你怎麼設定。

### 2026-08-22 — Message Queue vs. Event Bus vs. Message Broker。曾經把這三個詞混著用，用了很久才搞清楚它們根本不是同一層的東西。整理一下，希望可以幫到同樣困惑的人。
[原文](https://www.threads.com/@chunhao2026/post/DcXCxeDCNTk)

> <Comparison 系列> Message Queue vs. Event Bus vs. Message Broker。曾經把這三個詞混著用，用了很久才搞清楚它們根本不是同一層的東西。整理一下，希望可以幫到同樣困惑的人。

> 近乎每天都發工程師的內容有點小累，之後還是會繼續發，但中間穿插一下廢文來舒緩一下。
>
> 鑒於這幾個月美國英國兩處跑，看了看照片也分不出這裡是哪裡，想說隨便讓大家猜猜這裡是哪裡好了！見留言選項。

### 2026-09-13 — Parallelism vs. Concurrency
[原文](https://www.threads.com/@chunhao2026/post/DdOrU_kCAtl)

> <Comparison 系列> Parallelism vs. Concurrency
>
> 很多工程師把 concurrency 跟 parallelism 當同義詞用,但這其實是兩個不同維度的問題,一個是「怎麼設計」,一個是「怎麼跑」。搞混這兩個,常常會在解決問題前就選錯工具。

> 用 @wonderingapp 來學看看吧！ https://wondering.app/learn/parallelism-vs-concurrency-for-engineers-7cc969e03a352ac784635ace 
>
> Parallelism 是真的同時執行:把工作切成獨立的小塊,分配到不同的 CPU core、GPU 或機器上跑。像影片轉檔、matrix multiplication 這類切得開、彼此獨立的 CPU-bound 工作,丟給多核心通常能拿到接近線性的加速。但像 model training 這種需要不斷同步梯度的分散式運算,核心或 GPU 一多,通訊開銷就會把效率往下拉,擴展性會被 Amdahl’s Law 限制,不是核心越多就等比例變快。

連結：https://wondering.app/learn/parallelism-vs-concurrency-for-engineers-7cc969e03a352ac784635ace

### 2026-09-18 — Sharding vs. Partitioning
[原文](https://www.threads.com/@chunhao2026/post/Ddbp_TODr8l)

> <Comparison 系列> Sharding vs. Partitioning
>
> 很多人把 sharding 跟 partitioning 當成同一件事，但嚴格來說，sharding 只是 partitioning 的其中一種形式，差別在於資料到底有沒有被分散到不同機器上。

> 如果你也剛好有用 @wonderingapp ，這裡附上課程！
> https://wondering.app/learn/sharding-vs-partitioning-when-to-use-eac-bcd9bbcf45ad313cf95a7796
>
> Partitioning 怎麼運作:
> 把一張大 table 拆成多個 partition，但全部都還在同一個 database instance 裡。查詢的時候 engine 會自動幫你 route 到對的 partition，對外看起來還是一張 table。像 Postgres 的 table partitioning，常見用法是按時間切，例如按月分 partition，舊資料要清掉時直接 DROP PARTITION，比跑一次大型 DELETE 快很多，也不會有額外的 VACUUM 負擔。
>
> Partitioning 適合的場景:
> - 單台機器還撐得住，只是查詢變慢或資料太肥
> - 需要快速清掉大量舊資料（時間序資料很常見）
> - 想要簡單維運，不想處理跨機器的一致性問題

連結：https://wondering.app/learn/sharding-vs-partitioning-when-to-use-eac-bcd9bbcf45ad313cf95a7796

### 2026-09-25 — TCP vs. UDP
[原文](https://www.threads.com/@chunhao2026/post/DdtrxzdjhYc)

> <Comparison 系列> TCP vs. UDP
>
> WebSocket、gRPC 選 TCP，視訊通話、線上遊戲選 UDP，這背後是一場「資料不能丟」跟「資料不能慢」的取捨。

> TCP 怎麼運作：傳資料前先三次握手建立連線，之後用 sequence number 排序、用 ACK 確認送達，沒收到就重傳，確保資料完整又依序抵達。這也是為什麼 gRPC（跑在 HTTP/2 上）跟 WebSocket 都選擇 TCP，一個掉包的 RPC 呼叫或聊天訊息不是體驗變差，是正確性 bug。
>
> TCP 適合的場景：
> - API 呼叫、RPC（gRPC）、WebSocket：掉一個封包是 bug，不是體驗變差
> - 銀行轉帳、檔案傳輸：任何需要精確重建 byte stream 的場景
> - 代價是 head-of-line blocking：HTTP/2 把多個 stream 多工在同一條連線上，但底層還是 TCP，一個封包丟失會讓所有 stream 一起卡住

## Small Quiz（8）

### 2026-08-25 — 不想當考考男，但還是想嘗試看看軟體工程師 quiz 系列。
[原文](https://www.threads.com/@chunhao2026/post/DccW3y7E7t0)

> <Small Quiz 系列>
>
> 不想當考考男，但還是想嘗試看看軟體工程師 quiz 系列。
>
> 四句話關於 HTTP，有一句是錯的。
>
> 你能找出來嗎？
>
> A. HTTP 是無狀態協議，每個請求之間互相獨立，server 不會記得你
>
> B. HTTP/2 支援 multiplexing，同一條 TCP 連線可以並行處理多個請求
>
> C. PUT 是冪等操作，呼叫多次結果相同；POST 不是
>
> D. HTTPS 會把你連線的網域名稱也加密，外部觀察者無法得知你在連哪個網站
>
> 答案留言告訴我 👇

> 最近在準備 AWS 雲端的證照(AWS SAA-C03)，原本秉持著「使用官方的文件和內容學習一定是最佳解」的心態，但用了官方的平台一陣子，發現學習體驗上不是很好，於是最後.....

> 自己在 @wonderingapp 上建了一套課程！
>
> 附上課程來源：
> https://wondering.app/learn/aws-certified-solutions-architect-associ-195980f3627c1510afe0116f
>
> 19 sections、65 堂課，把 4 個 exam domain 全掃過一遍，還對照官方 exam guide PDF 逐一確認有沒有漏掉的內容。
>
> 目前讀了 13 堂，覺得收穫滿滿，整個體驗上也很順暢。AWS 有太多服務，每個服務的內容又很雜，很常看到一個內容又要去查另一個詞。但使用 Wondering，不懂的地方可以直接問 AI，且問完在每個 lesson 的最後還會直接幫我整理筆記，這是我覺得最方便的地方。
>
> 本來想考到證照再和大家分享的，不過自己耐不住性子，還是先分享了。
> 等到考過了，也會再分享一次！ ✌️
>
> 好奇有在備考 AWS 的朋友，都是怎麼準備 AWS 的考試～

連結：https://wondering.app/learn/aws-certified-solutions-architect-associ-195980f3627c1510afe0116f

### 2026-08-26 — 四句話關於 database index，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/Dce7zlcEwVa)

> <Small Quiz 系列>
>
> 四句話關於 database index，有一句是錯的。
>
> 你能找出來嗎？
>
> A. 為欄位加 index 可以避免 full table scan，加速資料查詢
>
> B. 每次 INSERT、UPDATE、DELETE，database 都需要同步更新相關的 index
>
> C. Composite index (last_name, first_name) 可以加速只 filter last_name 的查詢
>
> D. 只要在 WHERE 條件的欄位加上 index，查詢速度一定會提升
>
> 答案留言告訴我 👇

### 2026-09-23 — 四句話關於 OAuth 2.0，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/DdobVfckeI3)

> <Small Quiz 系列>
>
> 四句話關於 OAuth 2.0，有一句是錯的。
>
> 你能找出來嗎？
>
> A. OAuth 2.0 是一個 authorization 框架，讓第三方應用可以存取使用者資源，而不需要知道使用者的密碼
>
> B. OAuth 2.0 本身是一個 authentication 協議，可以用來驗證使用者是誰
>
> C. Access token 有時效性；過期後，client 可以用 refresh token 重新換取，不需要使用者重新登入
>
> D. Authorization Code Flow 是 OAuth 2.0 中最安全的授權流程，適合有 backend server 的應用程式
>
> 投票告訴我 👇 隔天公布解答

### 2026-09-24 — 解答來了
[原文](https://www.threads.com/@chunhao2026/post/Ddrq9soiF_a)

> <Small Quiz 系列> 解答來了
>
> 答案是 B。
>
> OAuth 2.0 是 authorization 框架，不是 authentication 協議。它解決的是「授權第三方存取資源」，而不是「確認你是誰」。很多工程師把這兩件事混在一起，但這是兩個不同的問題。
>
> 要做 authentication，需要在 OAuth 2.0 之上加 OpenID Connect (OIDC)。OIDC 定義了 ID token 的格式（JWT）和 userinfo endpoint，才是真正用來驗證使用者身份的標準。
>
> 簡單記法：OAuth 2.0 回答「你可以做什麼」；OIDC 回答「你是誰」。

### 2026-10-02 — 四句話關於 async/await，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/Dd_pBZnjEj9)

> <Small Quiz 系列>
>
> 四句話關於 async/await，有一句是錯的。
>
> 你能找出來嗎？
>
> A. async/await 是 Promise 的語法糖，讓非同步程式碼讀起來像同步寫法，但底層仍然是 Promise
>
> B. async function 永遠回傳一個 Promise；就算 return 一個普通值，也會被自動包成 resolved Promise
>
> C. async/await 讓 JavaScript 可以真正平行執行多個任務，效果等同於開多個 thread
>
> D. await 會暫停目前 async function 的執行，但不會阻塞整個 JavaScript event loop
>
> 答案留言告訴我 👇 隔天公布解答

### 2026-10-03 — 四句話關於 Docker，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/DeCSKtnDN15)

> <Small Quiz 系列>
>
> 四句話關於 Docker，有一句是錯的。
>
> 你能找出來嗎？
>
> A. Docker image 是唯讀的；每次啟動 container，都是在 image 上疊一層可寫的 layer
>
> B. Docker container 提供跟 VM 相同等級的隔離，兩者都有獨立的 OS kernel
>
> C. 同一台 host 上的多個 container，預設可以互相通訊，除非用 network 隔開
>
> D. Container 比 VM 啟動更快，因為不需要 boot 完整的作業系統
>
> 答案留言告訴我 👇 隔天公布解答

### 2026-10-05 — 四句話關於 WebSocket，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/DeHbumuj3og)

> <Small Quiz 系列>
>
> 四句話關於 WebSocket，有一句是錯的。
>
> 你能找出來嗎？
>
> A. WebSocket 內建自動重連機制，連線中斷後會自動嘗試重新連接
>
> B. WebSocket 是 full-duplex 通訊，client 和 server 都可以主動推送訊息
>
> C. WebSocket 連線是透過 HTTP upgrade 握手建立的，初始請求是標準的 HTTP request
>
> D. 連線建立後，WebSocket frame 的 overhead 遠比 HTTP request 小，適合高頻率的訊息傳遞
>
> 答案留言告訴我 👇 隔天公布解答

> 解答來了
>
> 答案是 B。
>
> Container 跟 VM 的核心差別在於：container 共享 host 的 OS kernel，VM 則透過 hypervisor 跑自己獨立的 kernel。這也是為什麼 container 比 VM 輕量——不需要完整的 OS，只需要 process 層級的隔離。
>
> 這個差別有實際的資安意義：container 的隔離是由 Linux namespace 和 cgroups 實現的，若出現安全漏洞，攻擊者有機會突破到 host kernel；VM 的 hypervisor 層則提供更強的邊界。
>
> 簡單記法：VM 是隔壁棟，container 是同棟不同房間。

### 2026-10-12 — 四句話關於 REST API，有一句是錯的。
[原文](https://www.threads.com/@chunhao2026/post/DeZdS6ECLn1)

> <Small Quiz 系列>
>
> 四句話關於 REST API，有一句是錯的。
>
> 你能找出來嗎？
>
> A. REST 是一種 architectural style，不是協議或規範，任何遵循其原則的設計都可以稱為 RESTful
>
> B. RESTful API 使用 HTTP method 來表達操作意圖：GET 讀取、POST 建立、PUT/PATCH 更新、DELETE 刪除
>
> C. REST API 必須使用 JSON 格式回傳資料，這是規範的一部分
>
> D. REST 的 stateless 原則要求每個請求都帶齊所有必要資訊，server 不儲存 client 的 session 狀態
>
> 答案留言告訴我 👇 隔天公布解答

## Cross-domain（1）

### 2026-08-03 — Occam’s Razor 與系統設計面試
[原文](https://www.threads.com/@chunhao2026/post/DblMXqfCVj-)

> <Cross-domain 系列> Occam’s Razor 與系統設計面試
>
> 曾在系統設計面試直接開始畫架構圖。沒有需求，沒有假設，就這樣開始了。
>
> 頭腦裡塞滿 Kafka、sharding、CDN，全部混在一起，沒有一個站得住腳。設計失焦，最後沒拿到 offer。
>
> 最近學到 Occam’s Razor，又想到了這段經歷。
>
> Occam’s Razor：假設越少的解釋，通常越正確。每一個「也許我們需要這個」，都是一個新的 failure point。
>
> 那次面試，我一開頭就加了太多沒被驗證的假設，全部藏在設計裡，看不見，也沒辦法被挑戰。
>
> 而剛好這段故事也符合了 Occam’s Razor 的原則。
>
> 好奇你是不是也有類似的經驗呢？

> 附上學習來源：https://wondering.app/learn/the-great-mental-models-volume-1-8beo3t

連結：https://wondering.app/learn/the-great-mental-models-volume-1-8beo3t
