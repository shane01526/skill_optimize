"""依 skill 分組 session。改寫自 SkillClaw pipeline/aggregation.py。

- session 引用 skill X → 進 X 的群組。
- 引用 A 和 B → 兩群都進。
- 沒引用任何 skill → 進 NO_SKILL_KEY。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

NO_SKILL_KEY = "__no_skill__"


def aggregate_by_skill(sessions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in sessions:
        skills = session.get("_skills_referenced") or set()
        if not skills:
            groups[NO_SKILL_KEY].append(session)
        else:
            for name in skills:
                groups[name].append(session)
    return dict(groups)
