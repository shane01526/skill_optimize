# 任務：把交易描述抽成嚴格符合 schema 的 JSON

下方 SOURCES 是幾筆用自然語言描述的交易紀錄。請把它們抽取成**嚴格符合下方 SCHEMA 的單一 JSON 物件**。

## 驗收點（會據此評分）
1. **符合 schema**：必填欄位齊全、型別正確、enum 只用允許值、巢狀結構正確（用程式驗證，不通過即失敗）。
2. **只輸出 JSON**：最終只回一個合法 JSON 物件（可包在 ```json 區塊），不要夾雜說明文字或多個 JSON。
3. **忠實**：欄位值要對應來源事實，不得捏造來源沒有的數字或名稱。
4. `total_count` 要等於 `transactions` 的筆數；`report_date` 用 `YYYY-MM-DD`。

## SCHEMA
```json
{
  "type": "object",
  "required": ["report_date", "total_count", "transactions"],
  "properties": {
    "report_date": "YYYY-MM-DD 字串",
    "total_count": "整數",
    "transactions": [{
      "id": "字串", "amount": "數字",
      "currency": "TWD|USD|EUR|JPY", "status": "settled|pending|failed",
      "flagged": "布林(選填)",
      "counterparty": {"name": "字串", "country": "字串"}
    }]
  }
}
```

> 註：離線 grounded 測試，來源即下方 SOURCES。
