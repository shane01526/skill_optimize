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


# ---- cohort 按 (goal, task) 分組（不跨 task/goal 污染）------------ #


def _sess(skill_name, task_id, num_turns, variant):
    """造一個 session：num_turns 用 turns 數量表示。"""
    return {
        "skill_name": skill_name,
        "task_id": task_id,
        "variant_label": variant,
        "turns": [{"response_text": "x", "tool_calls": [], "tool_results": []} for _ in range(num_turns)],
        "runner_meta": {},
    }


def test_cohort_grouped_by_goal_task():
    # 同 goal 兩個 task：task_A 輪數 1/9、task_B 輪數 2/3
    a_fast = _sess("g", "task_A", 1, "v_a")
    a_slow = _sess("g", "task_A", 9, "v_b")
    b_fast = _sess("g", "task_B", 2, "v_a")
    b_slow = _sess("g", "task_B", 3, "v_b")
    gm.attach_cohort_efficiency([a_fast, a_slow, b_fast, b_slow])

    # 每個 session 只跟「同 task」比：各桶 size=2
    for s in (a_fast, a_slow, b_fast, b_slow):
        assert s["_metrics"]["cohort_size"] == 2
    assert a_fast["_metrics"]["cohort_key"] == "g::task_A"
    assert b_fast["_metrics"]["cohort_key"] == "g::task_B"

    # task_A 內：1 輪 → num_turns 效率 1.0；9 輪 → 0.0
    assert a_fast["_metrics"]["per_metric"]["num_turns"] == 1.0
    assert a_slow["_metrics"]["per_metric"]["num_turns"] == 0.0
    # task_B 內：2 輪 → 1.0；3 輪 → 0.0（不受 task_A 的 1/9 影響）
    assert b_fast["_metrics"]["per_metric"]["num_turns"] == 1.0
    assert b_slow["_metrics"]["per_metric"]["num_turns"] == 0.0


def test_other_bucket_does_not_affect_this_bucket():
    # 本桶固定 2/4；另一桶放極端值 100，應完全不影響本桶正規化
    this_fast = _sess("g", "t1", 2, "v_a")
    this_slow = _sess("g", "t1", 4, "v_b")
    other = _sess("g", "t2", 100, "v_a")
    gm.attach_cohort_efficiency([this_fast, this_slow, other])
    assert this_fast["_metrics"]["per_metric"]["num_turns"] == 1.0   # 本桶最小
    assert this_slow["_metrics"]["per_metric"]["num_turns"] == 0.0   # 本桶最大


def test_singleton_bucket_is_neutral():
    only = _sess("g", "solo", 7, "v_a")
    gm.attach_cohort_efficiency([only])
    assert only["_metrics"]["cohort_size"] == 1
    assert only["_metrics"]["efficiency_score"] == 1.0   # min==max → 中性
