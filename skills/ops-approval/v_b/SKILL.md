---
skill_id: ops-approval
name: ops-approval
version: 1.0.0
description: "Refund approval SOP: query policy first, resolve conflicting rules by strict priority, accumulate against the daily budget, and always pair each refund with a loyalty deduction."
category: general
---

# Refund Approval（變體 B：查政策 → 依優先序解衝突 → 累計預算 → 每退必扣點）

**前提**：寫入工具不做把關，一切正確性由你負責。

- **Step 0 查政策**：先 `get_refund_policy`，掌握優先序 / 每日預算 / 扣點公式。未查政策前不得寫入。
- **Step 1 蒐集**：`list_requests` 列出所有申請並逐筆讀明細。
- **Step 2 解政策衝突（優先序，高→低）**：`fraud` 一律不退 ＞ `promo=FINAL` 一律不退 ＞
  VIP 用 `vip_days` 窗 ＞ 一般用 `base_days` 窗；超窗即逾期不退。多條規則牴觸時以較高優先者為準。
- **Step 3 排序核銷**：符合者按「VIP 先、其餘 id 升冪」處理；維護已退金額累計，
  **任何會使累計超過 `daily_budget` 的申請一律 defer（不退）**。
- **Step 4 連動扣點**：每筆 `issue_refund` 後必須 `deduct_loyalty(customer, floor(amount/10))`；不可漏。
- **Step 5 通知**：完成後回報。

原則：先讀後寫、優先序解衝突、預算要累計、退款與扣點成對出現、失敗/超預算就停不硬做。
