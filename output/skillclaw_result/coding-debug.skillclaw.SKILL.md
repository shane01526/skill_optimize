---
name: coding-debug
description: "Use for debugging failing unit tests in a Python project. Reproduce first, read tests as spec, make the smallest fix."
category: coding
---

# Coding Debug

When tests fail, look at the error and fix the code.

## 精煉補充（[MOCK-B] SkillClaw 由勝出變體證據萃取）
- 先重現失敗測試以確認可重現，再定位最小修改點。
- 把每個測試 case 當規格逐條對照，補齊缺漏分支（空輸入 / 邊界 / 需忽略的條件）。
- 修完先跑相關測試快速回饋，全綠後再跑完整套件。

