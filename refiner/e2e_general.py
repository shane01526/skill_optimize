"""general 場景 E2E 測試 orchestrator（Gemini 同時當 runner + judge）。

自包含流程，不動 refiner/pipeline.py，重用既有 building blocks：
  1. 對每個 (變體×task) 讓 Gemini 真跑產出綜整 → sessions
  2. summarize + evaluate（Gemini judge + 行為 detector + cohort 效率）
  3. aggregate + evolve 精煉出 refined skill + verifier 發布閘
  4. 回測：baseline skill vs refined skill 各在同一批 task 真跑一次、各 judge → 前後對照
  5. 寫 output/e2e_general/result.json

產出獨立報告：docs/e2e_general_test_report.html（見 render_report / e2e_report.py）。

誠實聲明：任務為 grounded（來源材料附在 task/sources.md，非即時查詢）；
conversation.json 的使用者後續回饋僅供 completion detector demo（illustrative），
改善的主要證據是 Gemini judge 對「真實產出 vs 來源」的評分與回測前後對照。
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Optional

from . import aggregation, evaluator, execution, summarizer, verifier
from .llm import LLMClient
from .normalizer import normalize_experiment_record
from .runner_codex import run_general_variant_on_task, _read_task_prompt, _read_sources, _compose_general_instruction, _load_variant
from .skillmd import build_skill_md, parse_skill_md

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

# 每個 (變體×task) / 每個回測 skill 重複跑的次數，取平均降低單次 LLM variance。
ROLLOUTS = 3


def _p(*parts: str) -> str:
    return os.path.join(PROJECT_ROOT, *parts)


def _stats(values: list[float]) -> dict[str, Any]:
    """回傳 {mean, std, n, scores}（忽略 None）。"""
    import statistics

    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return {"mean": None, "std": None, "n": 0, "scores": []}
    return {
        "mean": round(statistics.fmean(vals), 3),
        "std": round(statistics.pstdev(vals), 3) if len(vals) > 1 else 0.0,
        "n": len(vals),
        "scores": [round(v, 3) for v in vals],
    }


def discover_variants(goal_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(goal_dir, "*", "SKILL.md")))


def discover_tasks(tasks_dir: str) -> list[str]:
    return sorted(d for d in glob.glob(os.path.join(tasks_dir, "*")) if os.path.isdir(d))


def _task_judge(task_dir: str, default: str) -> str:
    """讀 task.json 的 judge 欄位決定該 task 用哪個 judge；未指定用 default。"""
    p = os.path.join(task_dir, "task.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                j = str(json.load(fh).get("judge") or "").strip()
            if j in _CHECK_KEYS:
                return j
        except (json.JSONDecodeError, OSError):
            pass
    return default


def load_baseline_skill(goal_dir: str) -> dict[str, Any]:
    path = os.path.join(goal_dir, "baseline", "SKILL.md")
    if not os.path.exists(path):
        variants = discover_variants(goal_dir)
        path = variants[0]
    with open(path, "r", encoding="utf-8") as fh:
        return parse_skill_md(fh.read(), fallback_name=os.path.basename(goal_dir))


# ------------------------------------------------------------------ #
#  回測：用指定 skill 內容在單一 task 上真跑 Gemini + judge            #
# ------------------------------------------------------------------ #


# 各 judge 用的 check 欄位（依 judge_system 不同而異）
_CHECK_KEYS = {
    "grounded": ("coverage", "faithfulness", "conflict_handling", "format"),
    "ppt_outline": ("coverage", "structure", "granularity", "faithfulness"),
    "cross_doc": ("coverage", "cross_reference", "conflict_handling", "faithfulness"),
    "json_schema": ("schema_valid", "required_coverage", "content_faithfulness"),
}


def _judge_prompt(judge: str) -> str:
    from . import prompts

    return {
        "ppt_outline": prompts.PPT_OUTLINE_JUDGE_SYSTEM,
        "cross_doc": prompts.CROSS_DOC_JUDGE_SYSTEM,
    }.get(judge, prompts.GROUNDED_JUDGE_SYSTEM)


def _run_skill_on_task(llm: LLMClient, skill: dict[str, Any], task_dir: str, task_id: str, label: str,
                       *, judge: str = "grounded") -> dict[str, Any]:
    """用給定 skill 在 task 上真跑 Gemini 產出 + grounded judge，回傳結果。"""
    task_prompt = _read_task_prompt(task_dir)
    sources = _read_sources(task_dir)
    instruction = _compose_general_instruction(task_prompt, sources, skill)
    try:
        output = llm.chat(
            "You are a careful assistant that strictly grounds answers in the given sources.",
            instruction, temperature=0.2, max_tokens=4096,
        )
    except Exception as exc:  # noqa: BLE001
        output = f"[error] {exc}"

    if judge == "json_schema":
        return _score_json_schema(llm, task_dir, task_prompt, sources, output, task_id, label)

    result = _grounded_judge(llm, task_prompt, sources, output, judge=judge)
    keys = _CHECK_KEYS.get(judge, _CHECK_KEYS["grounded"])
    return {
        "task_id": task_id,
        "label": label,
        "output": output,
        "completion": result.get("overall"),
        "checks": {k: result.get(k) for k in keys},
        "rationale": result.get("rationale", ""),
    }


def _validate_json_schema(answer: str, schema: dict[str, Any]) -> dict[str, Any]:
    """程式驗證（非 LLM）：從產出抽 JSON → 用 jsonschema 收集錯誤。

    回傳 {parsed_ok, schema_valid, error_count, errors, required_coverage}。
    這是能真正拉開弱 baseline 的客觀 gate（類似 coding 的 pytest）。
    """
    from .skillmd import extract_json_object

    obj = extract_json_object(answer)
    if obj is None:
        # 抽不出合法 JSON（弱 baseline 常見：夾雜文字/多段/壞括號）
        return {"parsed_ok": False, "schema_valid": False, "error_count": None,
                "errors": ["無法從產出抽出合法 JSON"], "required_coverage": 0.0}

    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except ImportError:
        return {"parsed_ok": True, "schema_valid": None, "error_count": None,
                "errors": ["jsonschema 未安裝"], "required_coverage": None}

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    err_msgs = [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors][:10]

    # required 欄位到位比例（頂層）：給部分分，讓「差一點」與「完全不對」有區別
    req = schema.get("required", []) or []
    present = sum(1 for k in req if isinstance(obj, dict) and k in obj)
    required_coverage = round(present / len(req), 3) if req else 1.0

    return {
        "parsed_ok": True,
        "schema_valid": len(errors) == 0,
        "error_count": len(errors),
        "errors": err_msgs,
        "required_coverage": required_coverage,
    }


def _score_json_schema(llm: LLMClient, task_dir: str, task_prompt: str, sources: str,
                       output: str, task_id: str, label: str) -> dict[str, Any]:
    """json_schema judge：程式驗證(硬) 為主 + LLM 內容忠實度(軟) 為輔，合成 completion。"""
    from .skillmd import extract_json_object

    schema_path = os.path.join(task_dir, "schema.json")
    schema = {}
    if os.path.exists(schema_path):
        with open(schema_path, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
    v = _validate_json_schema(output, schema)

    # 硬指標：schema 全過 → 1.0；否則用 required_coverage 給部分分（上限 0.5，代表「沒真的過」）
    if v["schema_valid"]:
        schema_pass = 1.0
    else:
        schema_pass = round(min(0.5, (v.get("required_coverage") or 0.0) * 0.5), 3)

    # 軟指標：只在有抽出 JSON 時才問 LLM 內容忠實度（省呼叫）
    content = 0.0
    content_rationale = "未抽出 JSON，略過內容評分" if not v["parsed_ok"] else ""
    if v["parsed_ok"]:
        from .prompts import JSON_CONTENT_JUDGE_SYSTEM
        from .skillmd import extract_json_object as _ejo

        payload = json.dumps({"task": task_prompt, "sources": sources, "answer": output}, ensure_ascii=False)
        try:
            raw = llm.chat(JSON_CONTENT_JUDGE_SYSTEM, payload, temperature=0.1, max_tokens=800)
            parsed = _ejo(raw) or {}
            cf = parsed.get("content_faithfulness")
            content = round(max(0.0, min(1.0, float(cf))), 3) if isinstance(cf, (int, float)) and not isinstance(cf, bool) else 0.5
            content_rationale = str(parsed.get("rationale") or "").strip()
        except Exception:  # noqa: BLE001
            content = 0.5

    completion = round(0.7 * schema_pass + 0.3 * content, 3)
    rationale = f"schema_valid={v['schema_valid']} (errors={v['error_count']}); {content_rationale}"
    if v["errors"]:
        rationale += " | " + "; ".join(v["errors"][:5])
    return {
        "task_id": task_id,
        "label": label,
        "output": output,
        "completion": completion,
        "checks": {
            "schema_valid": 1.0 if v["schema_valid"] else 0.0,
            "required_coverage": v.get("required_coverage"),
            "content_faithfulness": content,
        },
        "schema_errors": v["errors"],
        "rationale": rationale,
    }


def _grounded_judge(llm: LLMClient, task_prompt: str, sources: str, answer: str, *, judge: str = "grounded") -> dict[str, Any]:
    """讓 Gemini 核對產出 vs 來源，回各 check + overall。judge 決定用哪個 judge prompt 與 check 欄位。"""
    from .skillmd import extract_json_object

    keys = _CHECK_KEYS.get(judge, _CHECK_KEYS["grounded"])
    payload = json.dumps({"task": task_prompt, "sources": sources, "answer": answer}, ensure_ascii=False)
    try:
        raw = llm.chat(_judge_prompt(judge), payload, temperature=0.1, max_tokens=1200)
        parsed = extract_json_object(raw) or {}
    except Exception:  # noqa: BLE001
        parsed = {}

    def _num(v):
        return round(max(0.0, min(1.0, float(v))), 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    checks = {k: _num(parsed.get(k)) for k in keys}
    overall = _num(parsed.get("overall"))
    if overall is None:
        vals = [v for v in checks.values() if v is not None]
        overall = round(sum(vals) / len(vals), 3) if vals else 0.5
    return {**checks, "overall": overall, "rationale": str(parsed.get("rationale") or "").strip()}


def _backtest_skill(llm: LLMClient, skill: dict[str, Any], task_dir: str, task_id: str, label: str,
                    *, judge: str = "grounded") -> dict[str, Any]:
    """對單一 skill 在 task 上跑 ROLLOUTS 次 Gemini + grounded judge，聚合 mean/std。

    保留第 1 次的完整產出/rationale 供報告展示（代表性樣本），其餘只留分數。
    """
    runs = [_run_skill_on_task(llm, skill, task_dir, task_id, label, judge=judge) for _ in range(ROLLOUTS)]
    stats = _stats([r["completion"] for r in runs])
    rep = runs[0]  # 代表性樣本（第 1 次）
    return {
        "label": label,
        "output": rep["output"],
        "checks": rep["checks"],
        "schema_errors": rep.get("schema_errors"),  # json_schema 任務才有
        "rationale": rep["rationale"],
        "completion": stats["mean"],       # mean 作為代表分數
        "completion_std": stats["std"],
        "n": stats["n"],
        "scores": stats["scores"],
    }


def backtest(llm: LLMClient, baseline: dict[str, Any], refined: dict[str, Any], tasks: list[str],
             *, judge: str = "grounded") -> list[dict[str, Any]]:
    """對每個 task，baseline skill 與 refined skill 各跑 ROLLOUTS 次 Gemini + judge → 前後對照（mean）。"""
    rows: list[dict[str, Any]] = []
    for task_dir in tasks:
        task_id = os.path.basename(task_dir)
        tj = _task_judge(task_dir, judge)
        b = _backtest_skill(llm, baseline, task_dir, task_id, "baseline", judge=tj)
        r = _backtest_skill(llm, refined, task_dir, task_id, "refined", judge=tj)
        delta = None
        if b["completion"] is not None and r["completion"] is not None:
            delta = round(r["completion"] - b["completion"], 3)
        rows.append({"task_id": task_id, "baseline": b, "refined": r, "delta": delta})
    return rows


# ------------------------------------------------------------------ #
#  主流程                                                              #
# ------------------------------------------------------------------ #


def run_e2e(
    goal_dir: str,
    tasks_dir: str,
    output_dir: str,
    *,
    mode: str = "api",
    llm: Optional[LLMClient] = None,
    judge: str = "grounded",
) -> dict[str, Any]:
    llm = llm or LLMClient()
    os.makedirs(output_dir, exist_ok=True)
    variants = [v for v in discover_variants(goal_dir) if os.path.basename(os.path.dirname(v)) != "baseline"]
    tasks = discover_tasks(tasks_dir)

    # 1. 每個 (變體×task) 真跑 Gemini 產出 × ROLLOUTS 次
    records: list[dict[str, Any]] = []
    for vpath in variants:
        for task_dir in tasks:
            task_id = os.path.basename(task_dir)
            for i in range(ROLLOUTS):
                rec = run_general_variant_on_task(
                    skill_md_path=vpath, task_dir=task_dir, task_id=task_id, mode=mode, llm=llm
                )
                rec["rollout_idx"] = i
                records.append(rec)
            print(f"  ran {os.path.basename(os.path.dirname(vpath))} × {task_id} ×{ROLLOUTS}")

    # 2. normalize → summarize → evaluate（judge + detector + 效率）；每個 rollout 各自評分
    sessions = [normalize_experiment_record(r) for r in records]
    for s, r in zip(sessions, records):
        s["agent_output"] = r.get("agent_output")
        s["sources"] = r.get("sources")
        s["task_prompt"] = r.get("task_prompt")
        s["rollout_idx"] = r.get("rollout_idx")
        # session_id 加 rollout 後綴，避免 cohort/dedupe 誤判為同一筆
        s["session_id"] = f"{s['session_id']}#r{r.get('rollout_idx')}"
    summarizer.summarize_sessions(llm, sessions)
    evaluator.evaluate_sessions(llm, sessions, use_judge=True)

    # 3. aggregate + evolve + verify
    groups = aggregation.aggregate_by_skill(sessions)
    baseline = load_baseline_skill(goal_dir)
    existing = [k for k in groups.keys() if k != aggregation.NO_SKILL_KEY]
    # 精煉證據：每個 (變體×task) 只取一個代表 rollout（idx 0），避免 3×36 筆撐爆 evidence 上限
    evidence = _dedupe([s for s in sessions if s.get("rollout_idx") == 0])
    result = execution.evolve_skill_from_sessions(llm, baseline["name"], evidence, baseline, existing)

    refined = None
    verdict = None
    if result and result.get("action") != execution.ACTION_SKIP and result.get("skill"):
        candidate = dict(result["skill"])
        candidate.setdefault("category", "general")
        candidate.setdefault("skill_id", baseline.get("skill_id"))
        verdict = verifier.verify_candidate(llm, candidate, evidence, result["action"], current_skill=baseline, min_score=0.75)
        refined = candidate

    # 4. 回測 baseline vs refined（refined 沒過閘就用 candidate 仍回測，照實呈現）
    refined_for_test = refined or baseline
    backtest_rows = backtest(llm, baseline, refined_for_test, tasks, judge=judge)

    # 依實際回測數字產生「誠實解讀」註記（不寫死結論）
    bvals = [b["baseline"]["completion"] for b in backtest_rows if b["baseline"]["completion"] is not None]
    rvals = [b["refined"]["completion"] for b in backtest_rows if b["refined"]["completion"] is not None]
    b_mean = round(sum(bvals) / len(bvals), 3) if bvals else None
    r_mean = round(sum(rvals) / len(rvals), 3) if rvals else None
    note = None
    if b_mean is not None and r_mean is not None:
        d = round(r_mean - b_mean, 3)
        note = (
            f"回測整體 mean：baseline={b_mean}、refined={r_mean}、Δ={d:+.3f}（grounded judge，{ROLLOUTS} 次平均）。"
        )
        if b_mean >= 0.9:
            note += (
                "baseline 分數已接近上限——代表這個任務對 Gemini 這種強模型而言，"
                "即使用籠統的 baseline skill 也能產出高品質結果，因此「最終品質」上難再由 skill 拉開差距。"
                "這是真實且重要的觀察：skill 精煉的價值在強模型 × 偏易任務時會被稀釋，"
                "差異更會顯現在穩定度（std／成功率）、成本、或更難／限制更嚴的任務上。"
                "（注意：第 1 節變體評分仍受 conversation.json 腳本回饋影響，見誠實聲明。）"
            )

    # 5. 組報告資料
    report = {
        "goal": baseline["name"],
        "mode": mode,
        "llm": {"provider": llm.provider, "model": llm.model},
        "action": (result or {}).get("action"),
        "rationale": (result or {}).get("rationale", ""),
        "verify": verdict,
        "accepted": bool(verdict and verdict.get("accepted")),
        "variant_scores": _variant_rows(sessions),
        "rollouts": ROLLOUTS,
        "sessions": [_session_view(s) for s in sessions if s.get("rollout_idx") == 0],
        "baseline_skill": {"name": baseline["name"], "skill_id": baseline.get("skill_id"),
                           "description": baseline.get("description"), "content": baseline.get("content")},
        "refined_skill": ({"name": refined["name"], "skill_id": refined.get("skill_id"),
                           "description": refined.get("description"), "content": refined.get("content")} if refined else None),
        "backtest": backtest_rows,
        "backtest_note": note,
        "judge_prompt_general": _read_prompt_const("GENERIC_JUDGE_SYSTEM"),
        "judge_prompt_grounded": _judge_prompt(judge),
        "judge_kind": judge,
        "check_keys": list(_CHECK_KEYS.get(judge, _CHECK_KEYS["grounded"])),
        # 本次實際用到的 judge（可能因 per-task 而混合）+ 各自 prompt，供報告顯示
        "judges_used": sorted({_task_judge(t, judge) for t in tasks}),
        "judge_prompts": {jk: _judge_prompt(jk) for jk in sorted({_task_judge(t, judge) for t in tasks})},
    }
    out_path = os.path.join(output_dir, "result.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    report["_out_path"] = out_path
    return report


def _dedupe(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for s in sessions:
        sid = s.get("session_id", "")
        if sid not in seen:
            seen.add(sid)
            out.append(s)
    return out


def _variant_rows(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把每個 (變體×task) 的多次 rollout 聚合成一列（mean/std/success_rate）。"""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in sessions:
        key = (s.get("variant_label"), s.get("task_id"))
        groups.setdefault(key, []).append(s)

    rows = []
    for (variant, task_id), grp in groups.items():
        score_stats = _stats([s.get("_score") for s in grp])
        comp_stats = _stats([(s.get("_metrics") or {}).get("completion") for s in grp])
        n_success = sum(1 for s in grp if s.get("_success"))
        # 達標來源以多數為準（rule/llm）
        srcs = [(s.get("_metrics") or {}).get("completion_source") for s in grp]
        src = max(set(s for s in srcs if s), key=srcs.count) if any(srcs) else None
        rows.append({
            "variant": variant, "task_id": task_id,
            "completion_mean": comp_stats["mean"], "completion_std": comp_stats["std"],
            "completion_source": src,
            "score_mean": score_stats["mean"], "score_std": score_stats["std"],
            "score_scores": score_stats["scores"],
            "success_rate": round(n_success / len(grp), 3),
            "n": len(grp),
        })
    return sorted(rows, key=lambda r: (r["task_id"], -(r["score_mean"] or 0)))


def _session_view(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": s.get("session_id"),
        "variant": s.get("variant_label"),
        "task_id": s.get("task_id"),
        "agent_output": s.get("agent_output"),
        "turns": [{"prompt_text": t.get("prompt_text"), "response_text": t.get("response_text")} for t in s.get("turns", [])],
        "completion_signals": (s.get("_metrics") or {}).get("completion_signals"),
    }


def _read_prompt_const(name: str) -> str:
    from . import prompts

    return getattr(prompts, name, "")


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="general 場景 E2E 測試（Gemini runner+judge）")
    parser.add_argument("--goal-dir", default=_p("skills", "info-digest"))
    parser.add_argument("--tasks-dir", default=_p("golden", "general_e2e"))
    parser.add_argument("--output-dir", default=_p("output", "e2e_general"))
    parser.add_argument("--mode", default="api", choices=["api", "mock"])
    parser.add_argument("--judge", default="grounded", choices=["grounded", "ppt_outline", "cross_doc", "json_schema"])
    parser.add_argument("--report-out", default=_p("docs", "e2e_general_test_report.html"))
    parser.add_argument("--report-title", default=None)
    parser.add_argument("--report-lead", default=None)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)

    llm = LLMClient()
    print(f"[e2e] llm provider={llm.provider} model={llm.model} mode={args.mode} judge={args.judge}")
    report = run_e2e(args.goal_dir, args.tasks_dir, args.output_dir, mode=args.mode, llm=llm, judge=args.judge)
    print(f"[e2e] action={report['action']} accepted={report['accepted']} → {report['_out_path']}")
    print("[e2e] backtest deltas:", [(b['task_id'], b['delta']) for b in report['backtest']])

    if not args.no_report:
        from .e2e_report import render_report

        kw = {}
        if args.report_title:
            kw["title"] = args.report_title
        if args.report_lead:
            kw["lead"] = args.report_lead
        html = render_report(report, **kw)
        with open(args.report_out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[e2e] wrote report → {args.report_out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
