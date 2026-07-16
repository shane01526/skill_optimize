# Skill 精煉機制 Pipeline

從針對「同一類任務」的多個相似 skill 變體中，篩選出更有效率、效用的版本，
再萃取合併成一個精煉後的共用 Skill，並產出**精煉前 / 精煉後對照表**與一份
**離線 HTML 說明檔**。

需求與研究定位見 [`Skill 精煉機制_new.md`](Skill%20精煉機制_new.md)。
完整實作計畫見 `~/.claude/plans/immutable-soaring-lovelace.md`。

---

## 快速開始（離線可跑，不需 API key）

```bash
pip install -r requirements.txt

# 一鍵：跑實驗 → 精煉 → 產出對照表 + HTML（mock 離線模式）
SKILL_REFINER_MOCK=1 python -m refiner.pipeline all --mode mock
```

產出：
- `output/before_after.json` / `output/before_after.md` — 精煉前後對照表
- `output/coding-debug.refined.SKILL.md` — 精煉後的 skill 草稿
- `output/skill_registry.json` — skill_id / version / history
- `docs/skill_refinement.html` — **詳細說明查閱檔**（用瀏覽器開）

## 用真實 LLM 精煉

設定任一 provider 的金鑰即可（會自動偵測，預設 Anthropic）：

```bash
export ANTHROPIC_API_KEY=...        # 或 OPENAI_API_KEY / OPENAI_BASE_URL
python -m refiner.pipeline all --mode api      # LLM 當 coding agent
```

## 用 Codex CLI 當 runner（主線）

需先安裝經典 Codex CLI（`codex exec`）：

```bash
python -m refiner.pipeline all --mode codex    # agent 真的改檔、產生 rollout log
```

---

## 兩個 Phase

| Phase | 資料來源 | 指令 |
|---|---|---|
| **1 實驗驅動**（MVP 主線） | 手寫多個 skill 變體 × golden task | `run-experiment` → `refine` |
| **2 Log 探勘** | `~/.codex/sessions/**/rollout-*.jsonl` | `mine` → `refine` |

```bash
# Phase 2：從真實 Codex 對話探勘（累積 log 後）
python -m refiner.pipeline mine --sessions-dir ~/.codex/sessions --logs-dir logs
python -m refiner.pipeline refine
```

流程不換，換的只是「資料來源」與「評分方式」。

## Skill 上架驗證（Skill 上架流程）

對齊 `Skill 精煉機制_0714.md`「Skill 上架流程」：Registry 上架時檢查欄位完整
（`skill_id`/`name`/`description`）、`skill_id` slug 格式、唯一性（同 id 不同 name 衝突）。

```bash
python -m refiner.pipeline publish        # 掃 skills/<goal>/*/SKILL.md 逐一上架驗證
```

## actual_used_skill_ids

對齊 doc「任務執行流程」step 5-8：分析 log → 找出**實際被讀取**的 SKILL.md →
開檔取出 `skill_id` → 記為 `actual_used_skill_ids` → 與結果對齊（見 `normalizer.extract_used_skill_ids`）。
以此克服「Codex log 無 skill_id 欄位」的前提限制。

## 評分（通用場景無關 + coding 專用）

評分依 `task_type` 分流（標籤優先，否則以有無 `test_*.py` 偵測）：

- **通用（任何場景）** `refiner/generic_metrics.py`：從 session 既有欄位算
  `num_turns / elapsed_sec / num_tool_calls / tool_error_rate / response_chars`，
  以 cohort（同 (goal, task) 變體群）min-max 反向正規化成 `efficiency_score`。
  通用綜合分 = `completion × (0.6 + 0.4·efficiency)`——先確認有完成再比效率，避免獎勵擺爛。
- **coding 專用**：保留原本 `pytest 通過率(硬) + 四維 LLM judge(軟)` 綜合分為主體，
  再乘 `×(0.95 + 0.05·efficiency)` 做效率微調（向後相容）。

### 達標判定（降低 LLM 依賴）`refiner/completion_detector.py`

general 任務「有沒有達標」**優先用規則式 detector（零 LLM）判斷，模糊才退回 LLM judge**。
思路來自 IR／推薦系統的 implicit feedback——不問「滿意嗎」，而是看使用者**接下來的回覆**：
正向確認／採用產物／接續新任務 → 達標；否定／要求重來／重述同一需求 → 未達標
（純關鍵詞／正則／`difflib` 相似度）。`confidence ≥ 0.5` 用規則，否則 fallback LLM。
行為訊號在**多輪真實對話**（Phase 2）最有效；單輪 headless session 信心低 → 自動退回 LLM。

完整一步步拆解見 `docs/skill_refinement.html` 的「★ 評分流程詳解」。
範例任務：`task_003`（general，無測試）、`task_004`（general 多輪對話，附 `conversation.json`，
達標由使用者行為訊號判定）。

---

## Pipeline 階段（版本 A `refiner/`）

```
runner_codex → evaluator → normalizer → summarizer → aggregation
             → execution → verifier → registry → report / html_report
```

| 檔案 | 職責 | SkillClaw 對應 |
|---|---|---|
| `runner_codex.py` | 每個 (變體×task) 獨立 workspace 執行 | (client proxy) |
| `evaluator.py` | pytest 通過率（硬）+ LLM judge 四維（軟） | `session_judge.py` |
| `normalizer.py` | 實驗 log / rollout → 統一 session | (session dict) |
| `summarizer.py` | trajectory + LLM 摘要 | `summarizer.py` |
| `aggregation.py` | 依 skill 分組 | `aggregation.py` |
| `execution.py` | 萃取勝出做法 → 精煉草稿 | `execution.py` |
| `verifier.py` | before/after 四分數閘（≥0.75） | `skill_verifier.py` |
| `registry.py` | skill_id / version / history | `skill_registry.py` |
| `report.py` / `html_report.py` | 對照表 + HTML | — |

## 版本 B — 直接跑 SkillClaw

SkillClaw 以 **git submodule** 置於 `third_party/skillclaw/`。clone 本專案後先初始化：

```bash
git submodule update --init --recursive
```

用 SkillClaw evolve_server 的**原生**階段（summarize → session_judge → aggregate →
evolve → verify）精煉同一批 logs，供與版本 A 對照。轉接腳本在 `third_party/adapt_to_skillclaw.py`：

```bash
# 只轉檔（不需金鑰）
python third_party/adapt_to_skillclaw.py

# ★完整精煉（需有效的 OpenAI-compatible key；預設 gpt-4o）
export OPENAI_API_KEY=...            # 可搭 OPENAI_BASE_URL 指向集團 gateway / Azure
python third_party/adapt_to_skillclaw.py --refine

# 離線模擬（無金鑰時；注入介面相容的 Mock，仍走 SkillClaw 原生階段）
python third_party/adapt_to_skillclaw.py --refine --mock
```

產物 → `output/skillclaw_result/`：
- `result.json` — action / accepted / verify 分數 / session_judge 四維分數 / baseline+refined
- `coding-debug.skillclaw.SKILL.md` — 版本 B 精煉後草稿（accepted 時）

跑完重生 HTML（`python -m refiner.html_report`），第 6 節「版本 A vs B」會出現**實跑對照**
（動作 / 採用 / 驗證分數 / judge 對各變體評分 / 精煉內容 diff）。

---

## 測試

```bash
SKILL_REFINER_MOCK=1 python -m pytest
```

涵蓋：registry（skill_id 穩定性 / version 遞增 / history 上限 / 持久化）、
normalizer（統一 schema / rollout 解析 / skill 偵測 / SKILL.md 往返）、
端到端（勝出變體萃取、爛變體不勝出、驗證閘擋低分）、版本 B 轉接。

## 三個已知陷阱與對策

1. **log 沒記錄用了哪個 skill** → 上架綁 `skill_id`，runner 記 `selected_skill_ids`。
2. **task_complete ≠ 成功** → 用 pytest 通過率 + judge 當成功訊號。
3. **重複 pattern ≠ 有效** → verifier 四分數閘保守把關。
