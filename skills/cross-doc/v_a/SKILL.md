---
skill_id: cross-doc
name: cross-doc
version: 1.0.0
description: Use to cross-reference multiple sources: extract each source's claims, align them by topic, and explicitly flag agreements and contradictions with source citations.
category: general
---

# Cross Doc（變體 A：逐源抽點 → 交叉比對 → 標矛盾）

跨多份文獻交叉比對的有效流程：

1. **逐源抽claims**：把每一份來源（D1、D2…）各自的關鍵主張列出，標上來源編號，一份都不漏。
2. **依主題對齊**：把不同來源談同一議題的主張放在一起比較（同一 row 對照 D1/D2/D3）。
3. **明確標一致與矛盾**：
   - 多源一致 → 標「D1、D2 一致：…」。
   - 互相矛盾 → **兩邊都寫出並標明分歧**「D1 說 X，但 D3 說 Y」，不可擅自選邊或抹平。
   - 只有單一來源提到 → 標「僅 D2 提及」。
4. **每個結論附來源編號**（Dx），可回溯。
5. **忠實**：只根據來源，不外加；來源都沒提的問題寫「來源未涵蓋」。
