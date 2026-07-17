---
skill_id: json-extract
name: json-extract
version: 1.0.0
description: Use to extract text into schema-conformant JSON by walking the schema field-by-field as a checklist. Validate types and enums, emit only the JSON object.
category: general
---

# JSON Extract（變體 B：schema 當檢查表逐項走）

- **把 schema 當檢查表**：把 required 欄位列成清單，一個一個確認有填、型別對、enum 合法。
- **型別/列舉嚴格**：number/boolean/string 分清楚；enum 只用允許值。
- **巢狀照結構**：object/array 依 schema 巢狀，不要壓平。
- **只輸出 JSON**：回單一合法 JSON 物件，不要多餘文字或多段 JSON。
- 文本沒有的值用 null（若 schema 允許），不捏造。
