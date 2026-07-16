# Skill 精煉對照表：coding-debug

- 動作：**improve_skill**　採用：**True**
- 變體數：1　session 數：12
- 驗證閘：score=0.86 / 門檻 0.75 → accept
- 精煉理由：[MOCK] 勝出變體共通做法：先重現、最小修改、分段驗證。

## 各變體在 golden task 的分數

| 變體 | task | runner | 測試 | pass_rate | judge | 綜合分 | 成功 |
|---|---|---|---|---|---|---|---|
| coding-debug | task_004 | mock | 0/0 | 0.0 | None | **0.96** | True |
| coding-debug | task_002 | mock | 5/5 | 1.0 | 0.803 | **0.911** | True |
| coding-debug | task_001 | mock | 5/5 | 1.0 | 0.803 | **0.906** | True |
| coding-debug | task_004 | mock | 0/0 | 0.0 | None | **0.86** | True |
| coding-debug | task_003 | mock | 0/0 | 0.0 | None | **0.752** | True |
| coding-debug | task_003 | mock | 0/0 | 0.0 | None | **0.752** | True |
| coding-debug | task_003 | mock | 0/0 | 0.0 | None | **0.72** | True |
| coding-debug | task_001 | mock | 3/5 | 0.6 | 0.803 | **0.669** | False |
| coding-debug | task_002 | mock | 3/5 | 0.6 | 0.803 | **0.669** | False |
| coding-debug | task_001 | mock | 2/5 | 0.4 | 0.803 | **0.557** | False |
| coding-debug | task_002 | mock | 2/5 | 0.4 | 0.803 | **0.557** | False |
| coding-debug | task_004 | mock | 0/0 | 0.0 | None | **0.0** | False |

**勝出變體**：`coding-debug`（綜合分 0.96）

## 精煉前 / 精煉後

### Before（coding-debug / coding-debug）
> Use for debugging failing tests.

### After（v12 / coding-debug）
> Use for debugging failing tests.

### 內容 diff
```diff
--- 
+++ 
@@ -2,2 +2,6 @@
 
 When tests fail, look at the error and fix the code.
+
+## 精煉補充（[MOCK] 由勝出變體證據萃取）
+- 先重現失敗測試，再定位最小修改點。
+- 修完只跑相關測試快速回饋，全綠後再跑完整套件。
```
