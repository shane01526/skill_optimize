---
skill_id: coding-debug
name: coding-debug
version: 1.0.0
description: Use for debugging failing tests. Read the tests as the spec and cover every case.
category: coding
---

# Coding Debug（變體 B：以測試為規格）

- 把每個測試 case 當成一條規格，列出來：空輸入、單值、正常、邊界、需忽略的條件。
- 逐條對照目前實作，找出「哪些 case 沒被處理」。
- 針對缺的 case 補分支，改完重跑測試。
- 常見遺漏：空字串沒特判、只支援一種分隔符、沒處理上界/下界過濾。
