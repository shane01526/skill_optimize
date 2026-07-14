"""發布閘：候選(精煉版) vs 現有(精煉前) 的 before/after 四分數驗證。

改寫自 SkillClaw pipeline/skill_verifier.py（精簡為同步）。
分數 < min_score（預設 0.75）→ 擋下，不採用。對應文件陷阱三：
「找到重複 pattern，不代表有效」——需一道保守的驗證閘。
"""

from __future__ import annotations

from typing import Any, Optional

from .llm import LLMClient
from .prompts import VERIFY_SYSTEM
from .skillmd import extract_json_object

_CHECK_KEYS = (
    "grounded_in_evidence",
    "preserves_existing_value",
    "specificity_and_reusability",
    "safe_to_publish",
)


def _clip(value: Any, n: int) -> str:
    t = str(value or "").strip()
    return t if len(t) <= n else t[:n] + "..."


def _norm_score(v: Any) -> Optional[float]:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return round(max(0.0, min(1.0, float(v))), 3)


def verify_candidate(
    llm: LLMClient,
    candidate: dict[str, Any],
    sessions: list[dict[str, Any]],
    action_type: str,
    *,
    current_skill: Optional[dict[str, Any]] = None,
    min_score: float = 0.75,
) -> dict[str, Any]:
    """驗證候選 skill，回傳 {accepted, decision, score, threshold, reason, checks}。"""
    import json

    evidence = []
    for s in sorted(sessions, key=lambda x: x.get("_score", 0.0), reverse=True)[:8]:
        evidence.append(
            {
                "session_id": str(s.get("session_id", "")),
                "score": s.get("_score"),
                "test": s.get("test"),
                "summary": _clip(s.get("_summary", ""), 1000),
            }
        )
    payload: dict[str, Any] = {
        "action": action_type,
        "candidate_skill": {
            "name": str(candidate.get("name", "")),
            "description": str(candidate.get("description", "")),
            "category": str(candidate.get("category", "coding")),
            "content": _clip(candidate.get("content", ""), 8000),
        },
        "current_skill": None,
        "session_evidence": evidence,
        "acceptance_threshold": round(float(min_score), 3),
    }
    if current_skill:
        payload["current_skill"] = {
            "name": str(current_skill.get("name", "")),
            "description": str(current_skill.get("description", "")),
            "content": _clip(current_skill.get("content", ""), 4000),
        }

    try:
        raw = llm.chat(VERIFY_SYSTEM, json.dumps(payload, ensure_ascii=False, indent=2), temperature=0.1, max_tokens=2000)
    except Exception as exc:  # noqa: BLE001
        return _reject(min_score, f"Verifier call failed: {exc}")

    parsed = extract_json_object(raw)
    if not parsed:
        return _reject(min_score, "Verifier returned invalid JSON.")

    checks = {k: _norm_score(parsed.get("checks", {}).get(k)) for k in _CHECK_KEYS if isinstance(parsed.get("checks"), dict)}
    checks = {k: v for k, v in checks.items() if v is not None}
    score = _norm_score(parsed.get("score"))
    if score is None and checks:
        score = round(sum(checks.values()) / len(checks), 3)
    decision = str(parsed.get("decision", "")).strip().lower()
    reason = str(parsed.get("reason") or parsed.get("rationale") or "").strip()

    accepted = decision == "accept"
    if score is not None and score < float(min_score):
        accepted = False
    if decision not in {"accept", "reject"}:
        accepted = score is not None and score >= float(min_score)

    return {
        "enabled": True,
        "accepted": bool(accepted),
        "decision": "accept" if accepted else "reject",
        "score": score,
        "threshold": round(float(min_score), 3),
        "reason": reason,
        "checks": checks,
    }


def _reject(min_score: float, reason: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "accepted": False,
        "decision": "reject",
        "score": None,
        "threshold": round(float(min_score), 3),
        "reason": reason,
        "checks": {},
    }
