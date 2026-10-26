# System Design in a Hurry：Introduction
> 來源：https://www.hellointerview.com/learn/system-design/in-a-hurry/introduction ｜ 分類：in-a-hurry

## 一句話重點
System design 面試考的是「把模糊的大問題拆解成基礎設施元件、權衡 trade-off、清楚溝通」的能力，不是找唯一正解；課程從「面試需要什麼」倒推內容。

## 核心內容
### 什麼是 system design interview
- 評估能否把「定義模糊的高層問題」拆成所需的基礎設施元件；偏實務，比 leetcode 更接近真實工作。
- 重點不在單一正解，很多題有多個正確答案；面試官看你如何處理複雜問題、推理 trade-off、清楚表達。
- 層級：entry-level 多半沒有；mid-level 開始常見；senior 是常態且權重極大。

### 面試類型
- 絕大多數是 Product Design / Infrastructure Design（如「設計 Uber」「設計 rate limiter」），需要 services、load balancer、DB 等 → 本指南針對此類。
- 其他：Low-Level Design（OOD，類別結構）、ML System Design（模型、feature engineering）、前端設計面試（原文推薦 Great Frontend）。

### 評分四大主題（各家用詞不同，但主題一致）
| 能力 | 面試官看什麼 | 常見失敗方式 |
|---|---|---|
| Problem Navigation | 拆解模糊問題、排優先順序、持續推進；最重要也最多人卡關 | 需求探索不足；聚焦瑣碎處而非關鍵；卡在某一塊走不動；沒交付可運作的系統 |
| Solution Design | 每個子問題怎麼解、如何組成一體；用 Core Concepts | 核心概念不足；忽略 scaling/performance；「spaghetti design」 |
| Technical Excellence | 熟悉現行技術、best practice、能套用到題目 | 不知道有哪些技術；用過時做法/過時硬體限制；不會套用；不認得常見 pattern |
| Communication & Collaboration | 像同事一樣合作：講清楚複雜概念、接受回饋 | 講不清楚；被質疑就防禦/爭辯；迷失在細節 |

- 所有人都要完成滿足需求的完整設計；mid-level 把基礎做好、深度較淺；senior 快速帶過基礎，把時間留給 deep dive 展現深度。
- 面試官會警覺「背答案」的人，會用質疑、追問 trade-off 來測試。
- Staff+ 另有不同做法（原文有 Staff-Level System Design 專文）。
- 多數人卡關的原因是缺乏結構 → 用 Delivery Framework。

### 如何使用本指南
- 依序讀，已會的可跳過；先 How to Prepare。盡量自足，不必讀延伸材料。
- 一定要練習：常見失敗是「讀很多但實戰卡住」。有 worked solutions 與 Guided Practice；穿插 quiz。
- 準備時間：完全新手專注投入或分散 3-4 週；已有基礎者有人不到一週就準備好。
- 可請 recruiter 延後面試日期（多數公司寧願你通過率高）。
- 時間極少：先讀 Delivery Framework → 略讀 Key Technologies → 剩下時間讀 Core Concepts。

## 面試怎麼用
- 開場就用結構（Delivery Framework）避免失去方向；把「交付可運作系統」放第一。
- 避免講超出面試範圍的深度（原文提到那可能是 yellow flag）。
- 被質疑時以討論 trade-off 回應，不要防禦。
- 陷阱：背誦答案、忽略 scaling、被面試官打斷時硬講。

## 關鍵數字
- 準備時間：全新手 3-4 週；有基礎 < 1 週。

## 相關題目
- 練習題清單見 how-to-prepare；例如 [bitly](../../hellointerview-breakdowns/bitly.md)、[ticketmaster](../../hellointerview-breakdowns/ticketmaster.md)

## 自測問題
1. 四大評分主題是什麼？（Problem Navigation、Solution Design、Technical Excellence、Communication & Collaboration）
2. mid-level 與 senior 的期待差異？（皆需完整設計；senior 更快完成基礎並在 deep dive 展示深度、主動帶領）
3. 面試時間不夠準備時優先順序？（Delivery Framework → 略讀 Key Technologies → Core Concepts）
4. 面試官為何會質疑你的答案？（偵測背答案，測試推理與 trade-off 思考）
