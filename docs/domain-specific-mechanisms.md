# 領域特化機制清單(Domain-Specific Mechanisms)

> 定位:[cross-cutting-patterns.md](cross-cutting-patterns.md) 收的是**可現場推導**的通用 pattern;本檔收的是**沒見過就推不出來**的領域 trick(你不可能現場發明 geohash 的編碼方式)。好消息:這類知識總量有限,本清單 35 條覆蓋面試 ~95% 的出現率——面試官自己也是從同樣的題庫學的。
>
> 用法:每條記的不是名詞,是**推導鏈**(naive → 哪裡爆 → trick 解什麼)。複習時遮住推導鏈,只看標題自測能否重講。沒做過的 domain 面試時誠實說「我從需求推導」,fallback 用 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) 的四步法——評分項本來就是推導過程。

---

## 一、影音(YouTube / Netflix / Twitch)

### 1. 影片切段(segmentation)

**推導鏈**:整檔傳輸 → 不能邊下邊播、不能跳看、斷線重來 → 切成 2-10 秒的 segment → 但影片壓縮靠幀間差分(P/B frame 參考前面的幀),隨便切的段開頭無法解碼 → 每段必須以 keyframe(I-frame)開頭 = **GOP(Group of Pictures)邊界對齊**。

**必記**:segment 長度 2-10s;GOP 邊界 = 可獨立解碼點;這是「拖進度條為什麼跳到附近而不是精確位置」的原因。

### 2. Encoding ladder(多畫質轉碼矩陣)

**推導鏈**:用戶設備與頻寬差異巨大 → 同一支影片要轉出 解析度 × bitrate × codec 的矩陣(240p→4K × H.264/VP9/AV1)→ 單機轉一支 4K 片要數小時 → 先切段,**各 segment 並行轉碼**,再合併 manifest = 轉碼是一個 DAG pipeline → 這就是上傳後「處理中」等幾分鐘的原因、也是「1080p 比 360p 晚出現」的原因(逐檔位完成逐檔位上架)。

**必記**:轉碼是 queue + worker pool 的批次系統,不在請求路徑上;Netflix 進一步做 **per-title encoding**(每支片依內容複雜度客製 ladder,動畫片低 bitrate 就夠)。

### 3. Adaptive bitrate(ABR)與 HLS/DASH

**推導鏈**:網路品質隨時變 → 誰決定切畫質?server 推測不準 → **決策放 client**:server 只提供 manifest(各畫質 segment 的 URL 清單),client 量自己的下載速度,逐段選檔位 → 這就是 HLS/DASH 的本體——影片串流其實是「client 連續 GET 一堆小檔案」,天然吃 CDN、天然可 cache。

**必記**:HLS/DASH 跑在普通 HTTP 上(這是它贏過 RTMP 的原因);畫質切換發生在 segment 邊界。

### 4. 直播 latency ladder

**推導鏈**:直播延遲來自「切段 + 緩衝」→ segment 越長延遲越高 → HLS 預設 ~10-30s → 縮段 + 部分傳輸 = LL-HLS ~2-5s → 要 <1s(視訊通話、連麥)只能放棄 HTTP 分段模型,用 **WebRTC**(UDP、P2P/SFU)→ 判準:**觀眾互動程度決定協定**,單向大規模直播用 HLS(便宜、吃 CDN),互動用 WebRTC(貴、要自建 SFU)。

### 5. CDN 預置(Netflix Open Connect)

**推導鏈**:影片流量佔 ISP 骨幹大宗 → 尖峰時段跨網傳輸又貴又塞 → Netflix 把 cache box 放進 ISP 機房,**離峰時段預推「明天預測會熱門」的內容** → 推薦系統的預測反過來變成 cache 策略。面試亮點:「熱門內容 pre-position、長尾內容 origin 拉取」一句話。

### 6. Resumable upload(大檔上傳)

**推導鏈**:2GB 影片單一 POST → 斷線全部重來、server 記憶體爆 → 切 chunk(如 5-10MB)逐塊上傳 + server 記錄進度 → 再想:為什麼要過我的 server?→ **presigned URL 直傳 object storage**,server 只發授權與收完成通知(連 [component-deep-dives.md](component-deep-dives.md) S3 章)。

---

## 二、URL / ID / 機率型資料結構

### 7. Short URL 的兩派生成法

**推導鏈**:要 7 碼短碼 → (a) **全域 counter + Base62 編碼**:不碰撞、但可預測(遍歷攻擊)且 counter 是單點 → 分段發號(每台領一段 range)解單點;(b) **hash(URL) 截前 7 碼**:無狀態、但生日悖論保證碰撞 → 查庫重試或加 salt。判準:量大且怕碰撞 → counter 派;要無狀態 → hash 派。

**必記**:62^7 ≈ 3.5 兆;讀寫比 ~100:1 → cache 是主角。實作參照 [../url-shortener/README.md](../url-shortener/README.md)。

### 8. Snowflake ID

**推導鏈**:分散式發 ID → UUID 隨機無序,B-tree 索引寫入四處分裂 → 要「趨勢遞增 + 無中心協調」→ **41 bit 時間戳 + 10 bit 機器 ID + 12 bit 序號** = 每機每 ms 可發 4096 個、按時間排序、可反解出生成時間。原推導見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md)。

**必記**:時鐘回撥是它的失效模式(拒發或等待);機器 ID 分配需要一次性協調(常用 ZK/etcd)。

### 9. Bloom filter

**推導鏈**:「這個 URL 抓過沒?」百億級 → 精確 set 記憶體存不下 → 容忍極小誤判換空間:k 個 hash 對 bit array 打點 → 答案只有「**一定沒有**」和「**可能有**」→ 適用:crawler 去重、cache penetration 防護(先問 bloom,一定沒有就不打 DB)。不能刪除(counting bloom 變體才行)。

### 10. HyperLogLog 與 Count-min sketch

**HLL 推導鏈**:算 UV(去重計數)→ 精確 set 太大 → 觀察 hash 值的前導零分佈可估基數 → KB 級記憶體估億級 UV,誤差 ~1%(Redis `PFADD`/`PFCOUNT`)。
**CMS 推導鏈**:找 top-k 熱門 → 全量 counter 存不下 → 二維 counter 陣列 + 多 hash,取最小值當估計(只會高估不會低估)→ trending、hot key 偵測(見 [cross-cutting-patterns.md](cross-cutting-patterns.md) hot key 章)。

### 11. Consistent hashing

**推導鏈**:`hash(key) mod N` → 加一台機器幾乎所有 key 重新分配 → 把 hash 空間做成環,key 順時針找最近節點 → 加減機器只影響鄰居 → 節點少時分佈不均 → **virtual nodes**(每實體節點掛數百個虛擬點)。完整推導在 [cross-cutting-patterns.md](cross-cutting-patterns.md) sharding 章。

---

## 三、Geo(Uber / Yelp / 外送)

### 12. 地圖細分三代

**推導鏈**:「找我 3km 內的司機」→ DB 對 lat/lng 各建索引再交集,效率差(二維查詢一維索引救不了)→ (a) 固定 grid:市中心一格百萬人、沙漠一格沒人 → (b) **quadtree**:密度高的格遞迴四分 → 記憶體內結構,分散式難 → (c) **geohash**:把經緯度交錯編碼成 base32 字串,**前綴相同 = 地理相鄰** → 變成一維字串前綴查詢,任何 KV/DB 都能索引。工業界變體:Google S2、Uber H3(六邊形,鄰格距離均勻)。

**必記精度表**:geohash 5 碼 ≈ 4.9×4.9km、6 碼 ≈ 1.2×0.6km、7 碼 ≈ 153×153m。

### 13. 邊界問題(9 宮格查詢)

**推導鏈**:目標站在 cell 邊緣 → 最近的司機可能在隔壁 cell,只查自己那格會漏 → **永遠查自身 + 8 個鄰格**再按實際距離排序。這是 geo 題必被追問的一題,答不出 9 宮格就是沒真懂。

### 14. Redis GEO

`GEOADD`/`GEOSEARCH` 底層 = geohash 塞進 sorted set(score 是 52-bit geohash)。適合司機位置這種**易失、高頻寫**的資料——掉了重建即可,不落 DB。

### 15. 高頻位置更新的讀寫反轉

**推導鏈**:百萬司機每 5-10s 回報位置 → 寫 QPS 遠大於讀 → 傳統「寫 DB、讀 cache」反過來了 → 位置只寫 memory store(Redis/自建 grid),**不持久化**;歷史軌跡另外 async 批次落 time-series 儲存(計費、審計用)。兩條路徑分開是這題的關鍵句。

---

## 四、協作 / 同步(Google Docs / Dropbox)

### 16. OT(Operational Transformation)

**推導鏈**:兩人同時編輯 → 整份文件上鎖不可用 → 傳「操作」不傳「內容」(insert/delete/retain + 位置)→ 但 A 在位置 5 插入時,B 已在位置 2 刪了 3 個字,A 的位置 5 已經不是原來的位置 5 → **transform 函數把對方操作造成的位移補償進來** → 需要中央 server 給操作定全序。Google Docs 用這套。實作在 [../google-docs-clone/README.md](../google-docs-clone/README.md)。

### 17. CRDT

**推導鏈**:OT 需要中央定序 → 離線編輯/P2P/多資料中心沒有中央 → 換思路:**設計數學上保證「任意順序合併都收斂」的資料結構**(每字元帶唯一 ID + 位置關係)→ 代價:metadata 膨脹、刪除要留墓碑。判準:**有中央 server + 線上為主 → OT;離線/去中心 → CRDT**(Figma 用類 CRDT、Notion 混用)。

### 18. Content-defined chunking(Dropbox delta sync 核心)

**推導鏈**:大檔改一個字要重傳整檔 → 切固定 4MB chunk,只傳變動的 chunk → 但在檔案**開頭**插入一個字,所有 chunk 邊界全部位移,還是全變 → **讓邊界由內容決定**:rolling hash 滑過檔案,hash 值命中特定 pattern 就切一刀 → 插入只影響局部 chunk。這是 rsync/Dropbox 的招牌,沒見過絕對推不出來。

### 19. Chunk-level dedup(秒傳)

**推導鏈**:很多用戶存同一份檔案/相同片段 → 按 **chunk 內容 hash** 定址儲存,全用戶共享 → client 上傳前先送 hash 清單問 server「哪些你已經有」→ 都有 = **秒傳**(只寫 metadata)。副作用要會講:hash 碰撞理論風險(SHA-256 實務可忽略)、加密後 dedup 失效的矛盾。

### 20. 離線衝突解決

**推導鏈**:手機離線改、電腦也改 → 同步時誰贏?→ (a) **LWW**(last-write-wins):簡單但默默丟資料 → (b) **version vector**:每副本一個計數器,能判斷「誰先誰後 vs 真併發」→ 真併發時交給策略(保留兩份如 Dropbox conflicted copy、或領域規則合併)。完整分類在 [cross-cutting-patterns.md](cross-cutting-patterns.md) 併發寫入章。

---

## 五、社交 / 訊息(Chat / Feed)

### 21. 訊息順序

**推導鏈**:全域時間戳排序 → 分散式時鐘不可信 → 其實不需要全域序,用戶只感知**單一對話內**的順序 → per-conversation 遞增序號(該對話的 partition/server 發號)→ 這也決定 sharding key 選 conversation_id。

### 22. Delivery states(sent/delivered/read)

**推導鏈**:「已讀」怎麼來的 → 三段 ack:server 收到(sent)→ 對方裝置收到(delivered)→ 對方開啟(read),每段都是一則反向 ack 訊息 → 群組場景 read receipt 是 O(成員數) 的寫放大,大群要降級(只存計數或關閉)。

### 23. Presence(在線狀態)

**推導鏈**:「掉線」不會主動通知(斷電、斷網)→ 只能反著做:client 定期 heartbeat + server 端 TTL,**過期即離線** → 大量好友的 presence fan-out 很貴 → 只推給「正在看著你」的人(開著對話窗才訂閱)。原推導見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md)。

### 24. Fan-out hybrid(celebrity 問題)

**推導鏈**:發文推給所有 follower(push)→ 千萬 follower 的名人一發文 = 千萬次寫 → 名人改為讀時拉取合併(pull)→ **一般人 push、celebrity pull,閾值 ~1 萬 follower**。成本數學在 [cross-cutting-patterns.md](cross-cutting-patterns.md) fan-out 章;實作參照 [../social-media-feed/README.md](../social-media-feed/README.md)。

---

## 六、搜尋 / 推薦

### 25. Typeahead(trie + 預存 top-k)

**推導鏈**:每敲一鍵查一次 → `LIKE 'prefix%'` + 排序,扛不住鍵入頻率 → trie 按前綴組織 → 但每次還要遍歷子樹排熱度 → **每個節點預存自己的 top-k 建議**,查詢 = 走到節點直接取,O(prefix 長度) → 熱度變化由離線批次重建/增量更新,「查詢路徑零計算,計算全部離線」是這題的中心句。

### 26. Inverted index 與 near-real-time

**推導鏈**:全文搜尋 → 正排(doc→words)要掃全庫 → 倒排:term → posting list(出現的 doc ID 列表)→ 查詢 = 取 posting list 做交集 → 為什麼新文件不能立刻搜到?寫入先進 in-memory buffer,**定期(refresh interval ~1s)才生成新 segment** = ES 的 near-real-time。細節見 [component-deep-dives.md](component-deep-dives.md) ES 章。

### 27. 推薦兩段式(recall → ranking)

**推導鏈**:對億級候選跑重模型 → 算不動 → **先 recall**(協同過濾/ANN 向量檢索,百萬 → 千,快而糙)**再 ranking**(重特徵模型,千 → 十,慢而準)→ 所有推薦/搜尋排序題的骨架,講出「兩段式 + 各段的 latency budget」就贏過大多數人。你的 DE 背景加分點:feature store 與 embedding pipeline 怎麼餵這兩段(連 [../../docs/de-system-design.md](../../docs/de-system-design.md) ML-1/ML-4)。

---

## 七、交易(Payment / 訂票 / 秒殺)

### 28. Idempotency key 閉環

**推導鏈**:扣款請求 timeout → client 不知道成沒成功 → 不重試會漏單、重試可能重複扣款 → client 生成唯一 key 隨請求送出,server 存 key→result 映射,同 key 直接回放結果 → 完整閉環要講齊:**key 的生成端(client)、儲存(帶 TTL 的表)、與 retry 策略綁定**。詳見 [cross-cutting-patterns.md](cross-cutting-patterns.md) idempotency 章、[question-map.md](question-map.md) Payment 條。

### 29. Double-entry ledger

**推導鏈**:直接 UPDATE balance → 出 bug 後無法追查、併發下丟更新 → 帳本**只 append 不 update**:每筆交易記借方+貸方兩條(和恆為零),餘額是 SUM 出來的 derived view → 效能不夠再加快照(checkpoint)。「餘額是 view 不是 state」是這題的中心句。

### 30. PSP webhook 處理

**推導鏈**:第三方支付(Stripe)以 webhook 通知結果 → 網路問題它會重送 = **at-least-once** → 處理端必須冪等(按 event ID 去重)→ 但 webhook 可能永遠沒來 → **定時對帳(reconciliation)**拉 PSP 的帳單比對,作為最後防線。「webhook 是優化,對帳是保證」。

### 31. Seat hold 與秒殺三層

**推導鏈**:選了座位付款中,別人能不能買?→ 鎖死到付款完成 = 惡意佔位 → **hold + TTL**(預留 10 分鐘自動釋放,Redis TTL 或 DB 過期欄位)。秒殺(庫存單一 hot row)三層破法:**入口削峰**(排隊頁/隨機丟棄)→ **Redis 原子扣減**(`DECR` 判負)→ **佇列序列化**(把併發變順序,DB 慢慢消化)→ 原則:寧可少賣不可超賣。原推導見 [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md)。

---

## 八、基礎設施

### 32. Rate limiter 演算法

四演算法(fixed window / sliding window counter / token bucket / leaky bucket)對照 + 分散式 Redis Lua 原子化——完整內容在 [question-map.md](question-map.md) 第 17 條與 [cross-cutting-patterns.md](cross-cutting-patterns.md) 第 9 章,此處不重複。**必記一句**:token bucket 最常用,因為它「允許合理突發 + 長期速率受控」。

### 33. Crawler 三件套

politeness(per-domain 佇列 + crawl-delay)、frontier(優先級 + 防單 domain 霸佔)、trap 偵測(深度上限 + URL pattern)——完整推導在 [question-map.md](question-map.md) 第 18 條。

### 34. Fencing token(分散式鎖的最後一塊)

**推導鏈**:拿鎖 + TTL → 持有者 GC pause 超過 TTL → 鎖被別人拿走,但原持有者醒來**不知道自己已失去鎖**,繼續寫入 = 兩個 writer → 鎖服務發**單調遞增 token**,儲存端拒絕比已見過更小的 token → 「TTL 解決死鎖,fencing token 解決殭屍持有者」。這是 Redis 鎖 vs ZK/etcd 鎖判準的核心(見 [component-deep-dives.md](component-deep-dives.md) ZK/etcd 章)。

### 35. Outbox pattern

**推導鏈**:業務寫 DB + 發 Kafka event → 兩個系統無法原子 → 先在**同一個 DB transaction 裡**把 event 寫進 outbox 表 → 由 poller/CDC 讀 outbox 轉發到 Kafka(at-least-once,下游冪等)→ 「用一個系統的原子性換兩個系統的一致性」。DE 面試高頻(CDC 題的孿生兄弟,連 [../../docs/de-system-design.md](../../docs/de-system-design.md) DE-1)。

---

## 自測方式與 checklist

**自測法**:遮住推導鏈,只看條目標題,口頭重講「naive → 哪裡爆 → trick」。講不出「哪裡爆」的就是還沒懂,只是記得名詞。

1. 影片為什麼要在 GOP 邊界切段?ABR 的畫質決策為什麼在 client?
2. Netflix 怎麼利用推薦預測做 CDN 預置?
3. Short URL counter 派和 hash 派各自的坑?62^7 是多少?
4. Snowflake 三段 bit 各解什麼問題?時鐘回撥怎麼辦?
5. Bloom filter 的兩種答案是什麼?HLL 和 CMS 各用在哪?
6. geohash 為什麼「前綴相同 = 地理相鄰」有用?為什麼要查 9 宮格?
7. 司機位置為什麼不落 DB?歷史軌跡走哪條路?
8. OT 的 transform 在補償什麼?OT vs CRDT 的判準?
9. rolling hash 切 chunk 解了固定 chunk 的什麼問題?秒傳怎麼做到的?
10. 群組已讀為什麼是寫放大?presence 為什麼只能用 TTL?
11. typeahead 的「計算全部離線」指什麼?
12. 推薦兩段式各段的規模與模型輕重?
13. 「餘額是 view 不是 state」什麼意思?webhook 和對帳的關係?
14. 秒殺三層各擋掉什麼?seat hold 的 TTL 解什麼?
15. fencing token 防的是哪種失效?outbox 用什麼換什麼?
