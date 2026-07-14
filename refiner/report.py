"""產出精煉前 / 精煉後對照表（JSON + Markdown），並可餵給 HTML。

對應文件「預計產出 2. 精煉前 / 精煉後的對照表」。
"""

from __future__ import annotations

import difflib
import json
import os
from typing import Any, Optional


def _variant_scores(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每個變體在各 task 的分數列（逐 變體×task）。"""
    rows = []
    for s in sessions:
        test = s.get("test") or {}
        m = s.get("_metrics") or {}
        raw = m.get("raw") or {}
        rows.append(
            {
                "session_id": s.get("session_id"),
                "skill_name": s.get("skill_name"),
                "variant": s.get("variant_label") or s.get("skill_name"),
                "skill_id": s.get("skill_id"),
                "actual_used_skill_ids": s.get("actual_used_skill_ids") or [],
                "task_id": s.get("task_id"),
                "task_type": s.get("_task_type") or m.get("task_type"),
                "runner_mode": s.get("runner_mode"),
                "pass_rate": test.get("pass_rate"),
                "tests": f"{test.get('passed', 0)}/{test.get('total', 0)}" if test else "",
                "judge_overall": (s.get("_judge_scores") or {}).get("overall_score"),
                # 通用（場景無關）指標
                "num_turns": raw.get("num_turns"),
                "num_tool_calls": raw.get("num_tool_calls"),
                "tool_error_rate": raw.get("tool_error_rate"),
                "response_chars": raw.get("response_chars"),
                "elapsed_sec": raw.get("elapsed_sec"),
                "efficiency_score": m.get("efficiency_score"),
                "cohort_key": m.get("cohort_key"),
                "cohort_size": m.get("cohort_size"),
                "completion": m.get("completion"),
                "score": s.get("_score"),
                "success": s.get("_success"),
            }
        )
    return sorted(rows, key=lambda r: (r["score"] or 0.0), reverse=True)


def _variant_aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依變體聚合：跨 task 的平均綜合分（對齊 doc「同一批任務」語意）。

    winner 依此平均分選出，而非單筆 task 最高分。
    """
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_variant.setdefault(r["variant"], []).append(r)
    agg = []
    for variant, items in by_variant.items():
        scores = [i["score"] for i in items if i.get("score") is not None]
        pass_rates = [i["pass_rate"] for i in items if i.get("pass_rate") is not None]
        effs = [i["efficiency_score"] for i in items if i.get("efficiency_score") is not None]
        turns = [i["num_turns"] for i in items if i.get("num_turns") is not None]
        elapsed = [i["elapsed_sec"] for i in items if i.get("elapsed_sec") is not None]
        avg = round(sum(scores) / len(scores), 3) if scores else 0.0
        agg.append(
            {
                "variant": variant,
                "skill_id": items[0].get("skill_id"),
                "actual_used_skill_ids": items[0].get("actual_used_skill_ids") or [],
                "task_type": ",".join(sorted({str(i.get("task_type")) for i in items if i.get("task_type")})) or None,
                "num_tasks": len(items),
                "avg_score": avg,
                "avg_pass_rate": round(sum(pass_rates) / len(pass_rates), 3) if pass_rates else None,
                "avg_efficiency": round(sum(effs) / len(effs), 3) if effs else None,
                "avg_num_turns": round(sum(turns) / len(turns), 2) if turns else None,
                "avg_elapsed_sec": round(sum(elapsed) / len(elapsed), 3) if elapsed else None,
                "all_success": all(i.get("success") for i in items),
            }
        )
    return sorted(agg, key=lambda r: r["avg_score"], reverse=True)


def _content_diff(before: str, after: str) -> list[dict[str, str]]:
    """產生 before → after 的 unified-ish diff（行級），供表格顯示。"""
    b = (before or "").splitlines()
    a = (after or "").splitlines()
    diff = []
    for line in difflib.unified_diff(b, a, lineterm="", n=2):
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            kind = "hunk"
        elif line.startswith("+"):
            kind = "add"
        elif line.startswith("-"):
            kind = "del"
        else:
            kind = "ctx"
        diff.append({"kind": kind, "text": line})
    return diff


def build_before_after(
    summary: dict[str, Any],
    sessions: list[dict[str, Any]],
    baseline: dict[str, Any],
    candidate: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """組出結構化 before/after 報告。"""
    variant_rows = _variant_scores(sessions)
    variant_agg = _variant_aggregate(variant_rows)
    # winner 依「跨 task 平均分」選出（對齊 doc「同一批任務」）
    winner_agg = variant_agg[0] if variant_agg else None
    winner = None
    if winner_agg:
        # 找出勝出變體的代表列（供 HTML 既有欄位相容）
        winner = next((r for r in variant_rows if r["variant"] == winner_agg["variant"]), None)
        if winner:
            winner = {**winner, "avg_score": winner_agg["avg_score"], "num_tasks": winner_agg["num_tasks"]}

    report: dict[str, Any] = {
        "goal": summary.get("goal"),
        "generated_action": summary.get("action"),
        "rationale": summary.get("rationale"),
        "accepted": summary.get("accepted"),
        "verify": summary.get("verify"),
        "num_sessions": summary.get("num_sessions"),
        "num_variants": summary.get("num_variants"),
        "winner": winner,
        "variant_aggregate": variant_agg,
        "variant_scores": variant_rows,
        "before": {
            "skill_id": baseline.get("skill_id"),
            "name": baseline.get("name"),
            "description": baseline.get("description"),
            "content": baseline.get("content"),
        },
        "after": None,
        "content_diff": [],
    }
    if candidate:
        report["after"] = {
            "skill_id": candidate.get("skill_id"),
            "name": candidate.get("name"),
            "version": candidate.get("version"),
            "description": candidate.get("description"),
            "content": candidate.get("content"),
        }
        report["content_diff"] = _content_diff(baseline.get("content", ""), candidate.get("content", ""))
    return report


# ------------------------------------------------------------------ #
#  writers                                                            #
# ------------------------------------------------------------------ #


def write_report_json(report: dict[str, Any], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)


def write_report_md(report: dict[str, Any], path: str) -> None:
    lines: list[str] = []
    lines.append(f"# Skill 精煉對照表：{report.get('goal')}\n")
    lines.append(f"- 動作：**{report.get('generated_action')}**　採用：**{report.get('accepted')}**")
    lines.append(f"- 變體數：{report.get('num_variants')}　session 數：{report.get('num_sessions')}")
    verify = report.get("verify") or {}
    if verify:
        lines.append(f"- 驗證閘：score={verify.get('score')} / 門檻 {verify.get('threshold')} → {verify.get('decision')}")
    lines.append(f"- 精煉理由：{report.get('rationale')}\n")

    lines.append("## 各變體在 golden task 的分數\n")
    lines.append("| 變體 | task | runner | 測試 | pass_rate | judge | 綜合分 | 成功 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in report.get("variant_scores", []):
        lines.append(
            f"| {r['skill_name']} | {r['task_id']} | {r['runner_mode']} | {r['tests']} | "
            f"{r['pass_rate']} | {r['judge_overall']} | **{r['score']}** | {r['success']} |"
        )
    winner = report.get("winner")
    if winner:
        lines.append(f"\n**勝出變體**：`{winner['skill_name']}`（綜合分 {winner['score']}）\n")

    lines.append("## 精煉前 / 精煉後\n")
    before = report.get("before", {})
    after = report.get("after")
    lines.append(f"### Before（{before.get('name')} / {before.get('skill_id')}）")
    lines.append(f"> {before.get('description')}\n")
    if after:
        lines.append(f"### After（v{after.get('version')} / {after.get('skill_id')}）")
        lines.append(f"> {after.get('description')}\n")
        lines.append("### 內容 diff\n```diff")
        for d in report.get("content_diff", []):
            lines.append(d["text"])
        lines.append("```")
    else:
        lines.append("_（未產生採用的精煉版；見上方 skip / reject 理由）_")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
