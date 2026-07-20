---
skill_id: ops-workflow
name: ops-workflow
version: 1.0.0
description: Use for multi-step operations workflows (refunds, returns) that require tools and external state. Enforces a strict read-before-write SOP with eligibility checks.
category: general
---

# Ops Workflow（變體 A：嚴格 SOP，先查後判再寫）

處理需要多步驟工具操作的業務流程（退款、退貨等）時，**嚴格照以下順序**，每步做完再進下一步：

1. **先查規則**：一開始就呼叫查政策的工具（如 `get_refund_policy` / `get_return_policy`），
   把「可執行的前置條件」看清楚。**在查政策之前，絕對不要呼叫任何會寫入/改狀態的工具**（如退款、補庫存）。
2. **列出並逐筆讀取**：用 list / get 類工具取得所有待處理項目與其明細（金額、天數、是否已處理、是否拆封…）。
3. **逐筆核對資格**：對每一筆，依政策條件一條一條檢查是否符合。**只有全部條件都滿足**才進下一步；
   不符合的**直接跳過、不可執行寫入動作**。
4. **符合才寫入**：只對通過資格檢查的項目呼叫寫入工具（退款/補庫存），金額/數量要對應該筆的正確值。
5. **看每步回傳**：每次工具呼叫後檢查回傳的 `ok`；若失敗（例如政策擋下），**停下來、不要硬做**，
   記錄原因，不要對同一筆重試繞過規則。
6. **最後通知**：全部處理完再呼叫通知工具回報結果。

**核心紀律**：先讀後寫、逐條核對、失敗即停、不跳步。寧可不做，也不要對不符合資格的項目寫入。
