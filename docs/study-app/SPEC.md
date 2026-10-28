# 資料規格 — 系統設計決策學習頁

讀者：準備系統設計面試的軟體工程師（繁體中文，技術名詞保留英文）。
頁面的核心是「做決策」：每個主題都要讓讀者看完就能在面試中說出「我選 A 不選 B，因為…，代價是…，規模到 X 時會改用 C」。
**Tradeoff 與決策是重點，摘要是次要。** 每個選項都要寫清楚代價與失效方式，不可只寫優點。

來源（repo 根目錄 /Users/a8356555/Projects/alan/interview/system-design/docs/）：
- cross-cutting-patterns.md、component-deep-dives.md、domain-specific-mechanisms.md、question-map.md
- hellointerview-breakdowns/*.md（32 題案例；檔頭有「⚠️ Premium」者細節為整理者補充）
- hellointerview-learn/{in-a-hurry,core-concepts,patterns,deep-dives,in-the-wild}/*.md（patterns/ 全部與部分 core-concepts、deep-dives 標「🤖 by agents」= 非原文）
- threads-chunhao2026/tech-blog/*.md（15 篇 eng blog）、threads-chunhao2026/posts.md

規則：
- 內容必須出自上述來源；你自己補的判斷可以寫，但不要編造數字。數字只用來源裡出現過的。
- 文字精煉：一個欄位 1–3 句，不要段落文章。
- 輸出純 JSON（UTF-8），用 Write 寫檔，寫完用 `python3 -c "import json;json.load(open('<path>'))"` 驗證能解析。

## 主題 ID（固定，案例用來互相連結）
contention, consistency, multistep, idempotency, caching, scaling-reads, sharding, scaling-writes, realtime, fanout, async-jobs, streaming, blobs, search, geo, counting, rate-limiting, reliability, api-networking, auth, storage-choice, id-generation

## Schema A — topics（主題）
```json
[{
  "id": "contention",
  "title": "併發搶資源（Contention）",
  "group": "正確性 | 擴展 | 即時與非同步 | 資料與查詢 | 邊界與介面",
  "oneLiner": "一句話：這個主題在決定什麼",
  "question": "面試中觸發這個決策的典型問句，例如「兩個人同時搶最後一張票怎麼辦？」",
  "signals": ["看到這些需求/關鍵字就要想到這個主題", "..."],
  "options": [{
    "name": "選項名稱（例：DB 悲觀鎖 SELECT FOR UPDATE）",
    "how": "怎麼運作（1–2 句）",
    "bestWhen": "什麼條件下選它",
    "cost": "代價（延遲、吞吐、複雜度、成本）",
    "failure": "失效模式 / 會怎麼壞",
    "scale": "大約適用的規模或門檻（來源有數字才寫數字，否則寫定性描述）"
  }],
  "decisionGuide": [{"if": "條件", "then": "選擇", "why": "理由"}],
  "defaultAnswer": "面試時沒有特別要求下的預設選擇與一句理由",
  "interviewScript": "一段 2–4 句、可以直接在面試中說出口的論述，包含取捨",
  "pitfalls": ["常見錯誤 1", "..."],
  "cases": [{"name": "Ticketmaster", "ref": "hellointerview-breakdowns/ticketmaster.md", "note": "這題怎麼用這個決策"}],
  "sources": ["hellointerview-learn/patterns/dealing-with-contention.md"],
  "byAgents": false
}]
```
options 至少 3 個、最多 6 個，排列由簡單到複雜。decisionGuide 3–6 條。`byAgents`：主題內容若主要依賴標「🤖 by agents」或「Premium 補充」的來源，設 true。

## Schema B — cases（案例）
```json
[{
  "id": "ticketmaster",
  "title": "Ticketmaster",
  "kind": "面試題 | 業界實例",
  "source": "HelloInterview | HelloInterview Premium（補充） | In the Wild | Tech Blog",
  "file": "hellointerview-breakdowns/ticketmaster.md",
  "origin": "原文 URL（有就填）",
  "core": "一句話：這題/這個系統真正難在哪",
  "scaleNumbers": ["來源中的關鍵數字，例：10M 並發用戶"],
  "decisions": [{
    "decision": "要決定的事",
    "chosen": "最後選擇",
    "rejected": [{"option": "被否決的選項", "why": "為什麼不選"}],
    "tradeoff": "選擇的代價 / 什麼情況下會改變決定"
  }],
  "topics": ["contention", "realtime"],
  "followUps": ["面試官常追問 + 一句答案"]
}]
```
decisions 3–5 個。topics 只用上面的主題 ID。

## Schema C — components（元件速查）
```json
[{
  "id": "kafka",
  "name": "Kafka",
  "category": "訊息/串流 | 儲存 | 快取 | 搜尋 | 協調 | 流程 | 閘道",
  "what": "一句話定位",
  "guarantees": ["它保證什麼"],
  "notGuaranteed": ["它不保證什麼（面試常踩）"],
  "useWhen": ["..."],
  "avoidWhen": ["..."],
  "numbers": ["來源中的量級數字"],
  "gotchas": ["失效模式 / 進階考點"],
  "vs": [{"name": "替代品", "pickIf": "什麼情況選替代品"}],
  "file": "hellointerview-learn/deep-dives/kafka.md",
  "byAgents": false
}]
```

## Schema D — quiz（自測）
```json
[{"q": "問題", "a": "簡短答案（含理由）", "topic": "主題 ID", "kind": "概念 | 取捨 | 數字 | 情境"}]
```
「取捨」與「情境」類題目要佔一半以上（例：「讀多寫少、可容忍 1 分鐘舊資料，cache 失效策略選什麼？為什麼不選 write-through？」）。

## Schema E — mechanisms（領域機制：某個應用才會用到的具體技巧）
檔案格式：`{"mechanisms": [...], "quiz": [...]}`（quiz 用 Schema D，topic 欄位填下面的 domain id）。
```json
{
  "id": "per-title-encoding",
  "domain": "video",
  "apps": ["Netflix", "YouTube"],
  "title": "Per-title encoding：每支影片自己的畫質階梯",
  "naive": "直覺做法：所有影片套同一組解析度 × bitrate（固定 encoding ladder）",
  "breaks": "哪裡會壞：動畫用太多 bitrate 浪費頻寬，動作片在同 bitrate 下馬賽克",
  "trick": "實際做法：先試編碼分析複雜度，替每支影片挑出品質曲線上的最佳點",
  "cost": "代價 / 取捨：多一輪分析編碼的運算成本；只在觀看次數高的內容划算",
  "alternatives": [{"name": "固定 ladder", "pickIf": "內容量大但每支觀看少（UGC 長尾）"}],
  "numbers": ["來源中出現的數字才寫"],
  "interviewUse": "面試中什麼時候提、怎麼一句話帶出",
  "sources": [{"title": "Per-Title Encode Optimization", "url": "https://netflixtechblog.com/..."}],
  "topics": ["blobs"],
  "byAgents": true
}
```
- domain id：video, maps, connections, recsys, moderation, data-pipeline, deploy-migration, observability, classic（classic = repo 既有 domain-specific-mechanisms.md 的條目）
- 每條一定要綁定具體應用（apps），寫「這個產品實際怎麼做」，不要寫成泛用原則。
- sources：至少 1 個可公開存取的 URL（官方 eng blog、官方文件、論文、知名演講）。必須是你用 WebFetch / WebSearch 實際看過的頁面，不可憑記憶編 URL。
- 數字只寫來源中出現的；你自己的判斷可以寫在 cost / interviewUse。
- topics：對應 22 個主題 ID 中相關的 0–3 個。

## Schema E 補充規則（第二批起適用）
- numbers：只放你**實際打開的頁面**裡出現的數字。只在 WebSearch 結果摘要、或二手轉述文章裡看到的數字，一律不放（不要放進來再標「二手」）。
- apps：只掛來源證實「這家公司真的這樣做」的產品名稱；通用做法就寫技術或標準名稱（例如 "FIX protocol"、"MQTT"），不要掛示意性公司名。
- 403 / 擋自動抓取的網站：**不要繞過**（不用 Wayback 或其他鏡像去讀被擋的頁面）。直接跳過，換另一個可讀的一手來源；不要用內容農場或 vendor 行銷文當主要來源。
- 每條 sources 優先順序：官方 eng blog / 論文 / RFC / 官方文件 > 知名技術媒體（InfoQ、ACM Queue）> 其他。
- 每條都要有清楚的取捨：cost 至少點出一個「什麼情況下這招不划算」。

## Schema F — incidents（真實事故與解法：從公司技術部落格學）
檔案格式：`{"problem": "<type id>", "incidents": [...], "quiz": [...]}`（quiz 用 Schema D，topic 填 type id）。
```json
{
  "id": "roblox-2021-consul-outage",
  "problem": "cascading-failure",
  "company": "Roblox",
  "title": "73 小時停機：Consul streaming 與 BoltDB 效能退化",
  "date": "2021-10",
  "kind": "postmortem | design-writeup",
  "symptom": "使用者 / 指標看到什麼（例：全站無法登入、P99 從 X 升到 Y）",
  "rootCause": "根本原因（技術細節，1–3 句）",
  "whyHard": "為什麼難：直覺解法為何無效、問題怎麼擴大或為什麼難診斷",
  "fix": "止血做法 + 長期修正",
  "tradeoff": "修正方案的代價 / 什麼情況下不適用",
  "lessons": ["可遷移到其他系統的教訓，1–3 條"],
  "numbers": ["只放實際打開的頁面裡的數字"],
  "interviewUse": "面試中可以拿來支撐什麼論點（一句話）",
  "sources": [{"title": "...", "url": "..."}],
  "topics": ["reliability"],
  "byAgents": true
}
```
問題類型 id：tail-latency, cascading-failure, overload, cache-hotspot, db-scaling-migration, change-induced, multi-region-dr, capacity-peaks
（審查 agent 可能再提議新增類型）

規則（與 Schema E 補充規則相同）：
- 每條至少 1 個**實際打開讀過**的來源 URL；只看過搜尋摘要不算。
- 網站擋自動抓取（Medium 系 403、Uber 406 等）時，**不要繞過**（不用 Wayback / 鏡像），直接換其他可讀的一手來源，或不收這篇。
- 數字只寫實際讀到的頁面中出現的；不放搜尋摘要或二手轉述的數字。
- company 必須是事故 / 文章的主角；不要把通用做法掛在示意性公司名下。
- 同一個事件只寫一次（若跨類型，放最主要的類型，lessons 裡提另一類）。
- topics 用 22 個主題 ID 中相關的 1–3 個。

## Agent 系統設計區（2026-10-28 起）
來源：`sources/agent-sources.json`（137 筆，已驗證可開）與 `sources/agent-review.json`（主題、失敗分類、面試題）。寫作時**必須自己再用 WebFetch 打開**你引用的頁面，數字只取你讀到的原文；搜尋摘要、二手轉述的數字不放。擋自動讀取的網站不要繞過（不用 Wayback / 鏡像 / 轉載站）。

### 主題 ID（14 個，group 一律填 "Agent 系統設計"）
agent-vs-workflow, orchestration, planning-reflection, agent-comm, context-memory, tool-interface, retrieval-strategy, long-running-async, agent-reliability, agent-eval, agent-safety, agent-permissions, agent-cost-latency, agent-deploy-versioning
- 邊界：orchestration = 控制流（誰決定下一步）；agent-comm = 資料流（傳什麼、怎麼傳、共享狀態、平行 agent 衝突）；agent-safety = prompt injection / guardrails / human-in-the-loop；agent-permissions = 身分、最小權限、sandbox、多租戶；agent-cost-latency 含模型選擇與 fallback。

### 主題檔：Schema A，檔案格式 `{"topics": [...], "quiz": [...]}`
- topics 照 Schema A；`cases[].ref` 填 `"agent-case:<案例 id>"`（案例 id = agent-sources.json 裡 type 為 case-study 的 id），`sources` 填 URL。
- options 3–6 個，每個都要寫 cost 與 failure；`scale` 沒有原文數字就寫定性描述。
- quiz：每個主題至少 3 題 Schema D，「取捨」「情境」類佔一半以上，topic 填主題 ID。
- byAgents 一律 true（內容由 agents 整理自外部來源）。

### 案例檔：Schema B，檔案格式 `[...]`
- `id` = agent-sources.json 的 source id；`kind` = "業界實例"；`source` = "Agent Case Study"；`file` = ""；`origin` = 原文 URL（必填）。
- decisions 3–5 個，每個要寫被否決的選項與理由；文章沒講否決理由時，rejected 可寫業界常見替代方案，但 why 要標「（補充）」。
- topics 用上面 14 個 agent 主題 ID（也可加原本 22 個主題 ID）。

### 失敗事件：Schema F，檔名 `data/inc-agent-*.json`
- problem id 用 agent- 開頭，檔案加 `"problemName": "Agent：<中文名>"`。
- 研究型失敗分析（如 MAST）不是事故，不放這裡，放 readings。
- 只收真實發生、有可讀一手或可信二手來源（官方 postmortem、AI Incident Database、資安研究者原文）的事件；kind 用 "postmortem"、"incident-report"，研究或內部實驗用 "experiment"（頁面標「實驗環境」）。

### Schema G — readings（論文 / 指南導讀），檔案 `data/agent-readings.json` = `[...]`
```json
{
  "id": "mast-why-mas-fail",
  "type": "paper | guide | blog",
  "org": "UC Berkeley",
  "title": "Why Do Multi-Agent LLM Systems Fail?",
  "url": "https://arxiv.org/abs/...",
  "date": "2025-03",
  "claim": "一句話：這篇最重要的主張",
  "keyPoints": ["2–4 條重點，含它的方法或分類"],
  "numbers": ["只放原文讀到的數字"],
  "designTakeaway": "對設計 agent 系統的具體啟示（要寫成取捨或決策）",
  "caveat": "限制 / 不該過度引用的地方（例：只測某個 benchmark、廠商自評）",
  "topics": ["orchestration"]
}
```
