"""從勝出變體萃取共通做法 → 生成精煉版 skill 草稿。

改寫自 SkillClaw pipeline/execution.py（evolve / create / merge），精簡為同步。
"""

from __future__ import annotations

from typing import Any, Optional

from .llm import LLMClient
from .prompts import EVOLVE_SYSTEM
from .skillmd import extract_json_object

ACTION_IMPROVE = "improve_skill"
ACTION_OPTIMIZE_DESC = "optimize_description"
ACTION_CREATE = "create_skill"
ACTION_SKIP = "skip"

_MAX_SESSIONS = 30


def _build_session_evidence(sessions: list[dict[str, Any]]) -> str:
    """把 session 證據（含分數）排序後格式化。高分在前，讓 LLM 聚焦勝出變體。"""
    ordered = sorted(sessions, key=lambda s: s.get("_score", 0.0), reverse=True)
    blocks: list[str] = []
    for s in ordered[:_MAX_SESSIONS]:
        sid = s.get("session_id", "?")
        score = s.get("_score")
        test = s.get("test") or {}
        parts = [f"### Session {sid} | score={score}"]
        if test:
            parts[0] += f" | tests {test.get('passed', 0)}/{test.get('total', 0)} pass_rate={test.get('pass_rate')}"
        if s.get("skill_name"):
            parts[0] += f" | variant_skill={s['skill_name']}"
        if s.get("_trajectory"):
            parts.append(f"**Trajectory**:\n{s['_trajectory']}")
        if s.get("_summary"):
            parts.append(f"**Analysis**:\n{s['_summary']}")
        blocks.append("\n\n".join(parts))
    if len(ordered) > _MAX_SESSIONS:
        blocks.append(f"\n... and {len(ordered) - _MAX_SESSIONS} more sessions")
    return "\n\n---\n\n".join(blocks)


def _build_skill_block(skill: dict[str, Any]) -> str:
    return (
        "## Current skill (pre-refinement / source of truth)\n\n"
        f"Name: {skill.get('name', '')}\n"
        f"Description: {skill.get('description', '')}\n"
        f"Category: {skill.get('category', 'general')}\n\n"
        f"Content:\n```\n{skill.get('content', '')}\n```\n\n"
    )


def evolve_skill_from_sessions(
    llm: LLMClient,
    skill_name: str,
    sessions: list[dict[str, Any]],
    current_skill: Optional[dict[str, Any]],
    existing_skill_names: list[str],
    *,
    temperature: float = 0.0,
) -> Optional[dict[str, Any]]:
    """對一個 skill 群組做「決策 + 執行」，回傳 {action, rationale, skill?}。

    temperature：控制精煉生成的隨機性。預設 0.0——降低 run-to-run 變異、使回測 Δ 可重現
    （見 evolve 變異實驗：temp=0.4 時同一份證據精煉出的 skill 品質會擺盪，temp=0.0 才穩定）。
    """
    system = EVOLVE_SYSTEM.replace("{skill_name}", skill_name)
    skill_section = _build_skill_block(current_skill) if current_skill else ""
    evidence = _build_session_evidence(sessions)
    user = (
        f"{skill_section}"
        f"## Session evidence ({len(sessions)} variant runs, sorted by score desc)\n\n"
        f"{evidence}\n\n"
        f"## Existing skill names in the library\n\n"
        f"{', '.join(existing_skill_names) or '(none)'}\n"
    )
    # LLM 偶爾會回出無法解析的 JSON（長 skill 內嵌 markdown 導致截斷/括號失配），
    # 造成精煉版被靜默丟棄（action=None、報告 §2 空白）。重試數次直到拿到可解析結果。
    result: Optional[dict[str, Any]] = None
    for _ in range(3):
        raw = llm.chat(system, user, temperature=temperature, max_tokens=8192)
        result = _parse_evolve_result(raw, skill_name)
        if result is not None:
            break
    return result


def _parse_evolve_result(raw: str, skill_name: str) -> Optional[dict[str, Any]]:
    result = extract_json_object(raw)
    if not isinstance(result, dict):
        return None
    action = result.get("action", ACTION_SKIP)
    if action == ACTION_SKIP:
        return {"action": ACTION_SKIP, "rationale": result.get("rationale", "")}
    skill_data = result.get("skill")
    if not isinstance(skill_data, dict):
        return None
    if action == ACTION_CREATE:
        if not skill_data.get("name"):
            return None
        if skill_data["name"] == skill_name:
            action = ACTION_IMPROVE
    elif skill_name and not skill_data.get("name"):
        skill_data["name"] = skill_name
    return {"action": action, "rationale": result.get("rationale", ""), "skill": skill_data}
