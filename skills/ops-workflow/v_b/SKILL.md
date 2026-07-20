---
skill_id: ops-workflow
name: ops-workflow
version: 1.0.0
description: Use for tool-driven multi-step workflows. Always query policy first, verify each item's eligibility one by one, and only write state for items that pass; stop on failure.
category: general
---

# Ops Workflow（變體 B：查規則 → 逐條驗資格 → 只寫符合者 → 失敗即停）

- **Step 0 查規則**：先呼叫查政策工具，弄清楚每個「寫入動作」的前置條件。政策未查前不得寫入。
- **Step 1 蒐集**：列出所有待處理項目並逐筆讀明細。
- **Step 2 驗資格**：對每筆逐條比對政策條件（天數、是否已處理、金額上限、是否拆封等），
  記下「符合 / 不符合」。
- **Step 3 只寫符合者**：僅對符合資格的項目執行寫入工具；不符合者略過，切勿嘗試繞過或重試。
- **Step 4 檢查回傳**：每步看 `ok`；失敗就停、不硬闖。
- **Step 5 通知**：完成後回報。

原則：先讀後寫、逐條核對、只做該做的、失敗要停。
