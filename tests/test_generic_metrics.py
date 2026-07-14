"""通用（場景無關）評分：原始指標、cohort 效率正規化、任務分流、防呆。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SKILL_REFINER_MOCK"] = "1"

from refiner import generic_metrics as gm
from refiner import evaluator
from refiner.llm import LLMClient


def _session(turns, runner_meta=None, **kw):
    s = {"turns": turns, "runner_meta": runner_meta or {}}
    s.update(kw)
    return s


def test_compute_raw_metrics_counts():
    s = _session([
        {"response_text": "hello", "tool_calls": [{"function": {"name": "t"}}],
         "tool_results": [{"has_error": True}, {"has_error": False}]},
        {"response_text": "world", "tool_calls": [], "tool_results": []},
    ])
    m = gm.compute_raw_metrics(s)
    assert m["num_turns"] == 2
    assert m["num_tool_calls"] == 1
    assert m["tool_error_rate"] == 0.5      # 1/2 有錯
    assert m["response_chars"] == 10        # "hello"+"world"
    assert m["elapsed_sec"] is None         # 無計時


def test_elapsed_from_runner_meta():
    s = _session([{"response_text": ""}], runner_meta={"started_at": 100.0, "ended_at": 102.5})
    assert gm.compute_raw_metrics(s)["elapsed_sec"] == 2.5


def test_normalize_efficiency_reverse_minmax():
    # 三個變體 num_turns = 1/3/5 → 最少者(1)效率最高
    raws = [{"num_turns": 1, "tool_error_rate": 0.0},
            {"num_turns": 3, "tool_error_rate": 0.0},
            {"num_turns": 5, "tool_error_rate": 0.0}]
    e1 = gm.normalize_efficiency(raws[0], raws)
    e3 = gm.normalize_efficiency(raws[2], raws)
    assert e1["per_metric"]["num_turns"] == 1.0   # 最少
    assert e3["per_metric"]["num_turns"] == 0.0   # 最多
    assert e1["efficiency_score"] > e3["efficiency_score"]


def test_all_equal_cohort_gives_neutral_one():
    raws = [{"num_turns": 2, "tool_error_rate": 0.0}] * 3
    e = gm.normalize_efficiency(raws[0], raws)
    assert e["per_metric"]["num_turns"] == 1.0   # 全相等 → 無區別 → 1.0


def test_elapsed_missing_is_skipped():
    raws = [{"num_turns": 1, "elapsed_sec": None, "tool_error_rate": 0.0},
            {"num_turns": 2, "elapsed_sec": None, "tool_error_rate": 0.0}]
    e = gm.normalize_efficiency(raws[0], raws)
    assert "elapsed_sec" in e["skipped_metrics"]
    assert "elapsed_sec" not in e["used_metrics"]


def test_resolve_task_type():
    assert evaluator.resolve_task_type({"task_type": "general"}) == "general"
    assert evaluator.resolve_task_type({"task_type": "coding"}) == "coding"
    # 無標籤但有測試訊號 → coding
    assert evaluator.resolve_task_type({"test": {"total": 5}}) == "coding"
    # 純對話、無標籤無測試 → general
    assert evaluator.resolve_task_type({"turns": [{"response_text": "hi"}]}) == "general"


def test_generic_score_penalizes_doing_nothing():
    """防呆：擺爛（completion 低）就算又快又短，分數也不會高。"""
    llm = LLMClient()  # mock；通用 judge 走 mock 的 task_completion 分支

    # 完成度高、效率中性
    good = _session([{"response_text": "完整達成任務的長回覆" * 3}], task_type="general")
    # 完成度低（用 handler 模擬），效率極高（空回覆）
    def low_completion(system, user):
        if "task-agnostic evaluator" in system.lower() or "task_completion" in system.lower():
            return '{"task_completion": 0.1, "response_quality": 0.1, "rationale": "gave up"}'
        return "[MOCK summary]"
    llm_low = LLMClient(mock_handler=low_completion)
    lazy = _session([{"response_text": ""}], task_type="general")

    gm.attach_cohort_efficiency([good, lazy])
    evaluator.evaluate_session(llm, good, _cohort_done=True)
    evaluator.evaluate_session(llm_low, lazy, _cohort_done=True)

    # 擺爛者即使效率高，分數仍遠低於有完成者
    assert lazy["_score"] < good["_score"]
    assert lazy["_success"] is False
