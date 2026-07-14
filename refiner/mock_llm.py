"""離線 Mock LLM：讓整條 pipeline 在沒有 API key 時也能端到端跑通。

依 system prompt 的特徵字串判斷目前是哪個階段，回傳形狀正確的假輸出：
  - summarizer  → 純文字摘要
  - session judge → judge JSON（四維分數）
  - evolve      → improve_skill JSON（把勝出證據併回原 skill）
  - verifier    → accept JSON（分數 ≥ 0.75）

**這不是真的精煉**，只用於流程驗證 / 單元測試 / demo；真正精煉請設定
ANTHROPIC_API_KEY 或 OPENAI_API_KEY。
"""

from __future__ import annotations

import json
import re


def default_mock_response(system: str, user: str) -> str:
    s = system.lower()

    # -- session judge --------------------------------------------------- #
    if "session-level evaluator" in s or "task_completion" in s:
        # 從 user payload 裡撈既有 prm/aggregate 當基準，讓分數有點變化
        base = 0.8
        m = re.search(r'"avg_prm_before_judge":\s*([0-9.]+)', user)
        if m:
            try:
                base = max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        tc, rq, ef, tu = base, base, min(1.0, base + 0.05), base
        overall = round(tc * 0.55 + rq * 0.30 + ef * 0.05 + tu * 0.10, 3)
        return json.dumps(
            {
                "task_completion": tc,
                "response_quality": rq,
                "efficiency": ef,
                "tool_usage": tu,
                "overall_score": overall,
                "rationale": "[MOCK] 依既有分數推估的離線判斷。",
            }
        )

    # -- verifier -------------------------------------------------------- #
    if "final publication gate" in s or "safe_to_publish" in s:
        return json.dumps(
            {
                "decision": "accept",
                "score": 0.86,
                "reason": "[MOCK] 候選 skill 有證據支撐且保留既有具體資訊。",
                "checks": {
                    "grounded_in_evidence": 0.85,
                    "preserves_existing_value": 0.9,
                    "specificity_and_reusability": 0.85,
                    "safe_to_publish": 0.85,
                },
            }
        )

    # -- evolve from sessions ------------------------------------------- #
    if "skill evolution system" in s or "improve_skill" in s:
        cur = _extract_block(user, "Content:")
        name = _extract_field(user, "Name:") or "coding-debug"
        merged = (cur or "").strip()
        merged += (
            "\n\n## 精煉補充（[MOCK] 由勝出變體證據萃取）\n"
            "- 先重現失敗測試，再定位最小修改點。\n"
            "- 修完只跑相關測試快速回饋，全綠後再跑完整套件。\n"
        )
        return json.dumps(
            {
                "action": "improve_skill",
                "rationale": "[MOCK] 勝出變體共通做法：先重現、最小修改、分段驗證。",
                "skill": {
                    "name": name,
                    "description": _extract_field(user, "Description:")
                    or "Use for debugging failing tests.",
                    "content": merged,
                    "category": "coding",
                    "edit_summary": {
                        "preserved_sections": ["原始全部"],
                        "changed_sections": ["新增：精煉補充"],
                        "notes": "[MOCK]",
                    },
                },
            }
        )

    # -- create from no-skill bucket ------------------------------------ #
    if "no existing skill was referenced" in s:
        return json.dumps({"action": "skip", "rationale": "[MOCK] 無足夠共通 pattern。"})

    # -- summarizer (預設) ---------------------------------------------- #
    return (
        "[MOCK summary] 代理人讀取 skill 後嘗試修復失敗測試："
        "先重現錯誤、定位問題、做最小修改，最後跑測試驗證。"
        "skill 對定位步驟有幫助；整體任務完成。"
    )


def _extract_field(text: str, label: str) -> str:
    m = re.search(rf"{re.escape(label)}\s*(.+)", text)
    return m.group(1).strip() if m else ""


def _extract_block(text: str, label: str) -> str:
    """撈 ``Content:`` 之後第一個 ``` 圍起來的區塊。"""
    idx = text.find(label)
    if idx == -1:
        return ""
    seg = text[idx:]
    m = re.search(r"```\s*\n?(.*?)```", seg, re.DOTALL)
    return m.group(1).strip() if m else ""
