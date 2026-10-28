# Progress — system-design interview prep

**Last updated:** 2026-10-28
**Branch:** docs/system-design-study-notes

## Completed
- [x] 2026-10-28 學習頁新增「Agent 系統設計」區(artifact Version 6):14 個決策主題(64 題自測)、32 篇 agent 上線案例(20 家公司)、18 篇 agent 失敗事件(5 類,含標「實驗環境」的研究實驗)、55 篇論文與指南導讀(#read)。來源清單 sources/agent-sources.json(137 筆)、分類審查 sources/agent-review.json;數字核對:47 筆 not_found 經 reviewer 判定 42 supported / 3 wrong 已改 / 3 unsupported 已刪(含圖表才有的數字);Uber 三篇擋 curl → 標數字未核對
- [x] 2026-10-28 Wayback / 轉載內容決定保留並加標示(選 A);study-app 10 條加 accessNote、5 篇 Netflix 筆記加檔頭註記(commit 2ac1168)
- [x] 2026-10-28 Dcard 分支誤推的 commit 以 git revert 抵銷(135af3d,一般 push),檔案內容回到 b16726a
- [x] Google-related system notes
- [x] Data-intensive app notes (DDIA)
- [x] Data-intensive app — Flink notes
- [x] Dcard interview: Kappa / Lambda architecture notes
- [x] Discussion: strategy for unfamiliar topics in system design interviews — saved to [handling-unfamiliar-topics.md](handling-unfamiliar-topics.md)
- [x] 2026-09-09 教學文件四件套(agent team 產出):
  - [question-map.md](question-map.md) — 19 個經典題地圖(考什麼/決策點/必背數字/高頻追問/repo 資源);payment、ticket booking、rate limiter、crawler 等原缺口題已補足
  - [cross-cutting-patterns.md](cross-cutting-patterns.md) — 12 類跨題 pattern(併發寫入分類法、一致性譜系、idempotency、sharding/consistent hashing、快取、fan-out、hot key、rate limiting、佇列/backpressure、geo/ID、可靠性)≈ 原 Next-steps 的 building-blocks cheat sheet,已含 when-NOT-to-use 判準
  - [component-deep-dives.md](component-deep-dives.md) — 9 組件內部機制/保證與不保證/失效模式(Kafka ISR、Redis、ZK-etcd/Raft、Cassandra/LSM、ES、S3、RDB、Flink、ClickHouse)+ 選型速查表
  - [study-roadmap.md](study-roadmap.md) — 資產地圖 + pattern→題目→組件的 6 週執行計畫 + 面試當場 SOP
- [x] 2026-09-09 [eng-blog-reading-list.md](eng-blog-reading-list.md) — 46 篇官方 eng blog(8 domain,classic + recent),4 個蒐集 agent 每條 URL 以 WebFetch 驗證(Netflix Medium 系用 Wayback 快照替代驗證);主 session 另抽查 5 條 curl 200。擋爬未收名單(DoorDash/Lyft/Debezium/Netflix rec)已在各節註明
- [x] 2026-09-09 [domain-specific-mechanisms.md](domain-specific-mechanisms.md) — 35 條領域特化機制(8 個 domain,每條附「naive → 哪裡爆 → trick」推導鏈 + 15 條自測);定位:patterns 冊收可推導的,本冊收沒見過推不出的
- [x] 2026-10-18 [hellointerview-breakdowns/](hellointerview-breakdowns/README.md) — Threads @chunhao2026〈System Design Interview 系列〉→ Hello Interview 全 32 題 breakdown,每題一檔 + README 總表與 17 條跨題 pattern 對照
  - Threads 未登入只抓到最新 3 篇(WhatsApp / Tinder / GitHub App JWT),觀點寫在各檔開頭;更早貼文需登入才抓得到
  - 16 篇 Premium 僅需求+大綱,deep dive 解法為 agent 補充(檔內標註),可信度低於免費篇
- [x] 2026-10-19 [hellointerview-learn/](hellointerview-learn/README.md) — Hello Interview 其餘 5 分類 43 篇(In a Hurry 6 / Core Concepts 9 / Patterns 7 / Deep Dives 15 / In the Wild 6),README 總表 + 閱讀順序
  - 免費 29 篇照原文;Premium 14 篇依大綱由 agents 撰寫,檔內標「🤖 by agents」;參考連結 56 條已確認 HTTP 200,內容未逐條比對
  - In the Wild 6 篇已補回原始 eng blog URL
- [x] 2026-10-19 [threads-chunhao2026/](threads-chunhao2026/README.md) — 作者全部 270 篇貼文(使用者登入收集連結 + urllib 腳本抓全文);posts.md 收系統設計相關 64 組原文;tech-blog/ 15 篇 eng blog 找回原文整理(6 篇直接讀到原文、5 篇經 Wayback 核對、3 篇只有轉載、1 篇找不到);2026-10-24 補收連結預覽卡(22 篇貼文補到連結,無新 eng blog)與 6 篇新貼文
- [x] 2026-10-19 skill `harvesting-threads-posts`(~/.claude/skills/)— Threads 收集/抓取/追連結/agent 整理流程 + collector.js / fetch_posts.py / html_to_text.py
- [x] 2026-10-24 [study-app/](study-app/index.html) — 系統設計取捨學習頁:22 個決策主題(選項 × 適合/代價/會壞/規模 + 決策指引 + 面試說法)、53 案例(選擇 vs 不選)、247 條領域機制(2026-10-25 兩批共 19 個領域:影音、地圖、連線、推薦、審核、資料管線、部署遷移、觀測性、撮合、遊戲、音訊、協作、外送、廣告、Email、支付、搜尋引擎、IoT + 原 35 條轉換)、125 篇真實事故(2026-10-26:14 類問題、59 家公司,來自 99 家技術部落格清單 study-app/sources/companies.json;數字逐一回原文核對)、17 元件、278 題自測;已發布 https://claude.ai/artifact/GB7tGPy3DZFUzECkMuycu4 。改資料後在 study-app/ 跑 `python3 build.py` 重建

## In progress
- [ ] Threads 長貼文補齊:需使用者登入後在 /@chunhao2026/replies 跑收集腳本,補抓接續留言後重建 posts.md 與 tech-blog「作者的解讀」

## Next steps
- [ ] 每週技術部落格掃描 routine:待使用者 /web-setup 連 GitHub 並確認設定(週一 09:00、Sonnet 5.5、開 PR)
- [ ] Practice re-deriving the 10 examples from scratch (cover the derivation chain, derive, then check)
- [ ] 按 study-roadmap.md 的 6 週計畫執行;W3-4 的計時 writeup 必選 Payment(原最大缺口)
- [ ] Mock 後的弱點記回本檔
- [ ] Premium 16 題當練習題:先自推再對照補充解;有需要再登入 Threads 補抓舊貼文
