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


def _p(*parts: str) -> str:
    return os.path.join(PROJECT_ROOT, *parts)


def discover_variants(goal_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(goal_dir, "*", "SKILL.md")))


def discover_tasks(tasks_dir: str) -> list[str]:
    return sorted(d for d in glob.glob(os.path.join(tasks_dir, "*")) if os.path.isdir(d))


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


def _run_skill_on_task(llm: LLMClient, skill: dict[str, Any], task_dir: str, task_id: str, label: str) -> dict[str, Any]:
    """用給定 skill（dict，含 name/content）在 task 上真跑 Gemini 產出 + judge，回傳結果。"""
    task_prompt = _read_task_prompt(task_dir)
    sources = _read_sources(task_dir)
    instruction = _compose_general_instruction(task_prompt, sources, skill)
    try:
        output = llm.chat(
            "You are a careful assistant that strictly grounds answers in the given sources.",
            instruction, temperature=0.2, max_tokens=2048,
        )
    except Exception as exc:  # noqa: BLE001
        output = f"[error] {exc}"

    # grounded judge：給 judge 看「來源 + 需求驗收點 + 產出」，真的核對涵蓋度/忠實度/格式
    judge = _grounded_judge(llm, task_prompt, sources, output)
    return {
        "task_id": task_id,
        "label": label,
        "output": output,
        "completion": judge.get("overall"),
        "checks": {k: judge.get(k) for k in ("coverage", "faithfulness", "conflict_handling", "format")},
        "rationale": judge.get("rationale", ""),
    }


def _grounded_judge(llm: LLMClient, task_prompt: str, sources: str, answer: str) -> dict[str, Any]:
    """用 GROUNDED_JUDGE_SYSTEM 讓 Gemini 核對產出 vs 來源，回四個 check + overall。"""
    from .prompts import GROUNDED_JUDGE_SYSTEM
    from .skillmd import extract_json_object

    payload = json.dumps({"task": task_prompt, "sources": sources, "answer": answer}, ensure_ascii=False)
    try:
        raw = llm.chat(GROUNDED_JUDGE_SYSTEM, payload, temperature=0.1, max_tokens=1200)
        parsed = extract_json_object(raw) or {}
    except Exception:  # noqa: BLE001
        parsed = {}

    def _num(v):
        return round(max(0.0, min(1.0, float(v))), 3) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    checks = {k: _num(parsed.get(k)) for k in ("coverage", "faithfulness", "conflict_handling", "format")}
    overall = _num(parsed.get("overall"))
    if overall is None:
        vals = [v for v in checks.values() if v is not None]
        overall = round(sum(vals) / len(vals), 3) if vals else 0.5
    return {**checks, "overall": overall, "rationale": str(parsed.get("rationale") or "").strip()}


def backtest(llm: LLMClient, baseline: dict[str, Any], refined: dict[str, Any], tasks: list[str]) -> list[dict[str, Any]]:
    """對每個 task，baseline skill 與 refined skill 各真跑一次 Gemini + judge → 前後對照。"""
    rows: list[dict[str, Any]] = []
    for task_dir in tasks:
        task_id = os.path.basename(task_dir)
        b = _run_skill_on_task(llm, baseline, task_dir, task_id, "baseline")
        r = _run_skill_on_task(llm, refined, task_dir, task_id, "refined")
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
) -> dict[str, Any]:
    llm = llm or LLMClient()
    os.makedirs(output_dir, exist_ok=True)
    variants = [v for v in discover_variants(goal_dir) if os.path.basename(os.path.dirname(v)) != "baseline"]
    tasks = discover_tasks(tasks_dir)

    # 1. 每個 (變體×task) 真跑 Gemini 產出
    records: list[dict[str, Any]] = []
    for vpath in variants:
        for task_dir in tasks:
            task_id = os.path.basename(task_dir)
            rec = run_general_variant_on_task(
                skill_md_path=vpath, task_dir=task_dir, task_id=task_id, mode=mode, llm=llm
            )
            records.append(rec)
            print(f"  ran {rec['variant_label']} × {task_id} ({rec['runner_mode']}/{rec['runner_meta'].get('provider')})")

    # 2. normalize → summarize → evaluate（judge + detector + 效率）
    sessions = [normalize_experiment_record(r) for r in records]
    # 保留原始產出/來源供報告
    for s, r in zip(sessions, records):
        s["agent_output"] = r.get("agent_output")
        s["sources"] = r.get("sources")
        s["task_prompt"] = r.get("task_prompt")
    summarizer.summarize_sessions(llm, sessions)
    evaluator.evaluate_sessions(llm, sessions, use_judge=True)

    # 3. aggregate + evolve + verify
    groups = aggregation.aggregate_by_skill(sessions)
    baseline = load_baseline_skill(goal_dir)
    existing = [k for k in groups.keys() if k != aggregation.NO_SKILL_KEY]
    evidence = _dedupe(sessions)
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
    backtest_rows = backtest(llm, baseline, refined_for_test, tasks)

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
        "sessions": [_session_view(s) for s in sessions],
        "baseline_skill": {"name": baseline["name"], "skill_id": baseline.get("skill_id"),
                           "description": baseline.get("description"), "content": baseline.get("content")},
        "refined_skill": ({"name": refined["name"], "skill_id": refined.get("skill_id"),
                           "description": refined.get("description"), "content": refined.get("content")} if refined else None),
        "backtest": backtest_rows,
        "judge_prompt_general": _read_prompt_const("GENERIC_JUDGE_SYSTEM"),
        "judge_prompt_grounded": _read_prompt_const("GROUNDED_JUDGE_SYSTEM"),
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
    rows = []
    for s in sessions:
        m = s.get("_metrics") or {}
        rows.append({
            "variant": s.get("variant_label"),
            "task_id": s.get("task_id"),
            "completion": m.get("completion"),
            "completion_source": m.get("completion_source"),
            "completion_confidence": m.get("completion_confidence"),
            "efficiency_score": m.get("efficiency_score"),
            "score": s.get("_score"),
            "success": s.get("_success"),
        })
    return sorted(rows, key=lambda r: (r["task_id"], -(r["score"] or 0)))


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
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)

    llm = LLMClient()
    print(f"[e2e] llm provider={llm.provider} model={llm.model} mode={args.mode}")
    report = run_e2e(args.goal_dir, args.tasks_dir, args.output_dir, mode=args.mode, llm=llm)
    print(f"[e2e] action={report['action']} accepted={report['accepted']} → {report['_out_path']}")
    print("[e2e] backtest deltas:", [(b['task_id'], b['delta']) for b in report['backtest']])

    if not args.no_report:
        from .e2e_report import render_report

        html = render_report(report)
        out = _p("docs", "e2e_general_test_report.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[e2e] wrote report → {out} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
