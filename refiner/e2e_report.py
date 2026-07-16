"""渲染 general 場景 E2E 測試報告 → docs/e2e_general_test_report.html。

單一檔、內嵌 CSS、可離線開。資料來源：output/e2e_general/result.json。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

from .report import _content_diff

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>General 場景 E2E 測試報告</title>
<style>
  :root{--bg:#0f1116;--panel:#171a21;--panel2:#1e222b;--ink:#e7eaf0;--muted:#9aa3b2;
    --line:#2a2f3a;--accent:#5b9dff;--good:#3fb950;--warn:#d29922;--bad:#f85149;--chip:#232838;--purple:#a371f7;
    --add:#123a20;--del:#3a1214;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;font-size:15px;
    font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans TC","Microsoft JhengHei",sans-serif}
  header{padding:44px 24px 30px;background:radial-gradient(120% 140% at 20% 0%,#1c2740,#0f1116 60%);border-bottom:1px solid var(--line)}
  .wrap{max-width:1120px;margin:0 auto;padding:0 24px}
  h1{font-size:30px;margin:0 0 6px} h2{font-size:22px;margin:0 0 4px}
  h3{font-size:16.5px;margin:20px 0 8px;color:#cdd6e6}
  .sub{color:var(--muted);font-size:14.5px}
  .lead{color:#c7d0de;font-size:14.5px;margin:2px 0 14px;border-left:3px solid var(--accent);padding-left:12px}
  section{margin:34px 0}
  .sechead{display:flex;align-items:baseline;gap:10px;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:6px}
  .secno{color:var(--accent);font-weight:700;font-size:15px;background:#131a28;border:1px solid var(--line);border-radius:8px;padding:2px 9px}
  .toc{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
  .toc a{background:var(--chip);color:#cdd6e6;text-decoration:none;padding:6px 12px;border-radius:20px;font-size:13px;border:1px solid var(--line)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
  @media(max-width:860px){.grid{grid-template-columns:1fr}}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}
  th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
  th{background:var(--panel2);color:#cdd6e6}
  tr:nth-child(even) td{background:#141821}
  code{font-family:Consolas,Menlo,monospace;font-size:12.5px;color:#e6c07b}
  pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto;font-size:12.5px;color:#c8d2e0;white-space:pre-wrap}
  .badge{display:inline-block;padding:1px 8px;border-radius:6px;font-size:11.5px;font-weight:600}
  .b-rule{background:#0f2a1a;color:#6fdd8b;border:1px solid #235537}
  .b-llm{background:#2c2410;color:#e3c169;border:1px solid #574718}
  .ok{color:var(--good)} .no{color:var(--bad)} .mid{color:var(--warn)}
  .callout{border-left:3px solid var(--accent);background:#141a26;padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:14px}
  .callout.warn{border-color:var(--warn);background:#241f14}
  .callout.good{border-color:var(--good);background:#132116}
  .kpi{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
  .kpi .box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:110px;flex:1}
  .kpi .n{font-size:22px;font-weight:700} .kpi .l{color:var(--muted);font-size:12px}
  .bar-bg{background:#0b0d12;border:1px solid var(--line);border-radius:5px;height:11px;overflow:hidden;padding:1px;min-width:80px}
  .bar{height:9px;border-radius:5px;background:linear-gradient(90deg,#3fb950,#5b9dff)}
  .delta-pos{color:var(--good);font-weight:700} .delta-neg{color:var(--bad);font-weight:700} .delta-zero{color:var(--muted)}
  .diff .add{background:var(--add);color:#7ee787;display:block} .diff .del{background:var(--del);color:#ff9a9a;display:block}
  .diff .hunk{color:var(--accent);display:block} .diff .ctx{color:var(--muted);display:block}
  footer{color:var(--muted);font-size:12px;padding:30px 24px;border-top:1px solid var(--line);margin-top:40px}
  a{color:var(--accent)} .mut{color:var(--muted)} ul{margin:8px 0;padding-left:22px} li{margin:3px 0}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>General 場景 E2E 測試報告</h1>
  <div class="sub">以「新聞查詢與綜整」為主的 general 場景，用 Gemini 同時當 runner（實際執行）與 judge（評分），跑完整精煉 pipeline 並回測前後差異。</div>
  <div class="sub mut">LLM：{{ report.llm.provider }} / {{ report.llm.model }} · 模式：{{ report.mode }} · 目標 skill：{{ report.goal }}</div>
  <nav class="toc">
    <a href="#s0">0 誠實聲明</a>
    <a href="#s1">1 評測分數</a>
    <a href="#s2">2 優化前後 skill</a>
    <a href="#s3">3 judge prompt</a>
    <a href="#s4">4 回測前後</a>
    <a href="#s5">5 對話紀錄</a>
  </nav>
</div></header>

<main class="wrap">

<section id="s0">
  <div class="sechead"><span class="secno">0</span><h2>誠實聲明（測試設定）</h2></div>
  <div class="callout warn">
    <ul style="margin:0">
      <li><b>grounded（非即時查詢）</b>：本測試離線、無網路。「新聞」是附在每個 task 的 <code>sources.md</code> 來源材料；Gemini 依 skill 綜整這些材料，<b>不假裝有即時查詢</b>。</li>
      <li><b>Gemini 身兼兩角</b>：runner（依 skill 實際產出綜整）＋ judge（評「產出 vs 來源」的完成度/品質）。</li>
      <li><b>改善的主要證據</b>＝第 4 節「回測」：baseline skill 與 refined skill 各自真跑一次、由 judge 評分對照。第 5 節對話裡的「使用者後續回饋」是<b>預寫腳本（illustrative）</b>，僅用來示範規則式 completion detector，非改善證據。</li>
    </ul>
  </div>
</section>

<section id="s1">
  <div class="sechead"><span class="secno">1</span><h2>詳細評測分數</h2></div>
  <p class="lead">各 skill 變體在每個 general task 的 Gemini judge 完成度、達標來源（規則/LLM）、效率與綜合分。</p>
  <div class="card">
    <div class="kpi">
      <div class="box"><div class="n">{{ report.variant_scores|length }}</div><div class="l">變體×task session</div></div>
      <div class="box"><div class="n">{{ report.action }}</div><div class="l">精煉動作</div></div>
      <div class="box"><div class="n {{ 'ok' if report.accepted else 'no' }}">{{ '採用' if report.accepted else '未採用' }}</div><div class="l">發布閘</div></div>
      {% if report.verify %}<div class="box"><div class="n">{{ report.verify.score }}</div><div class="l">verify 分數</div></div>{% endif %}
    </div>
    <table>
      <tr><th>task</th><th>變體</th><th>完成度</th><th>達標來源</th><th>信心</th><th>效率</th><th>綜合分</th><th>成功</th></tr>
      {% for r in report.variant_scores %}
      <tr>
        <td>{{ r.task_id }}</td><td><code>{{ r.variant }}</code></td>
        <td>{{ r.completion }}</td>
        <td>{% if r.completion_source %}<span class="badge b-{{ r.completion_source }}">{{ r.completion_source }}</span>{% else %}—{% endif %}</td>
        <td>{{ r.completion_confidence }}</td><td>{{ r.efficiency_score }}</td>
        <td><b>{{ r.score }}</b></td>
        <td class="{{ 'ok' if r.success else 'no' }}">{{ '✓' if r.success else '✗' }}</td>
      </tr>
      {% endfor %}
    </table>
    <p class="mut">達標來源 <span class="badge b-rule">rule</span>＝規則式 detector（零 LLM，靠使用者後續回饋訊號）；
    <span class="badge b-llm">llm</span>＝detector 信心不足退回 Gemini judge。精煉理由：{{ report.rationale }}</p>
  </div>
</section>

<section id="s2">
  <div class="sechead"><span class="secno">2</span><h2>優化前後 skill 比較</h2></div>
  <p class="lead">baseline（精煉前）vs refined（Gemini 從勝出變體證據萃取的精煉版）。</p>
  <div class="grid">
    <div class="card">
      <h3>Before（baseline）</h3>
      <p class="mut">{{ report.baseline_skill.skill_id }} · <b>{{ report.baseline_skill.name }}</b></p>
      <p class="mut">{{ report.baseline_skill.description }}</p>
      <pre>{{ report.baseline_skill.content }}</pre>
    </div>
    <div class="card">
      <h3>After（refined）</h3>
      {% if report.refined_skill %}
      <p class="mut">{{ report.refined_skill.skill_id }} · <b>{{ report.refined_skill.name }}</b></p>
      <p class="mut">{{ report.refined_skill.description }}</p>
      <pre>{{ report.refined_skill.content }}</pre>
      {% else %}<p class="mut">（未產生採用的精煉版）</p>{% endif %}
    </div>
  </div>
  {% if content_diff %}
  <div class="card"><h3>內容 diff（baseline → refined）</h3>
    <pre class="diff">{% for d in content_diff %}<span class="{{ d.kind }}">{{ d.text }}</span>{% endfor %}</pre>
  </div>
  {% endif %}
</section>

<section id="s3">
  <div class="sechead"><span class="secno">3</span><h2>Gemini 當 judge 用的 prompt</h2></div>
  <p class="lead">評分用到兩個 judge：① 變體評分階段的通用 judge；② 回測階段的 grounded judge（會看來源，能核對涵蓋度/忠實度）。</p>
  <div class="card">
    <h3>① 通用 judge（變體評分 / detector fallback）— <code>GENERIC_JUDGE_SYSTEM</code></h3>
    <p class="mut">只看 trajectory＋summary，評 task_completion / response_quality。</p>
    <pre>{{ report.judge_prompt_general }}</pre>
    <h3>② Grounded judge（第 4 節回測用）— <code>GROUNDED_JUDGE_SYSTEM</code></h3>
    <p class="mut"><b>會同時看「來源材料＋需求驗收點＋產出」</b>，逐項核對 coverage / faithfulness / conflict_handling / format，
    捏造或漏來源會重扣。這比只看文字的通用 judge 更能反映 grounded 任務的真實品質。</p>
    <pre>{{ report.judge_prompt_grounded }}</pre>
  </div>
</section>

<section id="s4">
  <div class="sechead"><span class="secno">4</span><h2>回測：優化前 vs 優化後（實際產出＋評分）</h2></div>
  <p class="lead">同一批 task，baseline skill 與 refined skill 各讓 Gemini 真跑一次、各由 judge 評完成度，直接看出改善（delta &gt; 0）或退步（照實呈現）。</p>
  {% for b in report.backtest %}
  <div class="card">
    <h3>{{ b.task_id }}
      {% if b.delta is not none %}
        <span class="{{ 'delta-pos' if b.delta > 0 else ('delta-neg' if b.delta < 0 else 'delta-zero') }}">（Δ完成度 {{ '%+.3f'|format(b.delta) }}）</span>
      {% endif %}
    </h3>
    <table>
      <tr><th style="width:8%"></th><th style="width:12%">完成度</th><th>Gemini 實際產出 ＋ judge rationale</th></tr>
      <tr>
        <td><b>Before</b><br><span class="mut">baseline</span></td>
        <td>{{ b.baseline.completion }}{% if b.baseline.checks %}<br><span class="mut" style="font-size:11px">涵蓋{{ b.baseline.checks.coverage }}/忠實{{ b.baseline.checks.faithfulness }}/衝突{{ b.baseline.checks.conflict_handling }}/格式{{ b.baseline.checks.format }}</span>{% endif %}</td>
        <td><pre>{{ b.baseline.output }}</pre><p class="mut">judge：{{ b.baseline.rationale }}</p></td>
      </tr>
      <tr>
        <td><b>After</b><br><span class="mut">refined</span></td>
        <td class="{{ 'ok' if (b.delta is not none and b.delta > 0) else '' }}">{{ b.refined.completion }}{% if b.refined.checks %}<br><span class="mut" style="font-size:11px">涵蓋{{ b.refined.checks.coverage }}/忠實{{ b.refined.checks.faithfulness }}/衝突{{ b.refined.checks.conflict_handling }}/格式{{ b.refined.checks.format }}</span>{% endif %}</td>
        <td><pre>{{ b.refined.output }}</pre><p class="mut">judge：{{ b.refined.rationale }}</p></td>
      </tr>
    </table>
  </div>
  {% endfor %}
</section>

<section id="s5">
  <div class="sechead"><span class="secno">5</span><h2>對話紀錄（實跑 session）</h2></div>
  <p class="lead">每個 session 的實際內容：turn 1 是 Gemini 依 skill 產出的綜整；後續 turn 是<b>預寫的使用者回饋（illustrative，供 detector）</b>。</p>
  {% for s in report.sessions %}
  <div class="card">
    <h3><code>{{ s.variant }}</code> × {{ s.task_id }}</h3>
    {% for t in s.turns %}
      {% if t.response_text %}
      <p class="mut" style="margin:6px 0 2px">🧑 {{ t.prompt_text }}</p>
      <pre>{{ t.response_text }}</pre>
      {% else %}
      <p style="margin:6px 0"><span class="badge b-rule">使用者回饋(腳本)</span> {{ t.prompt_text }}</p>
      {% endif %}
    {% endfor %}
    {% if s.completion_signals %}<p class="mut">detector 命中訊號：{% for sig in s.completion_signals %}{{ sig.type }} {% endfor %}</p>{% endif %}
  </div>
  {% endfor %}
</section>

</main>
<footer class="wrap">
  General 場景 E2E 測試報告 · 由 <code>refiner/e2e_report.py</code> 產生（單一檔、內嵌 CSS、離線可開）。
  Gemini <code>{{ report.llm.model }}</code> 同時當 runner + judge。資料：<code>output/e2e_general/result.json</code>。
</footer>
</body>
</html>
"""


def render_report(report: dict[str, Any]) -> str:
    from jinja2 import Template

    diff = []
    if report.get("refined_skill") and report.get("baseline_skill"):
        diff = _content_diff(report["baseline_skill"].get("content", ""), report["refined_skill"].get("content", ""))
    return Template(_TEMPLATE).render(report=report, content_diff=diff)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="產生 general E2E 測試報告 HTML")
    parser.add_argument("--result", default=os.path.join(PROJECT_ROOT, "output", "e2e_general", "result.json"))
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "docs", "e2e_general_test_report.html"))
    args = parser.parse_args(argv)
    with open(args.result, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    html = render_report(report)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {args.out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
