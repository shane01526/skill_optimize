---
skill_id: coding-debug
name: coding-debug
version: 1.0.0
description: Use for debugging failing unit tests in a Python project. Reproduce the failure first, then make the smallest fix.
category: coding
---

# Coding Debug（變體 A：重現優先、最小修改）

修復失敗測試的有效流程：

1. **先重現**：直接跑 `pytest -q`，讀第一個失敗的斷言與 traceback，確認你能重現。
2. **定位最小修改點**：從 traceback 往回找到出錯的那一行；不要一次改一大片。
3. **對照規格逐條檢查**：把測試當成規格，逐個 case 對照目前實作缺了哪個分支
   （空輸入？邊界值？被忽略的條件？）。
4. **只做最小修改**：一次補一個缺失分支，改完馬上重跑相關測試。
5. **分段驗證**：先跑相關測試快速回饋，全綠後再跑完整套件確認沒有回歸。

不要重寫整個檔案；不要改測試來遷就實作。
