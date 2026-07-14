"""Skill 精煉 pipeline 主流程（版本 A）+ CLI 入口。

run_once 串接：
  run(可選) → evaluate → normalize → summarize → aggregate
            → evolve(改進/建立/合併) → verify(before/after 閘) → registry → report

子指令：
  run-experiment   針對 skills/<goal>/ 下所有變體 × golden tasks 跑一輪，產生 logs/
  refine           讀 logs/ → 精煉 → 產出 output/（草稿 + 對照表 + registry）
  all              run-experiment 後接 refine
  mine             Phase 2：讀 ~/.codex/sessions rollout 探勘（見 normalizer）

預設沒有 API key 時走離線 Mock（見 llm.py / mock_llm.py），可端到端跑通。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from typing import Any, Optional

from . import aggregation, evaluator, execution, summarizer, verifier
from .llm import LLMClient
from .normalizer import load_codex_rollouts, load_experiment_sessions
from .registry import SkillRegistry
from .report import build_before_after, write_report_json, write_report_md
from .runner_codex import run_variant_on_task, save_experiment_log
from .skillmd import build_skill_md, content_sha, parse_skill_md

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)


def _p(*parts: str) -> str:
    return os.path.join(PROJECT_ROOT, *parts)


# ------------------------------------------------------------------ #
#  探索 skill 變體 / golden tasks                                     #
# ------------------------------------------------------------------ #


def discover_variants(goal_dir: str) -> list[str]:
    """回傳 goal_dir 下所有變體的 SKILL.md 路徑（v_*/SKILL.md）。"""
    return sorted(glob.glob(os.path.join(goal_dir, "*", "SKILL.md")))


def discover_tasks(tasks_dir: str) -> list[str]:
    """回傳 golden/tasks 下每個 task 目錄。"""
    return sorted(d for d in glob.glob(os.path.join(tasks_dir, "*")) if os.path.isdir(d))


def load_baseline_skill(goal_dir: str) -> dict[str, Any]:
    """精煉前的 baseline skill：優先 baseline/SKILL.md，否則取第一個變體。"""
    baseline_path = os.path.join(goal_dir, "baseline", "SKILL.md")
    if not os.path.exists(baseline_path):
        variants = discover_variants(goal_dir)
        if not variants:
            raise FileNotFoundError(f"no variants under {goal_dir}")
        baseline_path = variants[0]
    with open(baseline_path, "r", encoding="utf-8") as fh:
        return parse_skill_md(fh.read(), fallback_name=os.path.basename(goal_dir))


# ------------------------------------------------------------------ #
#  run-experiment                                                     #
# ------------------------------------------------------------------ #


def run_experiment(goal_dir: str, tasks_dir: str, logs_dir: str, *, mode: str = "auto", llm: Optional[LLMClient] = None) -> list[str]:
    variants = discover_variants(goal_dir)
    tasks = discover_tasks(tasks_dir)
    if not variants:
        raise FileNotFoundError(f"no skill variants under {goal_dir}")
    if not tasks:
        raise FileNotFoundError(f"no golden tasks under {tasks_dir}")

    llm = llm or LLMClient()
    workspaces_root = _p("output", "workspaces")
    written: list[str] = []
    for variant_path in variants:
        # 跳過 baseline 目錄本身（它是精煉前，不當變體跑）
        if os.path.basename(os.path.dirname(variant_path)) == "baseline":
            continue
        for task_dir in tasks:
            task_id = os.path.basename(task_dir)
            rec, ws = run_variant_on_task(
                skill_md_path=variant_path, task_dir=task_dir, task_id=task_id,
                workspaces_root=workspaces_root, mode=mode, llm=llm,
            )
            # 硬指標：在該組合的獨立 workspace 跑測試（agent 已在此改檔）
            rec["test"] = evaluator.run_pytest(ws)
            path = save_experiment_log(rec, logs_dir)
            written.append(path)
            print(f"  ran {rec['variant_label']} × {task_id} → {rec['runner_mode']} "
                  f"(tests {rec['test']['passed']}/{rec['test']['total']})")
    return written


# ------------------------------------------------------------------ #
#  refine（核心精煉）                                                  #
# ------------------------------------------------------------------ #


def refine(
    logs_dir: str,
    goal_dir: str,
    output_dir: str,
    *,
    llm: Optional[LLMClient] = None,
    min_score: float = 0.75,
    use_judge: bool = True,
    registry_path: Optional[str] = None,
) -> dict[str, Any]:
    """讀 logs → 精煉 → 產出草稿/對照表/registry。回傳 summary dict。"""
    llm = llm or LLMClient()
    os.makedirs(output_dir, exist_ok=True)
    registry_path = registry_path or os.path.join(output_dir, "skill_registry.json")
    registry = SkillRegistry(registry_path)

    sessions = load_experiment_sessions(logs_dir)
    if not sessions:
        raise FileNotFoundError(f"no session logs in {logs_dir}")

    # 1. summarize + metadata
    summarizer.summarize_sessions(llm, sessions)
    # 2. evaluate（補齊 _score/_success；若 log 已含 test，evaluator 會沿用）
    for s in sessions:
        evaluator.evaluate_session(llm, s, use_judge=use_judge)
    # 3. aggregate by skill
    groups = aggregation.aggregate_by_skill(sessions)

    baseline = load_baseline_skill(goal_dir)
    baseline_name = baseline["name"]
    existing_names = list(groups.keys())

    # 4. evolve：把所有變體 session 當作同一目標的證據，精煉出一個新版
    #    （個人 MVP：合併所有非 no_skill 群組的 session 當證據）
    evidence_sessions = [s for k, g in groups.items() if k != aggregation.NO_SKILL_KEY for s in g]
    # 去重（同一 session 可能出現在多群）
    seen: set[str] = set()
    unique_evidence: list[dict[str, Any]] = []
    for s in evidence_sessions:
        sid = s.get("session_id", "")
        if sid not in seen:
            seen.add(sid)
            unique_evidence.append(s)

    result = execution.evolve_skill_from_sessions(
        llm, baseline_name, unique_evidence, baseline, existing_names
    )

    summary: dict[str, Any] = {
        "goal": baseline_name,
        "num_sessions": len(sessions),
        "num_variants": len({s.get("skill_name") for s in sessions if s.get("skill_name")}),
        "action": (result or {}).get("action"),
        "rationale": (result or {}).get("rationale", ""),
        "accepted": False,
        "verify": None,
    }

    if not result or result.get("action") == execution.ACTION_SKIP:
        summary["note"] = "pipeline 判定 skip（證據不足或已足夠好）"
        _finalize(summary, sessions, baseline, None, output_dir, registry, registry_path)
        return summary

    candidate = dict(result["skill"])
    candidate.setdefault("category", "coding")
    candidate.setdefault("skill_id", baseline.get("skill_id"))

    # 5. verify：before/after 四分數閘
    verdict = verifier.verify_candidate(
        llm, candidate, unique_evidence, result["action"],
        current_skill=baseline, min_score=min_score,
    )
    summary["verify"] = verdict
    summary["accepted"] = verdict["accepted"]

    if verdict["accepted"]:
        # 6. registry：寫入新版
        new_md = build_skill_md(candidate)
        new_sha = content_sha(new_md)
        version = registry.record_update(
            baseline_name, new_sha, action=result["action"], rationale=result.get("rationale", "")
        )
        candidate["version"] = version
        # 產出精煉版 SKILL.md 草稿
        refined_path = os.path.join(output_dir, f"{baseline_name}.refined.SKILL.md")
        with open(refined_path, "w", encoding="utf-8") as fh:
            fh.write(build_skill_md(candidate))
        summary["refined_skill_path"] = refined_path
        summary["new_version"] = version
    else:
        summary["note"] = f"verifier 擋下（score={verdict['score']} < {min_score}）"

    _finalize(summary, sessions, baseline, candidate if verdict["accepted"] else candidate, output_dir, registry, registry_path)
    return summary


def _finalize(summary, sessions, baseline, candidate, output_dir, registry, registry_path) -> None:
    registry.save(registry_path)
    report = build_before_after(summary, sessions, baseline, candidate)
    report_json = os.path.join(output_dir, "before_after.json")
    write_report_json(report, report_json)
    write_report_md(report, os.path.join(output_dir, "before_after.md"))
    summary["report_json"] = report_json
    # 順便產生 HTML 說明檔（可離線查閱）
    try:
        from .html_report import render_html

        html_path = _p("docs", "skill_refinement.html")
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(render_html(report, report_dir=output_dir))
        summary["html"] = html_path
    except Exception as exc:  # noqa: BLE001
        summary["html_error"] = str(exc)


# ------------------------------------------------------------------ #
#  mine（Phase 2）                                                     #
# ------------------------------------------------------------------ #


def mine_codex_logs(sessions_dir: str, out_logs_dir: str) -> list[str]:
    """讀 ~/.codex/sessions rollout → 統一 session → 寫進 logs/ 供 refine 使用。"""
    os.makedirs(out_logs_dir, exist_ok=True)
    sessions = load_codex_rollouts(sessions_dir)
    written = []
    for s in sessions:
        safe = str(s.get("session_id", "session")).replace("/", "_")
        path = os.path.join(out_logs_dir, f"mined_{safe}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=2)
        written.append(path)
    return written


# ------------------------------------------------------------------ #
#  publish（Skill 上架流程）                                          #
# ------------------------------------------------------------------ #


def publish_skills(goal_dir: str, output_dir: str, *, registry_path: Optional[str] = None) -> dict[str, Any]:
    """掃 goal_dir 下所有 SKILL.md，逐一經 registry 上架驗證。

    對齊 0714 文件「Skill 上架流程」1-4：提交 → 讀 metadata → 檢查 skill_id 唯一/欄位完整 → 建立資料。
    回傳 {results:[...], passed, failed}，並把通過的 skill 寫回 registry。
    """
    os.makedirs(output_dir, exist_ok=True)
    registry_path = registry_path or os.path.join(output_dir, "skill_registry.json")
    registry = SkillRegistry(registry_path)

    paths = sorted(glob.glob(os.path.join(goal_dir, "*", "SKILL.md")))
    results: list[dict[str, Any]] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            skill = parse_skill_md(fh.read(), fallback_name=os.path.basename(os.path.dirname(path)))
        outcome = registry.register(skill)
        outcome["path"] = os.path.relpath(path, PROJECT_ROOT)
        results.append(outcome)

    registry.save(registry_path)
    passed = sum(1 for r in results if r["ok"])
    outcome = {"results": results, "passed": passed, "failed": len(results) - passed}
    # 持久化供 HTML 顯示
    with open(os.path.join(output_dir, "publish_result.json"), "w", encoding="utf-8") as fh:
        json.dump(outcome, fh, ensure_ascii=False, indent=2)
    return outcome


# ------------------------------------------------------------------ #
#  CLI                                                                #
# ------------------------------------------------------------------ #


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Skill 精煉機制 pipeline（版本 A）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    default_goal = _p("skills", "coding-debug")
    default_tasks = _p("golden", "tasks")
    default_logs = _p("logs")
    default_out = _p("output")

    for name in ("run-experiment", "refine", "all"):
        sp = sub.add_parser(name)
        sp.add_argument("--goal-dir", default=default_goal)
        sp.add_argument("--tasks-dir", default=default_tasks)
        sp.add_argument("--logs-dir", default=default_logs)
        sp.add_argument("--output-dir", default=default_out)
        sp.add_argument("--mode", default="auto", choices=["auto", "codex", "api", "mock"])
        sp.add_argument("--min-score", type=float, default=0.75)
        sp.add_argument("--no-judge", action="store_true")

    mp = sub.add_parser("mine")
    mp.add_argument("--sessions-dir", default=os.path.expanduser("~/.codex/sessions"))
    mp.add_argument("--logs-dir", default=default_logs)

    pp = sub.add_parser("publish")
    pp.add_argument("--goal-dir", default=default_goal)
    pp.add_argument("--output-dir", default=default_out)

    args = parser.parse_args(argv)

    if args.cmd == "mine":
        written = mine_codex_logs(args.sessions_dir, args.logs_dir)
        print(f"mined {len(written)} sessions into {args.logs_dir}")
        return 0

    if args.cmd == "publish":
        print("== publish（Skill 上架驗證）==")
        outcome = publish_skills(args.goal_dir, args.output_dir)
        for r in outcome["results"]:
            mark = "[OK]" if r["ok"] else "[FAIL]"
            detail = f"skill_id={r['skill_id']}" if r["ok"] else "; ".join(r["errors"])
            print(f"  {mark} {r['path']} - {detail}")
        print(f"通過 {outcome['passed']} / 失敗 {outcome['failed']}")
        return 0

    llm = LLMClient()
    print(f"[llm] provider={llm.provider} model={llm.model}")

    if args.cmd in ("run-experiment", "all"):
        print("== run-experiment ==")
        run_experiment(args.goal_dir, args.tasks_dir, args.logs_dir, mode=args.mode, llm=llm)

    if args.cmd in ("refine", "all"):
        print("== refine ==")
        summary = refine(
            args.logs_dir, args.goal_dir, args.output_dir,
            llm=llm, min_score=args.min_score, use_judge=not args.no_judge,
        )
        print(json.dumps({k: v for k, v in summary.items() if k != "verify"}, ensure_ascii=False, indent=2))
        if summary.get("verify"):
            print("verify:", json.dumps(summary["verify"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
