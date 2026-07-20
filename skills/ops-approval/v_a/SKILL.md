---
skill_id: ops-approval
name: ops-approval
version: 1.0.0
description: "Domain SOP for refund approval with conflicting policies, a daily budget cap, and mandatory loyalty-point deduction. Enforces priority-order eligibility, budget accumulation, and read-before-write."
category: general
---

# Refund Approval（變體 A：領域專用 SOP，政策優先序＋預算＋連動扣點）

處理退款核准時，**注意：系統工具不會替你把關**——你退什麼它就退什麼、扣多少點就扣多少，
所以每一步都必須自己嚴格依政策判斷。務必照以下順序，做完一步再下一步：

1. **先查政策**：一開始就呼叫 `get_refund_policy`，看清楚「優先序、每日預算、連動扣點規則」。
   **查政策之前，絕對不要呼叫任何寫入工具**（`issue_refund`、`deduct_loyalty`）。
2. **列出並讀取**：用 `list_requests` 取得所有申請與明細（tier、days_since、amount、promo、fraud）。
3. **逐筆判資格（依優先序，高到低）**：
   1. `fraud=true` → **一律不退**（最高優先，即使看起來很新、金額大也不退）。
   2. `promo=FINAL` → **一律不退**（FINAL 促銷不可退，即使是 VIP 也蓋過）。
   3. VIP 客戶：退款窗為 **vip_days** 天（比一般寬）。
   4. 一般客戶：退款窗為 **base_days** 天。
   逾期（超過該 tier 的窗）→ 不退。
4. **排序**：把「符合資格」者排序——**VIP 優先**，其餘同組**按申請 id 升冪**。
5. **受每日預算逐筆核銷（長 horizon，務必累計）**：維護一個「已退累計金額」，
   逐筆嘗試退款；**若這筆退下去會超過 daily_budget，就 defer（不退）並繼續看後面**（不要為了塞小額而破序）。
6. **每筆退款必連動扣點**：每成功 `issue_refund` 後，**立刻**對該客戶 `deduct_loyalty`，
   點數 = `floor(退款金額 / 10)`。漏扣＝錯誤。
7. **最後通知**：全部處理完呼叫 `send_notification` 回報。

**核心紀律**：先查後寫、依優先序逐筆核對、累計預算不要忘、每退必扣點、寧可 defer 也不要違規退款。
