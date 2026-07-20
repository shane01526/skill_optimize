"""渲染「通用 vs 專用 skill」對照的深難 agentic E2E 報告 → docs/e2e_agentic_hard_report.html。

讀入兩份 result.json（generic = ops-workflow 通用 SOP、specialized = ops-approval 領域專用），
並排對照哪一套（若有）能把弱 baseline 拉開。單一內嵌 CSS 檔、可離線開。

本輪核心：環境已『移除硬性防呆』，四軸難度（多相依步驟 / 政策衝突 / 長 horizon 預算 / 無防呆）。
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

from .report import _content_diff

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

# case.json 的 8 筆申請與正解（供 §1 表格；與 golden/agentic_e2e_hard 對齊）
_CASE_ROWS = [
    ("R1", "normal", 10, 800, "-", "-", "退（base 窗內）"),
    ("R2", "normal", 45, 500, "-", "-", "不退（逾期）"),
    ("R3", "VIP", 45, 1200, "-", "-", "退（VIP 窗；base 說不、VIP 說可 → 政策衝突）"),
    ("R4", "VIP", 20, 900, "FINAL", "-", "不退（FINAL 蓋過 VIP → 政策衝突）"),
    ("R5", "normal", 5, 2000, "-", "✓", "不退（fraud，最高優先；看似新且大額的陷阱）"),
    ("R6", "VIP", 55, 1500, "-", "-", "退（VIP 窗）"),
    ("R7", "normal", 25, 700, "-", "-", "eligible 但超每日預算 → defer"),
    ("R8", "VIP", 10, 1000, "-", "-", "退"),
]

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
  :root{--bg:#0f1116;--panel:#171a21;--panel2:#1e222b;--ink:#e7eaf0;--muted:#9aa3b2;
    --line:#2a2f3a;--accent:#5b9dff;--good:#3fb950;--warn:#d29922;--bad:#f85149;--chip:#232838;--purple:#a371f7;
    --add:#123a20;--del:#3a1214;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;font-size:15px;
    font-family:-apple-system,"Segoe UI",Roboto,"Noto Sans TC","Microsoft JhengHei",sans-serif}
  header{padding:44px 24px 30px;background:radial-gradient(120% 140% at 20% 0%,#1c2740,#0f1116 60%);border-bottom:1px solid var(--line)}
  .wrap{max-width:1180px;margin:0 auto;padding:0 24px}
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
  @media(max-width:900px){.grid{grid-template-columns:1fr}}
  table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.5px}
  th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
  th{background:var(--panel2);color:#cdd6e6}
  tr:nth-child(even) td{background:#141821}
  code{font-family:Consolas,Menlo,monospace;font-size:12.5px;color:#e6c07b}
  pre{background:#0b0d12;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto;font-size:12.5px;color:#c8d2e0;white-space:pre-wrap}
  .badge{display:inline-block;padding:1px 8px;border-radius:6px;font-size:11.5px;font-weight:600}
  .b-rule{background:#0f2a1a;color:#6fdd8b;border:1px solid #235537}
  .b-gen{background:#2c2410;color:#e3c169;border:1px solid #574718}
  .b-spec{background:#241033;color:#c79bf7;border:1px solid #4a2b6b}
  .ok{color:var(--good)} .no{color:var(--bad)} .mid{color:var(--warn)}
  .callout{border-left:3px solid var(--accent);background:#141a26;padding:10px 14px;border-radius:0 8px 8px 0;margin:12px 0;font-size:14px}
  .callout.warn{border-color:var(--warn);background:#241f14}
  .callout.good{border-color:var(--good);background:#132116}
  .kpi{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
  .kpi .box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px 16px;min-width:120px;flex:1}
  .kpi .n{font-size:22px;font-weight:700} .kpi .l{color:var(--muted);font-size:12px}
  .delta-pos{color:var(--good);font-weight:700} .delta-neg{color:var(--bad);font-weight:700} .delta-zero{color:var(--muted)}
  .diff .add{background:var(--add);color:#7ee787;display:block} .diff .del{background:var(--del);color:#ff9a9a;display:block}
  .diff .hunk{color:var(--accent);display:block} .diff .ctx{color:var(--muted);display:block}
  footer{color:var(--muted);font-size:12px;padding:30px 24px;border-top:1px solid var(--line);margin-top:40px}
  a{color:var(--accent)} .mut{color:var(--muted)} ul{margin:8px 0;padding-left:22px} li{margin:3px 0}
</style>
</head>
<body>
<header><div class="wrap">
  <h1>{{ title }}</h1>
  <div class="sub">{{ lead }}</div>
  <div class="sub mut">LLM：{{ generic.llm.provider }} / {{ generic.llm.model }}（同時當 runner）· 模式：{{ generic.mode }} · rollout：{{ generic.rollouts }} 次 · 達標＝環境最終狀態程式驗證</div>
  <nav class="toc">
    <a href="#s0">0 誠實聲明</a>
    <a href="#s1">1 任務與陷阱</a>
    <a href="#s2">2 通用 vs 專用 回測對照</a>
    <a href="#s3">3 兩家族精煉前後</a>
    <a href="#s4">4 工具軌跡</a>
    <a href="#s5">5 誠實結論</a>
  </nav>
</div></header>

<main class="wrap">

<section id="s0">
  <div class="sechead"><span class="secno">0</span><h2>誠實聲明（本輪設定）</h2></div>
  <div class="callout warn">
    <ul style="margin:0">
      <li><b>為什麼有這一輪</b>：前一輪 agentic 任務第 4 次撞天花板——連弱 baseline 都拿滿分。主因是任務步數少、<b>且環境有硬性防呆</b>（違規寫入被擋，等於幫 baseline 兜底）。本輪針對性拉滿難度。</li>
      <li><b>四軸難度</b>：① 多相依步驟（查政策→判資格→排序→受預算核銷→<b>連動扣點</b>→通知）；② <b>政策衝突需推理</b>（fraud &gt; FINAL 不可退 &gt; VIP 窗 &gt; 基本窗）；③ <b>長 horizon</b>（每日預算上限，須累計已退金額、超過就 defer）；④ <b>移除硬性防呆</b>。</li>
      <li><b>關鍵：環境不再把關</b>：<code>issue_refund</code> / <code>deduct_loyalty</code> 照單全收、永遠回 ok，不檢查資格/預算/重複。於是「不查就寫」「退不該退的」「超預算」「漏扣點」的錯誤會<b>真的落地</b>，只能靠 <code>verify()</code> 事後比對正確最終狀態抓出來——這次 <code>no_illegal_writes</code> 會真的變動。</li>
      <li><b>達標＝程式客觀驗證（非 LLM）</b>：<code>completion = 0.7·state_correct + 0.2·order_correct + 0.1·no_illegal_writes</code>。驗證器見 <code>refiner/sim_env.py::make_approval_env</code>。</li>
      <li><b>本報告在比什麼</b>：同一個深難任務，用<b>通用 SOP skill</b>（<code>ops-workflow</code>）與<b>領域專用 skill</b>（<code>ops-approval</code>，寫死了優先序/預算/扣點）各跑一次完整精煉＋回測，看哪一套能把 baseline 拉開。</li>
      <li><b>改善主證據＝第 2 節回測</b>（baseline vs refined 真跑工具迴圈、程式驗證）。變體評分階段仍受 <code>conversation.json</code> 腳本回饋影響（illustrative，非改善證據）。每組跑 {{ generic.rollouts }} 次取 mean±std。</li>
    </ul>
  </div>
</section>

<section id="s1">
  <div class="sechead"><span class="secno">1</span><h2>任務與陷阱（8 筆申請）</h2></div>
  <p class="lead">政策：每日預算 <code>5000</code>、VIP 窗 <code>60</code> 天、一般窗 <code>30</code> 天。處理順序＝VIP 優先、其餘按 id 升冪，逐筆累計預算、超過 defer；每筆退款連動扣 <code>floor(金額/10)</code> 點。</p>
  <div class="card">
    <table>
      <tr><th>id</th><th>tier</th><th>天數</th><th>金額</th><th>promo</th><th>fraud</th><th>正解</th></tr>
      {% for r in case_rows %}
      <tr><td><code>{{ r[0] }}</code></td><td>{{ r[1] }}</td><td>{{ r[2] }}</td><td>{{ r[3] }}</td><td>{{ r[4] }}</td>
        <td class="{{ 'no' if r[5]=='✓' else 'mut' }}">{{ r[5] }}</td><td>{{ r[6] }}</td></tr>
      {% endfor %}
    </table>
    <p class="mut"><b>正解</b>：退款 <code>{R3,R6,R8,R1}</code> 共 4500（R7 700 會破 5000 → defer）；連動扣點 <code>{C3:120, C6:150, C8:100, C1:80}</code>。
    R2（逾期）、R4（FINAL）、R5（fraud）不退。弱 baseline 若不查政策就全退 8 筆、又不扣點 → <code>state_correct</code> 低、<code>no_illegal_writes=0</code>。</p>
  </div>
</section>

<section id="s2">
  <div class="sechead"><span class="secno">2</span><h2>通用 vs 專用：回測對照</h2></div>
  <p class="lead">同一深難任務，兩套 skill 家族各自 baseline → refined 真跑 {{ generic.rollouts }} 次工具迴圈、由環境最終狀態評分。Δ&gt;0＝精煉後把 baseline 拉開。</p>
  <div class="kpi">
    <div class="box"><div class="l"><span class="badge b-gen">通用 ops-workflow</span> baseline→refined Δ(mean)</div><div class="n {{ 'delta-pos' if generic.delta_mean and generic.delta_mean>0 else 'delta-zero' }}">{{ '%+.3f'|format(generic.delta_mean) if generic.delta_mean is not none else '—' }}</div></div>
    <div class="box"><div class="l"><span class="badge b-spec">專用 ops-approval</span> baseline→refined Δ(mean)</div><div class="n {{ 'delta-pos' if spec.delta_mean and spec.delta_mean>0 else 'delta-zero' }}">{{ '%+.3f'|format(spec.delta_mean) if spec.delta_mean is not none else '—' }}</div></div>
    <div class="box"><div class="l">baseline mean（越低＝任務越拉得開）</div><div class="n">通用 {{ generic.baseline_mean }} · 專用 {{ spec.baseline_mean }}</div></div>
  </div>

  {% for fam in [generic, spec] %}
  <div class="card">
    <h3>{% if fam.kind=='generic' %}<span class="badge b-gen">通用 ops-workflow</span>{% else %}<span class="badge b-spec">專用 ops-approval</span>{% endif %} 回測</h3>
    {% for b in fam.backtest %}
    <h3 style="margin-top:16px">{{ b.task_id }}
      {% if b.delta is not none %}<span class="{{ 'delta-pos' if b.delta>0 else ('delta-neg' if b.delta<0 else 'delta-zero') }}">（Δmean {{ '%+.3f'|format(b.delta) }}）</span>{% endif %}
    </h3>
    <table>
      <tr><th style="width:9%"></th><th style="width:26%">完成度 mean±std（三項 checks）</th><th>違規明細（env 事後抓）</th></tr>
      <tr>
        <td><b>Before</b><br><span class="mut">baseline</span></td>
        <td>{{ b.baseline.completion }} <span class="mut">± {{ b.baseline.completion_std }}</span>
          {% if b.baseline.checks %}<br><span class="mut" style="font-size:11px">{% for k,v in b.baseline.checks.items() %}{{ k }}={{ v }} {% endfor %}</span>{% endif %}</td>
        <td>{% if b.baseline.violations %}<span class="no" style="font-size:12px">{% for e in b.baseline.violations %}· {{ e }}<br>{% endfor %}</span>{% else %}<span class="ok">無違規</span>{% endif %}</td>
      </tr>
      <tr>
        <td><b>After</b><br><span class="mut">refined</span></td>
        <td class="{{ 'ok' if (b.delta is not none and b.delta>0) else '' }}">{{ b.refined.completion }} <span class="mut">± {{ b.refined.completion_std }}</span>
          {% if b.refined.checks %}<br><span class="mut" style="font-size:11px">{% for k,v in b.refined.checks.items() %}{{ k }}={{ v }} {% endfor %}</span>{% endif %}</td>
        <td>{% if b.refined.violations %}<span class="no" style="font-size:12px">{% for e in b.refined.violations %}· {{ e }}<br>{% endfor %}</span>{% else %}<span class="ok">無違規</span>{% endif %}</td>
      </tr>
    </table>
    {% endfor %}
  </div>
  {% endfor %}
</section>

<section id="s3">
  <div class="sechead"><span class="secno">3</span><h2>兩家族：精煉前後 skill</h2></div>
  {% for fam in [generic, spec] %}
  <div class="card">
    <h3>{% if fam.kind=='generic' %}<span class="badge b-gen">通用 ops-workflow</span>{% else %}<span class="badge b-spec">專用 ops-approval</span>{% endif %}
      · 動作：<code>{{ fam.action or '（無）' }}</code>
      {% if fam.verify %}· verify {{ fam.verify.score }}（{{ '通過' if fam.accepted else '未過' }}門檻 {{ fam.verify.threshold }}）{% endif %}</h3>
    <div class="grid">
      <div><h3>Before（baseline）</h3><pre>{{ fam.baseline_skill.content }}</pre></div>
      <div><h3>After（refined）</h3>{% if fam.refined_skill %}<pre>{{ fam.refined_skill.content }}</pre>{% else %}<p class="mut">（未產生採用的精煉版）</p>{% endif %}</div>
    </div>
    {% if fam.diff %}<h3>內容 diff</h3><pre class="diff">{% for d in fam.diff %}<span class="{{ d.kind }}">{{ d.text }}</span>{% endfor %}</pre>{% endif %}
  </div>
  {% endfor %}
</section>

<section id="s4">
  <div class="sechead"><span class="secno">4</span><h2>代表性工具軌跡</h2></div>
  <p class="lead">各家族 baseline 與 refined 的一條實際工具呼叫軌跡＋最終環境狀態（回測第 1 次 rollout 的代表樣本）。</p>
  {% for fam in [generic, spec] %}
  <div class="card">
    <h3>{% if fam.kind=='generic' %}<span class="badge b-gen">通用 ops-workflow</span>{% else %}<span class="badge b-spec">專用 ops-approval</span>{% endif %}</h3>
    {% for b in fam.backtest %}
    <p class="mut" style="margin:8px 0 2px">{{ b.task_id }} · baseline</p>
    <pre>{{ b.baseline.output }}</pre>
    <p class="mut" style="margin:8px 0 2px">{{ b.task_id }} · refined</p>
    <pre>{{ b.refined.output }}</pre>
    {% endfor %}
  </div>
  {% endfor %}
</section>

<section id="s5">
  <div class="sechead"><span class="secno">5</span><h2>誠實結論</h2></div>
  <div class="callout {{ 'good' if verdict.separated else 'warn' }}">
    {{ verdict.text }}
  </div>
</section>

</main>
<footer class="wrap">
  深難 Agentic 對照報告 · 由 <code>refiner/e2e_compare_report.py</code> 產生（單一檔、內嵌 CSS、離線可開）。
  資料：<code>output/agentic_hard_generic/result.json</code> + <code>output/agentic_hard_specialized/result.json</code>。
</footer>
</body>
</html>
"""

_DEFAULT_TITLE = "深難 Agentic 任務：通用 vs 專用 skill 對照報告"
_DEFAULT_LEAD = ("退款核准（四軸難度：多相依步驟＋政策衝突＋每日預算 horizon＋環境無硬性防呆），"
                 "比較通用 SOP skill 與領域專用 skill 誰能把弱 baseline 拉開。")


def _fam_view(result: dict[str, Any], kind: str) -> dict[str, Any]:
    """把單一 result.json 整理成報告需要的家族視圖。"""
    bt = result.get("backtest", [])
    deltas = [b["delta"] for b in bt if b.get("delta") is not None]
    bvals = [b["baseline"]["completion"] for b in bt if b["baseline"].get("completion") is not None]
    delta_mean = round(sum(deltas) / len(deltas), 3) if deltas else None
    baseline_mean = round(sum(bvals) / len(bvals), 3) if bvals else None
    diff = []
    if result.get("refined_skill") and result.get("baseline_skill"):
        diff = _content_diff(result["baseline_skill"].get("content", ""),
                             result["refined_skill"].get("content", ""))
    return {
        "kind": kind,
        "llm": result.get("llm", {}),
        "mode": result.get("mode"),
        "rollouts": result.get("rollouts"),
        "backtest": bt,
        "delta_mean": delta_mean,
        "baseline_mean": baseline_mean,
        "baseline_skill": result.get("baseline_skill", {}),
        "refined_skill": result.get("refined_skill"),
        "action": result.get("action"),
        "verify": result.get("verify"),
        "accepted": result.get("accepted"),
        "diff": diff,
    }


def _verdict(generic: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """依實際數字生成誠實結論（不寫死）。"""
    g_base, s_base = generic["baseline_mean"], spec["baseline_mean"]
    g_d, s_d = generic["delta_mean"], spec["delta_mean"]
    parts = [
        f"通用家族：baseline mean={g_base}、精煉後 Δmean={'%+.3f' % g_d if g_d is not None else '—'}；",
        f"專用家族：baseline mean={s_base}、精煉後 Δmean={'%+.3f' % s_d if s_d is not None else '—'}。",
    ]
    # 「拉開」的定義：baseline 沒有天花板（<0.9），代表任務確實難到讓弱 skill 失分
    g_sep = g_base is not None and g_base < 0.9
    s_sep = s_base is not None and s_base < 0.9
    separated = g_sep or s_sep
    if separated:
        who = []
        if s_sep:
            who.append("專用 ops-approval")
        if g_sep:
            who.append("通用 ops-workflow")
        parts.append(
            f"本輪終於<b>打破天花板</b>：{'、'.join(who)} 家族的弱 baseline 在四軸難度＋無防呆下真的失分"
            f"（baseline mean 明顯低於 1.0），skill 差異首次在最客觀的程式驗證 gate 下顯現。"
            "移除環境防呆讓「不查政策就亂退／退 fraud/FINAL/逾期／超預算／漏扣點」的錯誤真的落地，是關鍵。"
        )
        if s_base is not None and g_base is not None:
            if s_base < g_base:
                parts.append("其中<b>領域專用 skill 的 baseline 更低</b>——專用任務對通用 SOP 更不友善，"
                             "也印證『把領域規則寫進 skill』確有價值。")
            elif g_base < s_base:
                parts.append("兩套家族的 baseline 都被拉低，通用家族甚至更低，顯示難度來自任務本身而非 skill 措辭。")
        # 精煉方向對比：專用把 baseline 拉滿、通用沒幫上（甚至退步）＝本輪最重要的洞見
        if s_d is not None and g_d is not None and s_d > 0.15 and g_d <= 0:
            parts.append(
                f"<b>最關鍵的對比</b>：把同一批證據餵給精煉，<b>領域專用 skill 精煉後大幅拉高</b>"
                f"（Δ={'%+.3f' % s_d}，refined 達 {spec['backtest'][0]['refined']['completion']}），"
                f"而<b>通用 SOP skill 精煉後沒有幫助、甚至退步</b>（Δ={'%+.3f' % g_d}）。"
                "這正是 skill 精煉的核心價值：對規則明確的領域任務，光有『先讀後寫、逐條核對』的通用紀律不夠，"
                "必須把<b>領域規則（政策優先序、每日預算累計、連動扣點）寫進 skill</b>——通用 SOP 缺了這些領域知識，"
                "模型仍會踩爆 fraud/FINAL/超預算/漏扣點的陷阱。"
            )
    else:
        parts.append(
            "即使把難度拉到四軸＋移除環境防呆，兩套家族的弱 baseline <b>仍接近滿分</b>——"
            "gemini-flash 的內建推理已足以處理政策衝突與預算累計。這是第 5 次天花板觀察，照實呈現："
            "要再拉開，需更長 horizon（更多步驟易忘中間狀態）、更隱晦的衝突、或更大的申請批量。"
        )
    return {"separated": separated, "text": " ".join(parts)}


def render_compare(generic_result: dict[str, Any], spec_result: dict[str, Any],
                   *, title: str = _DEFAULT_TITLE, lead: str = _DEFAULT_LEAD) -> str:
    from jinja2 import Template

    generic = _fam_view(generic_result, "generic")
    spec = _fam_view(spec_result, "specialized")
    verdict = _verdict(generic, spec)
    return Template(_TEMPLATE).render(
        title=title, lead=lead, generic=generic, spec=spec,
        case_rows=_CASE_ROWS, verdict=verdict,
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="產生通用 vs 專用 skill 對照的深難 agentic E2E 報告 HTML")
    parser.add_argument("--generic", default=os.path.join(PROJECT_ROOT, "output", "agentic_hard_generic", "result.json"))
    parser.add_argument("--specialized", default=os.path.join(PROJECT_ROOT, "output", "agentic_hard_specialized", "result.json"))
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "docs", "e2e_agentic_hard_report.html"))
    args = parser.parse_args(argv)
    with open(args.generic, "r", encoding="utf-8") as fh:
        generic_result = json.load(fh)
    with open(args.specialized, "r", encoding="utf-8") as fh:
        spec_result = json.load(fh)
    html = render_compare(generic_result, spec_result)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"wrote {args.out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
