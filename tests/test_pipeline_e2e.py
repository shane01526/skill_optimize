"""端到端（mock 模式）：跑一輪實驗 + 精煉，確認勝出變體被萃取、爛變體不勝出、
驗證閘會擋、registry 版本 +1、對照表產出。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SKILL_REFINER_MOCK"] = "1"

from refiner import pipeline
from refiner.llm import LLMClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOAL = os.path.join(PROJECT_ROOT, "skills", "coding-debug")
TASKS = os.path.join(PROJECT_ROOT, "golden", "tasks")


def test_full_run(tmp_path):
    logs = str(tmp_path / "logs")
    out = str(tmp_path / "out")
    llm = LLMClient()  # mock

    pipeline.run_experiment(GOAL, TASKS, logs, mode="mock", llm=llm)
    summary = pipeline.refine(logs, GOAL, out, llm=llm, min_score=0.75,
                              registry_path=str(tmp_path / "reg.json"))

    # 精煉動作為 improve、被採用、版本 +1
    assert summary["action"] == "improve_skill"
    assert summary["accepted"] is True
    assert summary["new_version"] == 1

    # 對照表與精煉版草稿產出
    assert os.path.exists(os.path.join(out, "before_after.json"))
    assert os.path.exists(summary["refined_skill_path"])

    # 兩個 golden task × 3 變體 = 6 sessions
    import json
    report = json.load(open(os.path.join(out, "before_after.json"), encoding="utf-8"))
    assert len(report["variant_scores"]) == 6

    # 勝出變體是 v_a（指引最強 → pytest 全過），winner 依跨 task 平均選出
    assert report["winner"]["variant"] == "v_a"
    agg = {a["variant"]: a["avg_score"] for a in report["variant_aggregate"]}
    assert agg["v_a"] > agg["v_b"] > agg["v_c"]

    # 每變體都帶 actual_used_skill_ids
    assert all(a["actual_used_skill_ids"] for a in report["variant_aggregate"])


def test_verifier_blocks_low_score(tmp_path):
    """驗證閘：verifier 回傳低分時，候選不被採用。"""
    from refiner import verifier

    def low_score_handler(system, user):
        if "publication gate" in system.lower() or "safe_to_publish" in system.lower():
            return '{"decision":"reject","score":0.4,"reason":"weak","checks":{"grounded_in_evidence":0.4,"preserves_existing_value":0.4,"specificity_and_reusability":0.4,"safe_to_publish":0.4}}'
        return "irrelevant"

    llm = LLMClient(mock_handler=low_score_handler)
    verdict = verifier.verify_candidate(
        llm, {"name": "x", "description": "d", "content": "c"}, [], "improve_skill",
        current_skill={"name": "x", "content": "old"}, min_score=0.75,
    )
    assert verdict["accepted"] is False
    assert verdict["score"] == 0.4


def test_publish_all_variants_pass(tmp_path):
    """publish：4 個 SKILL.md（baseline + 3 變體）上架驗證全通過。"""
    out = str(tmp_path / "out")
    outcome = pipeline.publish_skills(GOAL, out, registry_path=str(tmp_path / "reg.json"))
    assert outcome["failed"] == 0
    assert outcome["passed"] == 4
    assert all(r["skill_id"] == "coding-debug" for r in outcome["results"])
