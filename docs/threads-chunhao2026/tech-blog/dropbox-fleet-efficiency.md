# Improving infrastructure efficiency for growing demand in the age of AI
> 原文：https://dropbox.tech/infrastructure/improving-infrastructure-efficiency-for-growing-demand-in-the-age-of-ai ｜ Dropbox（作者 Ilya Yakovlev）/ 2026-08-18 ｜ Threads 解讀：https://www.threads.com/@chunhao2026/post/Dc8rJsVjFgy（2026-09-06）

## 一句話重點
AI 時代容量需求暴增，Dropbox 的策略是「先把現有 fleet 的電力、空間、硬體壽命壓榨到極致，再考慮擴建」：用 Deep Sleep、Workload Balancing、SMR、依實際 failure rate 換機四招，系統性地降低每 PB 的成本。

## 作者的解讀（貼文重點，濃縮成條列，保留作者觀點）
- 直覺是買新設備擴容，Dropbox 反過來：先榨乾現有 fleet，才考慮買新硬體。
- Deep Sleep：閒置硬碟調到 standby，或整台 server 關掉，需要時幾分鐘內恢復；不需要「以備不時之需」讓硬體一直跑，待機成本近乎零。
- Workload Balancing：持續監控全 fleet 資源分布，把工作搬到低使用率機器；局部 bottleneck 靠重新分配解決，不必擴容。
- SMR：track 互相重疊，密度比 PMR 高，同容量用更少硬碟，連帶省 cabling、電力、冷卻。作者強調它適合 blob storage（資料多半只寫一次），random write 慢的缺點在此場景幾乎不影響。
- 換機時機看實際年故障率，不照廠商固定週期；能修就修，讓每台壽命最大化。

## 原文重點（背景/規模數字 → 問題 → 架構與設計決策 → 取捨 → 結果；這是主體）
**背景與規模**
- Dropbox 以混合模式營運多年：自研 blob storage Magic Pocket + colocation 資料中心。
- 原文數字：自 2020 年起，storage infrastructure 的 watts per petabyte 改善超過 50%，即支撐同樣儲存量所需電力不到 2020 年的一半。

**問題**
- AI 需求加速，基礎設施受限於能源、冷卻、硬體供應與實體空間；必須先最佳化現有系統，再談擴大資料中心 footprint。

**設計決策（原文五項）**
1. Deep Sleep：由自動化 fleet management 演算法決定哪些 server 有資格；可把閒置 HDD 降到 standby，或整台 server 斷電，且能在數分鐘內回到服務。
2. Workload Balancing：持續監看 spare capacity 與 workload 分布，重新平衡工作，或在需要的地方上線額外容量。
3. SMR：在不增加硬碟體積下提高資料密度，進而減少 server、rack、cabling 與電力冷卻需求。
4. 硬體生命週期：以 annual failure rate 等指標了解各元件與各世代設備隨時間的行為，據此做換機決策，可修就修，而非固定週期。
5. 實體基礎設施調整：第七代 server 部署需重新設計 rack 電力架構，每 rack 的 PDU 數量加倍，同時沿用既有 busway。

**取捨**
- Deep Sleep 以「恢復需數分鐘」換省電，因此只適合可容忍延遲的容量；原文另提對低延遲 workload 可只 spin down 閒置硬碟而非整台關機（該段細節以 WebSearch 摘要為準，未逐句核對）。
- 原文整體訴求是把各項決策視為相互關聯的系統級最佳化，而非單點問題。

**結果**
- watts per petabyte 較 2020 年改善 >50%。（原文未給其他單項節省比例，本文不補。）

## 面試怎麼用
- 容量規劃題：把「擴容」與「提高利用率」分開談；先講利用率（rebalancing、冷熱分層、休眠），再講加機器。
- Cold storage / blob store：資料 write-once、append-only 時，SMR 這類「寫入不友善但密度高」的媒體反而划算（補充：呼應 immutable extent 設計）。
- 成本指標：用 watts/PB、$/PB 這類單位成本衡量，而不只是總容量。
- 硬體生命週期：以實測 failure rate 驅動維運決策，是 data-driven ops 的好例子。
- 取捨話術：省電 vs 喚醒延遲；密度 vs random write 性能。

## 相關筆記
- [Dropbox（breakdown）](../../hellointerview-breakdowns/dropbox.md)
- [Distributed Cache](../../hellointerview-breakdowns/distributed-cache.md)（補充：資源利用率與容量規劃的對照）
