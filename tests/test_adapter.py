"""版本 B 轉接：本專案實驗紀錄 → SkillClaw session dict 形狀正確。"""

import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ADAPTER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "third_party", "adapt_to_skillclaw.py",
)


def _load_adapter():
    spec = importlib.util.spec_from_file_location("adapt_to_skillclaw", _ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_to_skillclaw_session_shape():
    adapter = _load_adapter()
    rec = {
        "session_id": "task_001::v_a",
        "skill_name": "coding-debug",
        "task_id": "task_001",
        "turns": [{"prompt_text": "fix", "response_text": "done", "tool_calls": [], "tool_results": []}],
        "test": {"pass_rate": 1.0, "all_pass": True},
        "_score": 0.92,
    }
    s = adapter.to_skillclaw_session(rec)
    assert s["session_id"] == "task_001::v_a"
    # SkillClaw 需要 read_skills 才能 aggregate
    assert s["turns"][0]["read_skills"] == [{"skill_name": "coding-debug"}]
    # 綜合分映成 prm_score，硬指標映成 benchmark.overall_score
    assert s["turns"][0]["prm_score"] == 0.92
    assert s["benchmark"]["overall_score"] == 1.0


def test_for_judge_omits_benchmark():
    """for_judge=True 時不塞 benchmark（否則 session_judge 會 skip），pass_rate 另存。"""
    adapter = _load_adapter()
    rec = {
        "session_id": "task_001::v_a", "skill_name": "coding-debug", "task_id": "task_001",
        "turns": [{"prompt_text": "fix", "response_text": "done"}],
        "test": {"pass_rate": 1.0}, "_score": 0.9,
    }
    s = adapter.to_skillclaw_session(rec, for_judge=True)
    assert "benchmark" not in s
    assert s["_pass_rate"] == 1.0
    assert "prm_score" not in s["turns"][0]  # 不塞 prm，讓 judge 執行


def test_mock_refine_end_to_end(tmp_path):
    """版本 B 離線 mock：真的跑 SkillClaw 原生 summarize+judge+aggregate+evolve+verify。"""
    import asyncio

    adapter = _load_adapter()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs = os.path.join(project_root, "logs")
    if not glob_has_json(logs):
        import pytest
        pytest.skip("no logs/ to convert; run pipeline first")

    sys.path.insert(0, os.path.join(project_root, "third_party", "skillclaw"))
    sessions = adapter.load_and_convert(logs, for_judge=True)
    result = asyncio.run(adapter._run_refine(sessions, "gpt-4o", mock=True))
    assert result["error"] is None
    assert result["action"] == "improve_skill"
    assert result["accepted"] is True
    assert result["verify"]["score"] >= 0.75
    # judge 對各變體評分，v_a 應 >= v_c
    by_variant = {j["variant_label"]: j["overall_score"] for j in result["judge_scores"]}
    assert by_variant.get("v_a", 0) >= by_variant.get("v_c", 0)


def glob_has_json(d):
    import glob
    return bool(glob.glob(os.path.join(d, "*.json")))
