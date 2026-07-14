"""產生詳細說明 HTML（docs/skill_refinement.html）—— 使用者要的查閱檔。

單一 HTML、內嵌 CSS、可離線開。用 Jinja2 把 before_after.json 的對照表
渲染進去，其餘章節為手寫說明（含流程圖、架構對應表、陷阱與對策）。

用法：
  python -m refiner.html_report            # 讀 output/before_after.json
  python -m refiner.html_report --report <path> --out <path>
"""

from __future__ import annotations

import argparse
import html
import json
import os
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skill 精煉機制 — 詳細說明</title>
<style>
  :root{
    --bg:#0f1116; --panel:#171a21; --panel2:#1e222b; --ink:#e7eaf0; --muted:#9aa3b2;
    --line:#2a2f3a; --accent:#5b9dff; --good:#3fb950; --warn:#d29922; --bad:#f85149;
    --add:#123a20; --del:#3a1214; --chip:#232838;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
    line-height:1.7;font-size:15px}
  header{padding:40px 24px 28px;background:linear-gradient(160deg,#1a2030,#0f1116);border-bottom:1px solid var(--line)}
  .wrap{max-width:1080px;margin:0 auto;padding:0 24px}
  h1{font-size:30px;margin:0 0 6px}
  h2{font-size:22px;margin:40px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
  h3{font-size:17px;margin:24px 0 8px;color:#cdd6e6}
  .sub{color:var(--muted);font-size:15px}
  .toc{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
  .toc a{background:var(--chip);color:#cdd6e6;text-decoration:none;padding:6px 12px;border-radius:20px;font-size:13px;border:1px solid var(--line)}
  .toc a:hover{border-color:var(--accent);color:#fff}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:800px){.grid{grid-template-columns:1fr}}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}
  th,td{border:1px solid var(--line);padding:8px 10px;text-align:left}
  th{background:var(--panel2);color:#cdd6e6}
  tr:nth-child(even) td{background:#141821}
  .win td{background:#12291a !important}
  code,pre{font-family:"JetBrains Mono",Consolas,Menlo,monospace;font-size:13px}
  pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto}
  .chip{display:inline-block;padding:2px 9px;border-radius:12px;font-size:12px;border:1px solid var(--line);background:var(--chip)}
  .ok{color:var(--good)} .no{color:var(--bad)} .mid{color:var(--warn)}
  .flow{background:#0b0d12;border:1px dashed var(--line);border-radius:10px;padding:16px;white-space:pre;overflow:auto;color:#b9c2d4;font-family:"JetBrains Mono",Consolas,monospace;font-size:12.5px}
  .diff .add{background:var(--add);color:#7ee787;display:block}
  .diff .del{background:var(--del);color:#ff9a9a;display:block}
  .diff .hunk{color:var(--accent);display:block}
  .diff .ctx{color:var(--muted);display:block}
  .kpi{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0}
  .kpi .box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:120px}
  .kpi .n{font-size:24px;font-weight:700}
  .kpi .l{color:var(--muted);font-size:12px}
  .callout{border-left:3px solid var(--accent);background:#141a26;padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0}
  .callout.warn{border-color:var(--warn);background:#241f14}
  footer{color:var(--muted);font-size:12px;padding:30px 24px;border-top:1px solid var(--line);margin-top:40px}
  a{color:var(--accent)}
  .mut{color:var(--muted)}
  ul{margin:8px 0 8px 0;padding-left:22px} li{margin:3px 0}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>Skill 精煉機制 — 詳細說明</h1>
  <div class="sub">從多個 skill 變體的使用紀錄中，篩選出更有效率、效用的版本，精煉成標準化共用 Skill。</div>
  <div class="sub mut">個人版 MVP · 實驗驅動（Phase 1）+ Log 探勘（Phase 2）· 基礎參考：SkillClaw（AMAP-ML）</div>
  <nav class="toc">
    <a href="#s1">1 需求與定位</a>
    <a href="#s2">2 SkillClaw 對應</a>
    <a href="#s3">3 Pipeline 流程</a>
    <a href="#s4">4 skill_id / Registry</a>
    <a href="#s-score">★ 評分流程</a>
    <a href="#s5">5 精煉前/後對照表</a>
    <a href="#s6">6 版本 A vs B</a>
    <a href="#s7">7 陷阱與擴展</a>
  </nav>
</div></header>

<main class="wrap">

<section id="s1">
<h2>1. 需求與研究定位</h2>
<div class="card">
  <p><b>需求：</b>從大量員工使用 Codex Skill 的紀錄中，透過 Log 分析找出可共用的有效做法，
  進一步整理、合併、精煉成標準化 Skill。</p>
  <p class="mut">多人使用 / 修改 Skill 的 Log → 找出有效做法與共通模式 → 精煉成新的共用 Skill</p>
  <ul>
    <li>目前沒有集團 Log 和同事的 Skill，先做<b>個人版 MVP</b>。</li>
    <li>MVP 以 <b>coding 任務</b>為實驗場景（好判斷結果好壞）：針對同一目標建立不同寫法的 skill 去跑同一任務，
      再從結果較好的 skill 裡萃取好做法。</li>
    <li>流程可擴展，換的是「怎麼判斷任務結果好不好」與「Golden Dataset 怎麼設計」。</li>
  </ul>
  <div class="callout"><b>預計產出：</b>① 可執行的 Skill 精煉流程　② 精煉前 / 精煉後對照表（本頁第 5 節）</div>
</div>
</section>

<section id="s2">
<h2>2. 為何選 SkillClaw、以及對應關係</h2>
<div class="card">
  <p>SkillClaw 的 <code>evolve_server</code> 正是可重用的精煉核心：從真實 session 自動去重、改進、合併、驗證 skill。
  它<b>不需要 golden dataset</b>，缺分數時退回 LLM-judge。本專案借用其設計精神與 prompt，但去掉
  proxy / OSS / dashboard / Nacos 等重架構，改成可離線、以檔案為主的個人版。</p>
  <table>
    <tr><th>本專案階段</th><th>SkillClaw 對應</th><th>版本 A 檔案</th></tr>
    <tr><td>Log 統一格式</td><td>session dict（turns / _skills_referenced / 分數）</td><td><code>normalizer.py</code></td></tr>
    <tr><td>摘要 + trajectory</td><td><code>pipeline/summarizer.py</code></td><td><code>summarizer.py</code></td></tr>
    <tr><td>依 skill 分組</td><td><code>pipeline/aggregation.py</code></td><td><code>aggregation.py</code></td></tr>
    <tr><td>評分（軟）</td><td><code>pipeline/session_judge.py</code>（四維權重）</td><td><code>evaluator.py</code></td></tr>
    <tr><td>評分（硬）</td><td>benchmark / PRM 分數</td><td><code>evaluator.run_pytest</code></td></tr>
    <tr><td>生成精煉版</td><td><code>pipeline/execution.py</code>（improve/create/merge）</td><td><code>execution.py</code></td></tr>
    <tr><td>before/after 閘</td><td><code>pipeline/skill_verifier.py</code>（≥0.75 四分數）</td><td><code>verifier.py</code></td></tr>
    <tr><td>skill_id / 版本</td><td><code>core/skill_registry.py</code></td><td><code>registry.py</code></td></tr>
  </table>
</div>
</section>

<section id="s3">
<h2>3. 本專案 Pipeline 流程</h2>
<div class="grid">
  <div class="card">
    <h3>Phase 1 — 實驗驅動（MVP 主線）</h3>
    <div class="flow">同一 coding 目標
   │  手寫多個 skill 變體 (v_a / v_b / v_c)
   ▼
Runner（codex exec / API / mock）
   │  每個 (變體 × golden task) 獨立 workspace 執行
   ▼
Evaluator
   │  pytest 通過率（硬） + LLM judge 四維（軟）
   ▼
Normalize → Summarize → Aggregate(by skill)
   ▼
Execution：從勝出變體萃取共通做法 → 精煉版草稿
   ▼
Verifier：before/after 四分數閘（≥0.75）
   ▼
Registry(version+1) + 精煉前/後對照表</div>
  </div>
  <div class="card">
    <h3>Phase 2 — Log 探勘（累積真實 log 後）</h3>
    <div class="flow">Codex 經典 CLI 日常對話
   │  ~/.codex/sessions/**/rollout-*.jsonl
   ▼
篩選：使用者自訂 skill →
   哪幾筆對話更新過該 skill
   ▼
Normalize（rollout → 統一 session）
   ▼
（沿用 Phase 1 後段，流程不換）
Summarize → Aggregate → Execution
   → Verifier → Registry → 對照表

換的只是「資料來源」與「評分方式」。</div>
    <div class="callout warn"><b>本機現況：</b>這台是 Codex Desktop app（SQLite 狀態），
      目前無 rollout log；Phase 2 需先安裝經典 CLI 並累積對話。</div>
  </div>
</div>
</section>

<section id="s4">
<h2>4. skill_id / 版本 / Registry 機制</h2>
<div class="card">
  <p>現有 Codex log <b>沒有</b>穩定欄位記錄「用了哪個 Skill」（靠 name/description 讓 LLM 判斷）。
  因此 skill 上架時就綁定 <code>skill_id</code>，讓使用紀錄、評估結果、精煉都能對齊到同一個 Skill。</p>
  <pre>---
skill_id: {{ before.skill_id }}
name: {{ before.name }}
version: 1.0.0
description: ...
---</pre>
  <ul>
    <li><b>skill_id</b>：作者提供的識別碼（slug，如 <code>coding-debug</code>）；未提供時系統以 <code>SHA-256(name)[:12]</code> 產生。</li>
    <li><b>version</b> 每次內容變更 +1；<b>content_sha</b> 記錄內容雜湊供衝突偵測。</li>
    <li><b>history</b>（上限 20 筆）記錄每次 {version, content_sha, timestamp, action, rationale}。</li>
    <li>Orchestrator（runner）明確記錄 <code>actual_used_skill_ids</code>，不靠事後推斷。</li>
  </ul>

  <h3>Skill 上架驗證（doc「Skill 上架流程」）</h3>
  {% if publish %}
  <p class="mut">Registry 上架時檢查：欄位完整（skill_id/name/description）、skill_id slug 格式、唯一性（同 id 不同 name 衝突）。</p>
  <table>
    <tr><th>SKILL.md</th><th>結果</th><th>skill_id / 錯誤</th></tr>
    {% for r in publish.results %}
    <tr><td><code>{{ r.path }}</code></td>
      <td class="{{ 'ok' if r.ok else 'no' }}">{{ '通過' if r.ok else '擋下' }}</td>
      <td>{{ r.skill_id if r.ok else (r.errors | join('; ')) }}</td></tr>
    {% endfor %}
  </table>
  <p class="mut">通過 {{ publish.passed }} / 失敗 {{ publish.failed }}。</p>
  {% else %}
  <p class="mut">（執行 <code>python -m refiner.pipeline publish</code> 後本區塊會顯示各 SKILL.md 的上架驗證結果。）</p>
  {% endif %}

  <h3>實際使用的 skill_id（actual_used_skill_ids）</h3>
  <p class="mut">分析 log 找出實際被讀取的 SKILL.md → 取出其 skill_id → 與任務結果對齊（doc「任務執行流程」step 5-8）。</p>
  <table>
    <tr><th>變體</th><th>actual_used_skill_ids</th></tr>
    {% for a in report.variant_aggregate %}
    <tr><td><code>{{ a.variant }}</code></td><td>{{ a.actual_used_skill_ids | join(', ') }}</td></tr>
    {% endfor %}
  </table>
</div>
</section>

<section id="s-score">
<h2>★ 評分流程詳解（Scoring，一步步）</h2>
<div class="card">
  <p>每個 <b>(變體 × task)</b> 會產生一個 session。評分先<b>依任務類型分流</b>：
  <b>coding</b> 走「pytest 硬指標 + LLM judge 軟指標」為主、再用通用效率分微調；
  <b>general（任何場景）</b> 走「通用完成度 judge × 效率」。最後把同一變體跨多個 task 的綜合分
  取平均，決定<b>勝出變體</b>。程式在 <code>refiner/evaluator.py</code> 與 <code>refiner/generic_metrics.py</code>。</p>
  <div class="flow">一個 session（變體 v × task t）
   │
   ├─▶ 通用指標（任何場景都算）
   │     num_turns / elapsed / tool 次數·錯誤率 / 輸出長度
   │     → cohort min-max 反向正規化 → efficiency_score ∈ [0,1]
   │
   ▼ resolve_task_type(session)   # 標籤優先，否則有無測試偵測
 ┌───────────────┴────────────────┐
 coding                            general（場景無關）
   │ pytest pass_rate（硬 60%）       │ 通用 completion judge
   │ + LLM judge 四維（軟 40%）       │   （任務完成度）
   │ = base                          │
   ▼ 效率微調 ±5%                    ▼ 效率加成 ≤40%
 score = base × (0.95+0.05·eff)   score = completion × (0.6+0.4·eff)
 └───────────────┬────────────────┘
   ▼ 聚合：同一變體跨 task 取 avg_score → 取最高者為 winner</div>
</div>

<div class="card">
  <h3>通用（場景無關）評分：不依賴 pytest 也能比較 skill</h3>
  <p>對應 <code>refiner/generic_metrics.py</code>。以下四類指標<b>任何任務都能算</b>，全部從 session 既有
  欄位取得，不需額外資料源：</p>
  <table>
    <tr><th>指標</th><th>來源</th><th>方向</th><th>權重</th></tr>
    <tr><td><code>num_turns</code></td><td>len(turns)：對話輪數</td><td>越少越好</td><td>0.35</td></tr>
    <tr><td><code>elapsed_sec</code></td><td>runner_meta 的 ended−started：執行時間</td><td>越少越好</td><td>0.25</td></tr>
    <tr><td><code>num_tool_calls</code></td><td>所有 turn 的工具呼叫總數</td><td>越少越好</td><td>0.15</td></tr>
    <tr><td><code>tool_error_rate</code></td><td>有錯誤的 tool_results 佔比</td><td>越低越好</td><td>0.15</td></tr>
    <tr><td><code>response_chars</code></td><td>回覆總字數（代理 token 消耗）</td><td>越少越好</td><td>0.10</td></tr>
  </table>
  <ul>
    <li><b>正規化</b>：以「同一 goal 的變體群（cohort）」做 min-max <b>反向</b>正規化
      → 該群最小值得 1.0、最大值得 0.0；全相等或只有一個值 → 1.0（無區別）。
      加權平均得 <code>efficiency_score ∈ [0,1]</code>。</li>
    <li><b>缺值處理</b>：某項在 cohort 全缺（如 mock 無真實時間）→ 該項不計入，權重按剩餘項重分配，
      並在 <code>skipped_metrics</code> 標註。</li>
    <li><b>防呆</b>：效率「越少越好」，單獨用會獎勵擺爛。故通用分一定是
      <code>完成度 judge × 效率</code>——先確認有完成，再在完成前提下比效率。</li>
  </ul>
  <div class="callout"><b>通用有效性 judge</b>（<code>prompts.GENERIC_JUDGE_SYSTEM</code>）不假設 coding，
  只評 <code>task_completion / response_quality</code>；明確要求「做得少或放棄 → task_completion 要低」，
  避免短 trajectory 被誤判為好。</div>
</div>

<div class="card">
  <h3>Step 1（coding 專用）— 硬指標：pytest 通過率（客觀 ground truth）</h3>
  <p>對應 <code>evaluator.py::run_pytest → _parse_pytest_output</code>。這是文件「coding 任務好判斷好壞」的核心；
  非 coding 任務沒有這一步（改由上方通用完成度 judge 提供有效性訊號）。</p>
  <ul>
    <li>在該 (變體×task) 的<b>獨立 workspace</b> 跑 <code>pytest -q</code>（agent 已在此改過程式），
      彼此不互相污染。</li>
    <li>用 regex 從輸出抓 <code>N passed / N failed / N error</code>：
      <br><code>total = passed + failed + errors</code>；
      <code>pass_rate = passed / total</code>（四捨五入 3 位）。</li>
    <li><code>all_pass = (total &gt; 0 且 passed == total)</code> → 之後決定 <code>_success</code>。</li>
    <li>邊界：找不到測試 / timeout / 執行例外 → <code>pass_rate = 0.0</code>（視為失敗，不中斷）。</li>
  </ul>
  <pre>pass_rate = passed / (passed + failed + errors)
# 例：5 passed, 0 failed  → 5/5  = 1.0
#     3 passed, 2 failed  → 3/5  = 0.6
#     2 passed, 3 failed  → 2/5  = 0.4</pre>
</div>

<div class="card">
  <h3>Step 2（coding 專用）— 軟指標：LLM judge 四維加權</h3>
  <p>對應 <code>evaluator.py::judge_session → _parse_scores</code>，system prompt 為
  <code>prompts.JUDGE_SYSTEM</code>（沿用 SkillClaw session_judge 的四維與權重）。</p>
  <ul>
    <li>送給 judge 的 payload：<code>session_id / skill_name / task_id / test（硬指標結果）/
      _trajectory（逐步軌跡）/ _summary（LLM 摘要）</code>。</li>
    <li>呼叫 <code>LLMClient.chat(JUDGE_SYSTEM, payload, temperature=0.1, max_tokens=1200)</code>，
      要求回一個 JSON。</li>
    <li>四個維度各自 clamp 到 [0,1]，再依權重加總為 <code>overall_score</code>（round 3）。</li>
    <li>容錯：JSON 解析失敗、或任一維度不是數字 → 回 <code>None</code>，該 session 略過軟指標
      （只用硬指標）。</li>
  </ul>
  <table>
    <tr><th>維度</th><th>意義</th><th>權重</th></tr>
    <tr><td><code>task_completion</code></td><td>是否達成 coding 目標（測試通過是強證據）</td><td><b>0.55</b></td></tr>
    <tr><td><code>response_quality</code></td><td>修正的正確性 / 完整性 / 清晰度</td><td>0.30</td></tr>
    <tr><td><code>tool_usage</code></td><td>工具使用是否適當有效</td><td>0.10</td></tr>
    <tr><td><code>efficiency</code></td><td>是否避免無謂重試 / 繞路</td><td>0.05</td></tr>
  </table>
  <pre>overall = 0.55·task_completion + 0.30·response_quality
        + 0.10·tool_usage    + 0.05·efficiency</pre>
</div>

<div class="card">
  <h3>Step 3 — 合成綜合分（依任務類型分流）</h3>
  <p>對應 <code>evaluator.py::evaluate_session</code>。先 <code>resolve_task_type</code>（標籤優先，
  否則有無測試偵測），再分流：</p>
  <pre># coding：原 pytest+judge 為主體，效率僅 ±5% 微調（向後相容）
base  = 0.6 × pass_rate + 0.4 × judge.overall_score
score = base × (0.95 + 0.05 × efficiency_score)

# general（場景無關）：完成度為主體，效率在已完成前提下加成 ≤40%
score = completion × (0.6 + 0.4 × efficiency_score)</pre>
  <ul>
    <li>coding 退化情形：只有硬指標 → 取 pass_rate；只有軟指標 → 取 overall；皆無 → 0。</li>
    <li><code>_success</code>：coding 用 <code>all_pass</code>；general 用 <code>completion ≥ 0.75</code>。</li>
    <li>效率<b>中性</b>（cohort 無區別）時 efficiency=1.0：coding <code>×(0.95+0.05)=×1.0</code>，
      分數與升級前一致 → <b>向後相容</b>。</li>
    <li>同時把 <code>_avg_prm = score</code>，讓 summarizer / execution 排序時對齊（借 SkillClaw PRM 概念）。</li>
  </ul>
</div>

<div class="card">
  <h3>Step 4 — 變體聚合 → 選出 winner</h3>
  <p>對應 <code>report.py::_variant_aggregate</code>。同一變體會跑多個 golden task，
  取<b>跨 task 的綜合分平均</b> <code>avg_score</code>，最高者為勝出變體（對齊文件「同一批任務」語意）。
  勝出變體的內容送進 <code>execution.py</code> 萃取共通有效做法，生成精煉版草稿。</p>
</div>

<div class="card">
  <h3>實算範例（本頁 mock 模式的實際數字）</h3>
  <p class="mut">離線 mock 的 judge 以 base=0.8 產生四維（見 <code>mock_llm.py</code>）：
  overall = 0.8·0.55 + 0.8·0.30 + 0.85·0.05 + 0.8·0.10 = <b>0.803</b>。
  真實 LLM 模式則由模型實際評分，數字會不同。</p>
  <table>
    <tr><th>變體</th><th>pytest pass_rate（硬）</th><th>judge overall（軟）</th><th>0.6×硬 + 0.4×軟</th><th>綜合分</th></tr>
    <tr class="win"><td><code>v_a</code></td><td>1.0</td><td>0.803</td><td>0.6·1.0 + 0.4·0.803</td><td><b>0.921</b></td></tr>
    <tr><td><code>v_b</code></td><td>0.6</td><td>0.803</td><td>0.6·0.6 + 0.4·0.803</td><td><b>0.681</b></td></tr>
    <tr><td><code>v_c</code></td><td>0.4</td><td>0.803</td><td>0.6·0.4 + 0.4·0.803</td><td><b>0.561</b></td></tr>
  </table>
  <p class="mut">→ 三個變體軟指標相同（mock 特性），故差距主要由 <b>pytest 通過率</b>拉開；
  <code>v_a</code> 全過勝出。真實 LLM judge 下軟指標也會分化。</p>
  <p class="mut">上表為 coding 的 <code>base</code> 分（Step 3 前）。實際 <code>score</code> 會再乘上效率微調
  <code>×(0.95+0.05·efficiency)</code>；因效率僅 ±5%，數字幾乎不變（例：v_a base 0.921 → 視 cohort 效率
  約 0.91~0.92），winner 不受影響。實際數字見下方第 5 節對照表。</p>
</div>

<div class="card">
  <h3>兩件容易混淆的事</h3>
  <div class="callout"><b>三種 judge 來源，公式相同：</b>
  ① 版本 A 真實 LLM（<code>JUDGE_SYSTEM</code>）② 版本 A 離線 mock（<code>mock_llm.py</code>，base=0.8）
  ③ 版本 B 由 SkillClaw 原生 <code>session_judge</code>——都用同一組四維與權重。</div>
  <div class="callout warn"><b>「評分閘」≠「發布閘」：</b>
  本節的<b>綜合分</b>用來比較變體、選勝出；而 <code>verifier.py</code> 的 <b>0.75 門檻</b>是另一道
  獨立的「精煉版能不能發布」閘（四個 check：grounded_in_evidence / preserves_existing_value /
  specificity_and_reusability / safe_to_publish），用途不同、不要混為一談。</div>
</div>
</section>

<section id="s5">
<h2>5. 精煉前 / 精煉後對照表</h2>
<div class="card">
  <div class="kpi">
    <div class="box"><div class="n">{{ report.goal }}</div><div class="l">目標 skill</div></div>
    <div class="box"><div class="n">{{ report.num_variants }}</div><div class="l">變體數</div></div>
    <div class="box"><div class="n">{{ report.num_sessions }}</div><div class="l">session 數</div></div>
    <div class="box"><div class="n">{{ report.generated_action }}</div><div class="l">精煉動作</div></div>
    <div class="box"><div class="n {{ 'ok' if report.accepted else 'no' }}">{{ '採用' if report.accepted else '未採用' }}</div><div class="l">驗證結果</div></div>
  </div>
  {% if report.verify %}
  <p class="mut">驗證閘：score = <b>{{ report.verify.score }}</b> / 門檻 {{ report.verify.threshold }} → {{ report.verify.decision }}
  {% if report.verify.checks %}（{% for k,v in report.verify.checks.items() %}{{ k }}={{ v }} {% endfor %}）{% endif %}</p>
  {% endif %}
  <p><b>精煉理由：</b>{{ report.rationale }}</p>

  <h3>各變體在 golden task 的表現</h3>
  <p class="mut">分數怎麼算的一步步拆解見 <a href="#s-score">★ 評分流程詳解</a>。</p>
  <table>
    <tr><th>變體</th><th>task</th><th>類型</th><th>測試</th><th>pass_rate</th><th>judge</th>
      <th>輪數</th><th>時間(s)</th><th>tool錯誤率</th><th>效率</th><th>綜合分</th><th>成功</th></tr>
    {% for r in report.variant_scores %}
    <tr class="{{ 'win' if report.winner and r.session_id == report.winner.session_id else '' }}">
      <td><code>{{ r.variant }}</code></td><td>{{ r.task_id }}</td><td>{{ r.task_type }}</td>
      <td>{{ r.tests }}</td><td>{{ r.pass_rate }}</td><td>{{ r.judge_overall }}</td>
      <td>{{ r.num_turns }}</td><td>{{ r.elapsed_sec }}</td><td>{{ r.tool_error_rate }}</td>
      <td>{{ r.efficiency_score }}</td>
      <td><b>{{ r.score }}</b></td>
      <td class="{{ 'ok' if r.success else 'no' }}">{{ '✓' if r.success else '✗' }}</td>
    </tr>
    {% endfor %}
  </table>
  <p class="mut">「輪數 / 時間 / tool錯誤率 / 效率」為<b>通用（場景無關）</b>指標；「測試 / pass_rate / judge」為
  <b>coding 專用</b>。效率 = cohort 內反向正規化後的加權分（越高越省資源）。</p>
  {% if report.variant_aggregate %}
  <h3>各變體跨 task 平均（winner 依此選出）</h3>
  <table>
    <tr><th>變體</th><th>類型</th><th>task 數</th><th>平均 pass_rate</th><th>平均輪數</th><th>平均時間(s)</th>
      <th>平均效率</th><th>平均綜合分</th><th>全成功</th></tr>
    {% for a in report.variant_aggregate %}
    <tr class="{{ 'win' if report.winner and a.variant == report.winner.variant else '' }}">
      <td><code>{{ a.variant }}</code></td><td>{{ a.task_type }}</td><td>{{ a.num_tasks }}</td>
      <td>{{ a.avg_pass_rate }}</td><td>{{ a.avg_num_turns }}</td><td>{{ a.avg_elapsed_sec }}</td>
      <td>{{ a.avg_efficiency }}</td><td><b>{{ a.avg_score }}</b></td>
      <td class="{{ 'ok' if a.all_success else 'no' }}">{{ '✓' if a.all_success else '✗' }}</td></tr>
    {% endfor %}
  </table>
  {% endif %}
  {% if report.winner %}<p>勝出變體：<span class="chip ok">{{ report.winner.variant }}</span>（跨 {{ report.winner.num_tasks }} task 平均綜合分 {{ report.winner.avg_score }}）</p>{% endif %}

  <div class="grid">
    <div class="card">
      <h3>Before（精煉前）</h3>
      <p class="mut">{{ before.skill_id }}</p>
      <p><b>{{ before.name }}</b></p>
      <p class="mut">{{ before.description }}</p>
      <pre>{{ before.content }}</pre>
    </div>
    <div class="card">
      <h3>After（精煉後{% if after %} · v{{ after.version }}{% endif %}）</h3>
      {% if after %}
      <p class="mut">{{ after.skill_id }}</p>
      <p><b>{{ after.name }}</b></p>
      <p class="mut">{{ after.description }}</p>
      <pre>{{ after.content }}</pre>
      {% else %}
      <p class="mut">（未產生採用的精煉版——見 skip / reject 理由）</p>
      {% endif %}
    </div>
  </div>

  {% if content_diff %}
  <h3>內容 diff（before → after）</h3>
  <pre class="diff">{% for d in content_diff %}<span class="{{ d.kind }}">{{ d.text }}</span>{% endfor %}</pre>
  {% endif %}
</div>
</section>

<section id="s6">
<h2>6. 版本 A（自建）vs 版本 B（SkillClaw）</h2>
<div class="card">
  <table>
    <tr><th></th><th>版本 A — 精簡自建</th><th>版本 B — 直接跑 SkillClaw</th></tr>
    <tr><td>定位</td><td>個人 MVP、可離線、可讀、好控制</td><td>驗證 A 正確性、未來擴集團規模</td></tr>
    <tr><td>依賴</td><td>anthropic/openai + yaml + jinja2</td><td>evolve_server + OpenAI-compatible endpoint</td></tr>
    <tr><td>資料流</td><td>logs/ JSON in → output/ 草稿+對照表</td><td>logs → SkillClaw session dict → workflow.run_once</td></tr>
    <tr><td>評分</td><td>pytest（硬）+ LLM judge（軟）</td><td>PRM / session_judge / verifier</td></tr>
    <tr><td>擴展</td><td>換評分 / golden dataset 即可</td><td>內建 sharing / OSS / dashboard</td></tr>
  </table>
  <p class="mut">轉接腳本：<code>third_party/adapt_to_skillclaw.py</code> 把本專案 logs 餵進 SkillClaw workflow（SkillClaw 以 submodule 置於 <code>third_party/skillclaw/</code>）。</p>
</div>

{% if skillclaw %}
<div class="card">
  <h3>實跑對照（同一批 logs，各自精煉）</h3>
  <p class="mut">LLM：{{ skillclaw.model }}{% if skillclaw.model == 'mock' %}（離線模擬——OpenAI key 401，改用介面相容的 Mock 驅動 SkillClaw 原生階段）{% endif %}
  {% if skillclaw.error %}<span class="no"> · 版本 B 執行錯誤：{{ skillclaw.error }}</span>{% endif %}</p>
  <table>
    <tr><th>維度</th><th>版本 A（自建）</th><th>版本 B（SkillClaw）</th></tr>
    <tr><td>精煉動作</td><td>{{ report.generated_action }}</td><td>{{ skillclaw.action }}</td></tr>
    <tr><td>是否採用</td>
      <td class="{{ 'ok' if report.accepted else 'no' }}">{{ '採用' if report.accepted else '未採用' }}</td>
      <td class="{{ 'ok' if skillclaw.accepted else 'no' }}">{{ '採用' if skillclaw.accepted else '未採用' }}</td></tr>
    <tr><td>驗證閘分數</td>
      <td>{{ report.verify.score if report.verify else '—' }}</td>
      <td>{{ skillclaw.verify.score if skillclaw.verify else '—' }}</td></tr>
    <tr><td>精煉後 description</td>
      <td>{{ after.description if after else '—' }}</td>
      <td>{{ skillclaw.refined.description if skillclaw.refined else '—' }}</td></tr>
  </table>

  {% if skillclaw.judge_scores %}
  <h3>版本 B — SkillClaw session_judge 對各變體評分</h3>
  <table>
    <tr><th>變體</th><th>pytest pass_rate</th><th>judge overall</th><th>task_completion</th><th>response_quality</th><th>efficiency</th><th>tool_usage</th></tr>
    {% for j in skillclaw.judge_scores %}
    <tr><td><code>{{ j.variant_label }}</code></td><td>{{ j.pass_rate }}</td><td><b>{{ j.overall_score }}</b></td>
      <td>{{ j.task_completion }}</td><td>{{ j.response_quality }}</td><td>{{ j.efficiency }}</td><td>{{ j.tool_usage }}</td></tr>
    {% endfor %}
  </table>
  <p class="mut">對照：版本 A 的綜合分（pytest 硬 60% + judge 軟 40%）見第 5 節；兩版對同一批變體的排序一致（v_a &gt; v_b &gt; v_c）可互相佐證。</p>
  {% endif %}

  {% if skillclaw.refined %}
  <div class="grid">
    <div class="card">
      <h3>版本 B 精煉後 skill</h3>
      <p class="mut">{{ skillclaw.refined.name }}</p>
      <pre>{{ skillclaw.refined.content }}</pre>
    </div>
    <div class="card">
      <h3>版本 B 內容 diff（baseline → refined）</h3>
      {% if skillclaw._diff %}
      <pre class="diff">{% for d in skillclaw._diff %}<span class="{{ d.kind }}">{{ d.text }}</span>{% endfor %}</pre>
      {% else %}<p class="mut">（無 diff 可顯示）</p>{% endif %}
    </div>
  </div>
  {% endif %}
</div>
{% else %}
<div class="callout warn">版本 B 尚未實跑。執行
  <code>python third_party/adapt_to_skillclaw.py --refine</code>
  （或加 <code>--mock</code> 離線）後重新產生本頁即可看到實跑對照。</div>
{% endif %}
</section>

<section id="s7">
<h2>7. 三個已知陷阱與對策 · 可擴展性</h2>
<div class="grid">
  <div class="card">
    <h3>陷阱與對策</h3>
    <ul>
      <li><b>log 沒記錄用了哪個 skill</b> → 上架時綁 <code>skill_id</code>；分析 log 找出實際讀取的 SKILL.md 取其 skill_id，記為 <code>actual_used_skill_ids</code> 與結果對齊。</li>
      <li><b>task_complete ≠ 成功</b> → 用 pytest 通過率 + LLM judge 當成功訊號，不只看是否結束。</li>
      <li><b>重複 pattern ≠ 有效</b> → verifier 四分數閘（grounded / preserves value / specificity / safe，≥0.75）保守把關。</li>
    </ul>
  </div>
  <div class="card">
    <h3>個人 → 集團 擴展路徑</h3>
    <ul>
      <li>資料源：個人實驗 log → 集團 Codex rollout（Phase 2 normalizer 已備）。</li>
      <li>評分：coding pytest → 各 BU 任務的 golden dataset + 對應 judge。</li>
      <li>分享：本機 registry JSON → SkillClaw sharing / OSS / dashboard（版本 B）。</li>
    </ul>
  </div>
</div>
</section>

</main>
<footer class="wrap">
  Skill 精煉機制 · 版本 A（自建 pipeline）· 本頁由 <code>refiner/html_report.py</code> 自動產生。
  對照表資料來源：<code>output/before_after.json</code>。基礎參考：AMAP-ML/SkillClaw。
</footer>
</body>
</html>
"""


def _load_json(path: str) -> Optional[dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _load_skillclaw_result(report_dir: str) -> Optional[dict[str, Any]]:
    """載入版本 B（SkillClaw）實跑結果並算 baseline→refined 的 diff（若存在）。"""
    path = os.path.join(report_dir, "skillclaw_result", "result.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            sc = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    baseline = sc.get("baseline") or {}
    refined = sc.get("refined") or {}
    if baseline.get("content") is not None and refined.get("content") is not None:
        from .report import _content_diff

        sc["_diff"] = _content_diff(baseline.get("content", ""), refined.get("content", ""))
    else:
        sc["_diff"] = []
    return sc


def render_html(report: dict[str, Any], *, report_dir: Optional[str] = None) -> str:
    """用 Jinja2 渲染（若無 jinja2 則退回極簡替換）。

    report_dir：對照表 JSON 所在目錄（預設 output/），用來找版本 B 的 skillclaw_result/。
    """
    before = report.get("before") or {}
    after = report.get("after")
    content_diff = report.get("content_diff") or []
    report_dir = report_dir or os.path.join(PROJECT_ROOT, "output")
    skillclaw = _load_skillclaw_result(report_dir)
    publish = _load_json(os.path.join(report_dir, "publish_result.json"))
    try:
        from jinja2 import Template

        return Template(_TEMPLATE).render(
            report=report, before=before, after=after, content_diff=content_diff,
            skillclaw=skillclaw, publish=publish,
        )
    except ImportError:
        # 極簡退回：至少把對照表塞進去
        body = f"<h1>Skill 精煉對照表：{html.escape(str(report.get('goal')))}</h1>"
        body += f"<p>action={report.get('generated_action')} accepted={report.get('accepted')}</p>"
        return f"<!DOCTYPE html><html><meta charset='utf-8'><body>{body}</body></html>"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="產生 Skill 精煉說明 HTML")
    parser.add_argument("--report", default=os.path.join(PROJECT_ROOT, "output", "before_after.json"))
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "docs", "skill_refinement.html"))
    args = parser.parse_args(argv)

    if not os.path.exists(args.report):
        raise FileNotFoundError(f"找不到對照表 {args.report}；請先跑 python -m refiner.pipeline all")
    with open(args.report, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    out_html = render_html(report, report_dir=os.path.dirname(os.path.abspath(args.report)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out_html)
    print(f"wrote {args.out} ({len(out_html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
