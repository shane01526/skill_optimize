# Skill 精煉機制

Created time: July 9, 2026 2:55 PM
Assignee: Aaron
Status: In progress
Project: 數位同事 (https://app.notion.com/p/38bee105f48380569f7ffdc9c44beaab?pvs=21)

## 研究方向：Skill 精煉機制

> 需求是希望從大量員工使用 Codex Skill 的紀錄中，透過 Log 分析找出可共用的有效做法，進一步整理、合併、精煉成標準化 Skill。
> 

**多人使用 / 修改 Skill 的 Log → 找出有效做法與共通模式 → 精煉成新的共用 Skill**

---

### 預計產出

1. Skill 精煉流程
2. 精煉前 / 精煉後的對照表

---

### 研究定位

1. SkillClaw 的 skill evolution 概念與本研究目標高度相似：都是從多使用者、長時間累積的 agent 使用紀錄中，找出重複出現且有效的做法，並用來更新共用 Skill。
2. 目前沒有集團 Log，也沒有同事的 Skill，因此先做個人版 MVP。
3. MVP 階段先以 coding Skill 作為實驗場景，因為 coding 任務比較容易判斷好壞。
4. MVP 做法是針對同一目標建立多個寫法不同的 Skill，讓它們處理同一批任務，再從結果較好的 Skill 中萃取有效做法。
5. 流程可擴展，換的是「怎麼判斷任務結果好不好」和「Golden Dataset」。

---

### 前提限制

1. 現有 Codex log 沒有欄位直接記錄 `skill_id` 或 `skill_used`。

2. Codex 主要依據 Skill 的 `name`、`description`、`path` 判斷是否使用；若決定使用，才會讀取對應的 `SKILL.md`。 

3. `task_complete` 只代表 Codex 該回合結束，不代表使用者滿意。 

4. 找到重複 pattern 不代表它一定有效，仍需要透過成功 / 失敗案例比較與 Evaluate 驗證。

---

### Skill 上架流程

1. Skill 作者提交 [SKILL.md](http://skill.md/) 

2. Skill Registry 讀取 [SKILL.md](http://skill.md/) metadata 例如 skill_id、name、description、version、path 

3. Skill Registry 檢查 skill_id 是否唯一、欄位是否完整 

4. 通過後，建立 Skill 資料

---

### Skill ID 設計

```markdown
---
skill_id: coding-debug
name: Coding Debug
version: 1.0.0
description: Use for debugging failing tests.
---
```

---

### 任務執行流程

1. 使用者丟任務 

2. Codex 根據 Skill 的 name / description / path 判斷要不要使用 Skill 

3. 若使用 Skill，Codex 會讀取對應的 [SKILL.md](http://skill.md/) 

4. Codex 依照讀取到的 Skill 內容執行任務 

5. 任務完成後，分析 Codex log 

6. 找出實際被讀取的 [SKILL.md](http://skill.md/) 

7. 從 [SKILL.md](http://skill.md/) 取出 skill_id 

8. 記錄為 actual_used_skill_ids 

9. 將 actual_used_skill_ids 與任務結果對齊，作為 Skill 精煉資料

---

### MVP 流程

```
Codex 原始對話紀錄
        +
SKILL.md metadata（skill_id）
        ↓
找出實際被讀取的 SKILL.md
        ↓
取得 actual_used_skill_ids
        ↓
整理任務紀錄與結果
        ↓
比較不同 Skill 在同一任務上的表現
        ↓
找出成功案例常出現的做法
        ↓
產生新版 Skill 草稿
        ↓
Evaluate
        ↓
產出精煉前 / 精煉後對照表
```

---