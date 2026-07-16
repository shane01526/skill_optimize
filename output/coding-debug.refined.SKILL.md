---
skill_id: coding-debug
name: coding-debug
version: 13
description: "Use for debugging failing tests by treating them as specifications and making minimal, targeted fixes."
category: coding
---

# Coding Debug (代碼除錯與測試修復)

## 核心原則：以測試為規格，最小化修改

1. **重現並定位問題 (Reproduce & Locate)**
   - **先執行測試**：直接執行測試指令（如 `pytest -q`），閱讀第一個失敗的斷言 (Assertion) 與 Traceback，確認能穩定重現。
   - **定位最小修改點**：從 Traceback 往回追溯出錯的程式碼行，專注於該處，**切忌盲目重寫大片程式碼**。

2. **以測試為規格進行對照 (Treat Tests as Specifications)**
   - 將測試案例視為功能規格，逐一列出並檢查以下常見邊界與分支：
     - **空輸入/極端值**：空字串 `""`、`None`、`0`、空陣列等。
     - **單一值/常規值**：單個元素、標準輸入。
     - **邊界條件**：上界/下界過濾（例如大於 1000 需忽略、負數需拋出異常等）。
     - **多重格式/分隔符**：是否支援多種分隔符（如 `,` 與 `\n`）、自定義分隔符。
   - 逐條對照目前實作，找出「哪些規格/分支尚未被處理」。

3. **最小修改與分段驗證 (Minimal Change & Incremental Verification)**
   - **一次只補一個缺失分支**：針對缺少的 Case 補上對應的 `if/else` 分支或邏輯，修改完立即重跑相關測試。
   - **分段驗證**：先確保當前修改的測試通過，最後再執行完整測試套件，確保沒有引入回歸 Bug (Regression)。
