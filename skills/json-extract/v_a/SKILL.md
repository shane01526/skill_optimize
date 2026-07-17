---
skill_id: json-extract
name: json-extract
version: 1.0.0
description: Use to extract data from unstructured text into JSON that strictly conforms to a given JSON Schema. Fill every required field, match types/enums exactly, output ONLY valid JSON.
category: general
---

# JSON Extract（變體 A：嚴格對齊 schema）

從非結構文本抽出**嚴格符合給定 JSON Schema** 的 JSON：

1. **先讀 schema**：列出所有 `required` 欄位、每個欄位的 `type`、`enum` 允許值、以及巢狀物件/陣列結構。
   把 schema 當成契約——輸出必須逐項對齊。
2. **逐欄位填值**：對每個 required 欄位，從文本找出對應資料填入；
   - 型別要對（數字用 number 不要用字串、布林用 true/false）。
   - enum 欄位只能用 schema 列出的允許值，不可自創。
   - 巢狀/陣列要照結構包好。
3. **缺值處理**：文本沒有的資訊，若 schema 允許 null 就填 null；不可為了湊而**捏造**。
   （若某 required 欄位文本真的沒有，選最忠實的表示，切勿亂編。）
4. **只輸出 JSON**：最終只回一個合法 JSON 物件（可放在 ```json 區塊內），
   **不要**夾雜說明文字、註解、或多個 JSON。
5. **自我檢查**：輸出前確認 (a) 每個 required 欄位都在、(b) 型別/enum 對、(c) 是合法 JSON 可被 parse。
