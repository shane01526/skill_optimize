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

from .llm import LLMClient
from .prompts import JUDGE_SYSTEM
from .skillmd import extract_json_object

_DIMENSIONS = ("task_completion", "response_quality", "efficiency", "tool_usage")
_WEIGHTS = {"task_completion": 0.55, "response_quality": 0.30, "efficiency": 0.05, "tool_usage": 0.10}

# 綜合分數：硬指標(測試) 與 軟指標(judge) 的權重
HARD_WEIGHT = 0.6
SOFT_WEIGHT = 0.4


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
#  綜合分數                                                            #
# ------------------------------------------------------------------ #


def evaluate_session(llm: LLMClient, session: dict[str, Any], *, use_judge: bool = True) -> dict[str, Any]:
    """合成硬(測試)+軟(judge) → session["_score"], session["_success"]。就地修改並回傳 session。"""
    test = session.get("test") or {}
    hard = float(test.get("pass_rate", 0.0)) if test else None

    soft = None
    if use_judge:
        scores = session.get("_judge_scores") or judge_session(llm, session)
        if scores:
            soft = float(scores.get("overall_score", 0.0))

    if hard is not None and soft is not None:
        score = round(HARD_WEIGHT * hard + SOFT_WEIGHT * soft, 3)
    elif hard is not None:
        score = round(hard, 3)
    elif soft is not None:
        score = round(soft, 3)
    else:
        score = 0.0

    session["_score"] = score
    # PRM 對齊：把綜合分數當成該 session 的 turn 分數，供 summarizer/execution 顯示
    session["_avg_prm"] = score
    session["_success"] = bool(test.get("all_pass")) if test else (score >= 0.75)
    return session
