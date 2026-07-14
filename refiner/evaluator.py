"""評分：pytest 硬指標 + SkillClaw 式 LLM judge 軟指標 → 綜合 _score。

對應文件：coding 任務好判斷好壞。ground truth = 單元測試通過率（客觀），
再加 LLM judge 四維（task_completion/response_quality/efficiency/tool_usage）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any, Optional

from . import generic_metrics
from .llm import LLMClient
from .prompts import GENERIC_JUDGE_SYSTEM, JUDGE_SYSTEM
from .skillmd import extract_json_object

_DIMENSIONS = ("task_completion", "response_quality", "efficiency", "tool_usage")
_WEIGHTS = {"task_completion": 0.55, "response_quality": 0.30, "efficiency": 0.05, "tool_usage": 0.10}

# 綜合分數：硬指標(測試) 與 軟指標(judge) 的權重
HARD_WEIGHT = 0.6
SOFT_WEIGHT = 0.4

# 通用分：完成度為主體，效率在「已完成」前提下最多再加成 EFF_BONUS。
GENERIC_EFF_BONUS = 0.4        # generic_score = completion × (0.6 + 0.4·eff)
# coding：原綜合分為主，效率僅 ±CODING_EFF_TWEAK 微調（向後相容）。
CODING_EFF_TWEAK = 0.05        # score = coding × (0.95 + 0.05·eff)


# ------------------------------------------------------------------ #
#  硬指標：pytest                                                      #
# ------------------------------------------------------------------ #


def run_pytest(task_dir: str, *, timeout: int = 120) -> dict[str, Any]:
    """在 task_dir 跑 pytest，解析通過數 / 總數。

    回傳 {"passed", "total", "pass_rate", "all_pass", "raw"}。
    找不到測試或執行失敗時 pass_rate=0。
    """
    if not os.path.isdir(task_dir):
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "all_pass": False, "raw": "task dir missing"}
    try:
        proc = subprocess.run(
            # -p no:cacheprovider + -o 覆寫，讓 workspace 測試不受專案 pytest.ini 影響
            [
                sys.executable, "-m", "pytest", "-q", "--no-header",
                "-p", "no:cacheprovider",
                "-o", "addopts=", "-o", "testpaths=.", "-o", "norecursedirs=.git",
                "--rootdir", task_dir, ".",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=task_dir,
        )
        out = proc.stdout + "\n" + proc.stderr
    except subprocess.TimeoutExpired:
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "all_pass": False, "raw": "pytest timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"passed": 0, "total": 0, "pass_rate": 0.0, "all_pass": False, "raw": f"pytest error: {exc}"}

    return _parse_pytest_output(out)


def _parse_pytest_output(out: str) -> dict[str, Any]:
    passed = _find_int(r"(\d+) passed", out)
    failed = _find_int(r"(\d+) failed", out)
    errors = _find_int(r"(\d+) error", out)
    total = passed + failed + errors
    pass_rate = (passed / total) if total else 0.0
    return {
        "passed": passed,
        "total": total,
        "pass_rate": round(pass_rate, 3),
        "all_pass": total > 0 and passed == total,
        "raw": out[-2000:],
    }


def _find_int(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


# ------------------------------------------------------------------ #
#  軟指標：LLM judge                                                   #
# ------------------------------------------------------------------ #


def judge_session(llm: LLMClient, session: dict[str, Any]) -> Optional[dict[str, Any]]:
    """對一個 session 做四維 LLM judge，回傳分數 dict（就地寫入 _judge_scores）。"""
    payload = {
        "session_id": session.get("session_id"),
        "skill_name": session.get("skill_name"),
        "task_id": session.get("task_id"),
        "test": session.get("test"),
        "trajectory": session.get("_trajectory", ""),
        "summary": session.get("_summary", ""),
    }
    try:
        raw = llm.chat(JUDGE_SYSTEM, json.dumps(payload, ensure_ascii=False), temperature=0.1, max_tokens=1200)
    except Exception:  # noqa: BLE001
        return None
    scores = _parse_scores(raw)
    if scores:
        session["_judge_scores"] = scores
    return scores


def _parse_scores(raw: str) -> Optional[dict[str, Any]]:
    payload = extract_json_object(raw)
    if not payload:
        return None
    scores: dict[str, float] = {}
    for key in _DIMENSIONS:
        val = payload.get(key)
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return None
        scores[key] = max(0.0, min(1.0, float(val)))
    overall = round(sum(scores[k] * _WEIGHTS[k] for k in _DIMENSIONS), 3)
    return {**scores, "overall_score": overall, "rationale": str(payload.get("rationale") or "").strip()}


# ------------------------------------------------------------------ #
#  通用（場景無關）有效性 judge + 任務類型判定                          #
# ------------------------------------------------------------------ #


def resolve_task_type(session: dict[str, Any]) -> str:
    """判定任務類型：標籤優先，否則以「有沒有測試訊號」偵測回退。回 "coding" | "general"。"""
    tag = str(session.get("task_type") or "").strip().lower()
    if tag in ("coding", "general"):
        return tag
    test = session.get("test") or {}
    if isinstance(test, dict) and test.get("total"):
        return "coding"
    return "general"


def generic_completion_score(llm: LLMClient, session: dict[str, Any]) -> float:
    """通用 LLM judge：回 task_completion（0..1）。解析失敗 → 保守 0.5。就地存 _generic_judge。"""
    cached = session.get("_generic_judge")
    if isinstance(cached, dict) and isinstance(cached.get("task_completion"), (int, float)):
        return float(cached["task_completion"])
    payload = {
        "session_id": session.get("session_id"),
        "task_id": session.get("task_id"),
        "trajectory": session.get("_trajectory", ""),
        "summary": session.get("_summary", ""),
    }
    try:
        raw = llm.chat(GENERIC_JUDGE_SYSTEM, json.dumps(payload, ensure_ascii=False), temperature=0.1, max_tokens=800)
        parsed = extract_json_object(raw) or {}
    except Exception:  # noqa: BLE001
        parsed = {}
    tc = parsed.get("task_completion")
    rq = parsed.get("response_quality")
    result = {
        "task_completion": max(0.0, min(1.0, float(tc))) if isinstance(tc, (int, float)) and not isinstance(tc, bool) else 0.5,
        "response_quality": max(0.0, min(1.0, float(rq))) if isinstance(rq, (int, float)) and not isinstance(rq, bool) else None,
        "rationale": str(parsed.get("rationale") or "").strip(),
    }
    session["_generic_judge"] = result
    return result["task_completion"]


# ------------------------------------------------------------------ #
#  綜合分數（coding 原評分 + 通用效率層）                              #
# ------------------------------------------------------------------ #


def evaluate_sessions(llm: LLMClient, sessions: list[dict[str, Any]], *, use_judge: bool = True) -> list[dict[str, Any]]:
    """對一組（同 goal）sessions 評分：先算 cohort 效率，再逐一 evaluate_session。

    cohort 效率需整組一起算（min-max 正規化），故提供批次入口。
    """
    generic_metrics.attach_cohort_efficiency(sessions)
    for s in sessions:
        evaluate_session(llm, s, use_judge=use_judge, _cohort_done=True)
    return sessions


def evaluate_session(
    llm: LLMClient,
    session: dict[str, Any],
    *,
    use_judge: bool = True,
    _cohort_done: bool = False,
) -> dict[str, Any]:
    """評分：coding → 原(pytest+judge)為主 + 效率微調；general → 通用(completion×效率)。

    就地寫入 session["_score"] / ["_success"] / ["_metrics"] / ["_task_type"]。
    單獨呼叫時 cohort=自己一人（效率=中性 1.0）；批次請用 evaluate_sessions。
    """
    if not _cohort_done and "_metrics" not in session:
        generic_metrics.attach_cohort_efficiency([session])

    metrics = session.get("_metrics") or {}
    efficiency = float(metrics.get("efficiency_score", 1.0))
    task_type = resolve_task_type(session)
    session["_task_type"] = task_type

    if task_type == "coding":
        test = session.get("test") or {}
        hard = float(test.get("pass_rate", 0.0)) if test else None
        soft = None
        if use_judge:
            scores = session.get("_judge_scores") or judge_session(llm, session)
            if scores:
                soft = float(scores.get("overall_score", 0.0))
        if hard is not None and soft is not None:
            base = HARD_WEIGHT * hard + SOFT_WEIGHT * soft
        elif hard is not None:
            base = hard
        elif soft is not None:
            base = soft
        else:
            base = 0.0
        # 原分為主，效率僅 ±CODING_EFF_TWEAK 微調（efficiency=1 → ×1.0，中性；越低越扣）
        score = round(base * (1.0 - CODING_EFF_TWEAK + CODING_EFF_TWEAK * efficiency), 3)
        session["_success"] = bool(test.get("all_pass")) if test else (score >= 0.75)
        session["_metrics"]["base_coding_score"] = round(base, 3)
    else:  # general
        completion = generic_completion_score(llm, session) if use_judge else 0.5
        # 完成度為主體，效率在已完成前提下加成
        score = round(completion * (1.0 - GENERIC_EFF_BONUS + GENERIC_EFF_BONUS * efficiency), 3)
        session["_success"] = completion >= 0.75
        session["_metrics"]["completion"] = round(completion, 3)

    session["_score"] = score
    session["_metrics"]["task_type"] = task_type
    # PRM 對齊：綜合分當該 session 的 turn 分數，供 summarizer/execution 顯示
    session["_avg_prm"] = score
    return session
