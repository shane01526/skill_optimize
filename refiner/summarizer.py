"""Summarize：為每個 session 建 lossless trajectory + LLM 分析摘要 + metadata。

改寫自 ``third_party/skillclaw/evolve_server/pipeline/summarizer.py``（精簡為同步）。
"""

from __future__ import annotations

from typing import Any

from .llm import LLMClient
from .prompts import SUMMARIZE_SYSTEM

_CLIP = 400
_MAX_TOOLS = 8


def _clip(text: Any, limit: int = _CLIP) -> str:
    s = str(text or "").strip().replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def build_trajectory(session: dict[str, Any]) -> str:
    """建 lossless 逐步 trajectory 文字（零資訊損失、給 LLM 與人看）。"""
    turns = session.get("turns", [])
    if not turns:
        return "(empty session)"
    blocks: list[str] = []
    for i, t in enumerate(turns, 1):
        header = [f"[Step {i}]"]
        prm = t.get("prm_score")
        if prm is not None:
            header.append(f"PRM={prm}")
        skills = [s.get("skill_name") if isinstance(s, dict) else str(s) for s in t.get("read_skills") or []]
        skills = [s for s in skills if s]
        if skills:
            header.append(f"read_skills={skills}")
        lines = [" | ".join(header)]
        if i == 1 and t.get("prompt_text"):
            lines.append(f"  User: {_clip(t['prompt_text'])}")
        tool_lines = _format_tools(t)
        if tool_lines:
            lines.append("  Tools:")
            lines.extend(tool_lines)
        if t.get("response_text"):
            lines.append(f"  Agent: {_clip(t['response_text'])}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _format_tools(turn: dict[str, Any]) -> list[str]:
    calls = turn.get("tool_calls") or []
    results = {r.get("tool_call_id"): r for r in turn.get("tool_results") or [] if isinstance(r, dict)}
    lines: list[str] = []
    for tc in calls[:_MAX_TOOLS]:
        if not isinstance(tc, dict):
            continue
        func = tc.get("function") or {}
        name = func.get("name") or "unknown"
        args = _clip(func.get("arguments", ""))
        r = results.get(tc.get("id"))
        outcome = ""
        if r:
            if r.get("has_error"):
                outcome = f" → ✗ {_clip(r.get('content', ''))}"
            else:
                outcome = f" → ✓ {_clip(r.get('content', ''))}".rstrip()
        lines.append(f"    {name}({args}){outcome}")
    if len(calls) > _MAX_TOOLS:
        lines.append(f"    ... +{len(calls) - _MAX_TOOLS} more tool calls")
    return lines


def extract_metadata(session: dict[str, Any]) -> None:
    """補上 _skills_referenced / _prm_scores / _avg_prm / _has_tool_errors。"""
    skills: set[str] = set()
    prm_scores: list[float] = []
    has_errors = False
    for turn in session.get("turns", []):
        for item in turn.get("read_skills") or []:
            name = item.get("skill_name", "").strip() if isinstance(item, dict) else str(item or "").strip()
            if name:
                skills.add(name)
        prm = turn.get("prm_score")
        if prm is not None:
            prm_scores.append(prm)
        if any(r.get("has_error") for r in turn.get("tool_results") or []):
            has_errors = True
    # 若 session 明確帶 skill_name（實驗場景），確保它進入分組
    if session.get("skill_name"):
        skills.add(session["skill_name"])
    session["_skills_referenced"] = skills
    session["_prm_scores"] = prm_scores
    session["_avg_prm"] = round(sum(prm_scores) / len(prm_scores), 3) if prm_scores else None
    session["_has_tool_errors"] = has_errors


def _build_payload(session: dict[str, Any]) -> str:
    import json

    turns = session.get("turns", [])
    interactions = []
    for t in turns:
        interactions.append(
            {
                "prompt": _clip(t.get("prompt_text", ""), 1500),
                "response": _clip(t.get("response_text", ""), 1500),
                "tool_calls": [
                    {"name": (tc.get("function") or {}).get("name"), "args": _clip((tc.get("function") or {}).get("arguments", ""))}
                    for tc in (t.get("tool_calls") or [])[:6]
                ],
            }
        )
    payload = {
        "session_id": session.get("session_id"),
        "skill_name": session.get("skill_name"),
        "task_id": session.get("task_id"),
        "test": session.get("test"),
        "trajectory": session.get("_trajectory", ""),
        "interactions": interactions,
    }
    return json.dumps(payload, ensure_ascii=False)


def summarize_sessions(llm: LLMClient, sessions: list[dict[str, Any]]) -> None:
    """為每個 session 補上 _trajectory / _summary / metadata（就地修改）。"""
    for session in sessions:
        extract_metadata(session)
        session["_trajectory"] = build_trajectory(session)
        try:
            session["_summary"] = llm.chat(SUMMARIZE_SYSTEM, _build_payload(session), temperature=0.2)
        except Exception as exc:  # noqa: BLE001
            session["_summary"] = ""
            session["_summary_error"] = str(exc)
