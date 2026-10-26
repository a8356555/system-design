# System Design 學習 Roadmap(整合版)

> 目標:把 repo 裡分散的 SD 資產(專案 README、推導筆記、DE 題庫、cs-fundamentals)整合成一條有順序的學習路徑,終點是 Google L4 / Meta E4 的 SD 輪水準。
> 核心原則:**pattern 先於題目,題目先於組件細節**——面試評的是決策過程,不是背架構圖。

## 資產地圖(你手上有什麼)

| 層 | 文件 | 角色 |
|---|---|---|
| 方法論 | [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md) | 陌生題的推導模板(naive → 哪裡爆 → 放寬 → primitive),全 repo 最重要的一份 |
| 題目地圖 | [question-map.md](question-map.md) | ~16 個經典題:考什麼、決策點、必背數字、高頻追問 |
| 共同 pattern | [cross-cutting-patterns.md](cross-cutting-patterns.md) | 12 類跨題知識點:併發寫入、一致性、idempotency、sharding、快取、fan-out⋯ |
| 組件深度 | [component-deep-dives.md](component-deep-dives.md) | Kafka/Redis/ZK-etcd/Cassandra/ES/S3⋯ 內部機制與失效模式 |
| 領域特化 | [domain-specific-mechanisms.md](domain-specific-mechanisms.md) | 35 條「沒見過就推不出」的 domain trick(GOP 切段、geohash、OT/CRDT、rolling hash⋯),每條附推導鏈 |
| 一手校準 | [eng-blog-reading-list.md](eng-blog-reading-list.md) | 46 篇官方 eng blog(8 domain × classic + recent),URL 全數驗證;每篇附「借什麼」 |
| 進階題庫 | [../../docs/de-system-design.md](../../docs/de-system-design.md) | 17 題 DE/ML 特化題 + 6-point rubric(你的差異化武器) |
| 實作參照 | `../*/README.md` 13 個專案 | 各題的具體實作參考(深度不一,question-map 已標注哪些值得讀) |
| 底層地基 | [../../docs/cs-fundamentals/](../../docs/cs-fundamentals/README.md) | 網路/OS/組織/安全 9 分冊——SD 答案的「為什麼」層 |
| 深挖筆記 | [../dcard-interview.md](../dcard-interview.md) | Lambda vs Kappa、一致性窗口、partition 推理(面試級深度的範本) |

## 學習順序(為什麼是這個順序)

```
Phase A: 方法論 + Pattern          Phase B: 題目掃描            Phase C: 組件深度
┌──────────────────────┐      ┌──────────────────────┐    ┌─────────────────────┐
│ handling-unfamiliar    │      │ question-map 16 題     │    │ component-deep-dives │
│ cross-cutting-patterns │ ───→ │ 每題 30min 心中過一遍   │ ──→ │ 按面試頻率讀          │
│ (推導能力 + 共用積木)   │      │ 挑 5 題寫完整 writeup   │    │ (答追問的彈藥)        │
└──────────────────────┘      └──────────────────────┘    └─────────────────────┘
         ↑ 併行                                                      ↑ 併行
   cs-fundamentals(底層 why)                              de-system-design 題庫(DE 特化)
```

先 pattern 後題目的理由:16 個經典題其實是 12 個 pattern 的排列組合(見 cross-cutting-patterns 檔尾的對照矩陣)。先會積木,每題只要學「這題特有的 twist」;反過來先背題,換個皮就答不出來。

組件放最後的理由:組件知識是「追問防禦」不是「開場白」。面試開場講架構用不到 ISR 細節;被追問「Kafka 掛一台會怎樣」才用到。先有架構語感,組件細節才掛得住。

## 6 週執行計畫(每週 ~4hr,可疊加 prep plan 的 SD 時數)

| 週 | 讀 | 練 |
|---|---|---|
| 1 | handling-unfamiliar-topics(重讀)+ cross-cutting-patterns 前 6 章(估算、併發寫入、一致性、idempotency、sharding、快取) | 用推導模板自己重推 flash sale 的 hot-row 三層解法,不看答案 |
| 2 | cross-cutting-patterns 後 6 章(fan-out、hot key、rate limiting、佇列、geo/ID、可靠性) | 手推 push vs pull 的成本數學(給定 1M DAU、平均 200 followers、1% celebrity) |
| 3 | question-map 群組 1-3(讀重寫輕、社交/Feed、媒體)共 9 題 | 挑 2 題寫 45min 計時 writeup(建議:Typeahead、YouTube),套 de-system-design 的 6-point rubric |
| 4 | question-map 群組 4-7(Geo、儲存/協作、交易、基礎設施)共 7 題 | 挑 2 題寫 writeup(**必選 Payment**——最大缺口 + DE 相關;另選 Rate limiter) |
| 5 | component-deep-dives:Kafka、Redis、ZK/etcd | 口頭回答每個組件的「保證與不保證」表;1 次 SD mock(用 question-map 隨機抽題) |
| 6 | component-deep-dives:Cassandra、ES、S3、RDB、Flink、ClickHouse + 全部 checklist 自測 | 1 次 SD mock;把答不順的 pattern 記回 [PROGRESS.md](PROGRESS.md) |

之後進入 prep plan Phase 3 的 mock 節奏時,de-system-design.md 的 DE-1~DE-12 接棒成為主練習題庫(那是你相對其他候選人的差異化面)。

## 面試當場的執行順序(SOP)

1. **釐清需求(5min)**:功能 3-5 條 + 非功能(規模、latency、一致性容忍)——非功能決定一切後續選擇
2. **容量估算(5min)**:QPS/storage/bandwidth 量級,只算會影響決策的數字
3. **高層架構(10min)**:先畫最無聊的可行版(LB → service → DB → cache),再逐步加料;每加一個組件說出「為了解決什麼」
4. **深挖 1-2 個決策點(15-20min)**:面試官引導往哪就往哪;這裡用 cross-cutting-patterns 的判準語言(「衝突率低所以樂觀鎖」「讀寫比 99:1 所以 cache-aside + 長 TTL」)
5. **失效模式收尾(5min)**:主動講「這個設計在 X 掛掉時會 Y,緩解是 Z」——這是 L4 → L5 的訊號

陌生題觸發 fallback:切到 handling-unfamiliar-topics 的 4 步推導模板,**把推導過程說出聲**——面試官評的就是這個。

## 與其他 track 的接點

- **DDIA**(prep plan Phase 2):Ch5-9 是 cross-cutting-patterns 一致性/sharding 章的理論底;讀完 DDIA 再回看 pattern 冊會「接起來」
- **cs-fundamentals**:SD 答案被追問「為什麼」時往下鑽的層——connection pool 大小(N1)、zero-copy 與 Kafka(O2)、backpressure(N3)、columnar 與 cache line(A1)
- **llama-serve 專案**:DE-11/DE-12/ML-4 + vLLM serving 是你面試時「我實際建過」的證據,SD 講到 streaming/observability 時主動連過去

## 維護

- 新學到的 pattern/踩坑 → 記進對應分冊,不要開新檔
- Mock 後的弱點 → 記進 [PROGRESS.md](PROGRESS.md) 的 Next steps
- 本 roadmap 的每週安排可依 prep plan 實際進度平移,順序不要動
