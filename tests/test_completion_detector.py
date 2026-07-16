"""規則式 completion detector：使用者行為訊號判定達標（零 LLM）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["SKILL_REFINER_MOCK"] = "1"

from refiner.completion_detector import detect_completion
from refiner import evaluator, generic_metrics
from refiner.llm import LLMClient


def _sess(*pairs):
    """pairs = [(prompt, response), ...] → session。"""
    turns = [
        {"prompt_text": p, "response_text": r, "tool_calls": [], "tool_results": []}
        for p, r in pairs
    ]
    return {"task_type": "general", "turns": turns}


def test_negative_followup_not_completed():
    s = _sess(("幫我寫公告", "草稿..."), ("還是不對，重寫一次", ""))
    d = detect_completion(s)
    assert d["verdict"] == "not_completed"
    assert d["completion"] < 0.5
    assert d["confidence"] >= 0.5
    assert any(x["type"] == "negative" for x in d["signals"])


def test_positive_followup_completed():
    s = _sess(("幫我寫公告", "草稿..."), ("讚，就是這個，謝謝", ""))
    d = detect_completion(s)
    assert d["verdict"] == "completed"
    assert d["completion"] > 0.5
    assert d["confidence"] >= 0.5


def test_reformulation_detected():
    s = _sess(("幫我把這段翻成英文", "translation..."), ("幫我把這段翻譯成英文", ""))
    d = detect_completion(s)
    assert any(x["type"] == "reformulation" for x in d["signals"])
    assert d["verdict"] == "not_completed"


def test_coding_retry_signal():
    s = _sess(("修好測試", "改了..."), ("still failing", ""))
    d = detect_completion(s)
    assert d["completion"] < 0.5
    assert any(x["type"] in ("coding_retry", "negative") for x in d["signals"])


def test_continue_next_is_completed():
    s = _sess(("幫我寫公告", "草稿..."), ("接著幫我寫英文版", "英文版..."), ("OK 可以了", ""))
    d = detect_completion(s)
    assert d["verdict"] == "completed"


def test_single_turn_low_confidence():
    """單輪無後續 user 回覆 → 信心低（觸發 fallback）。"""
    s = _sess(("幫我寫公告", "草稿..."))
    d = detect_completion(s)
    assert d["confidence"] < evaluator.CONFIDENCE_THRESHOLD


def test_adopt_tool_signal():
    s = {
        "task_type": "general",
        "turns": [
            {"prompt_text": "修這個 bug", "response_text": "patch...",
             "tool_calls": [{"function": {"name": "apply_patch"}}],
             "tool_results": [{"tool_name": "apply_patch", "has_error": False}]},
        ],
    }
    d = detect_completion(s)
    assert any(x["type"] == "adopt_tool" for x in d["signals"])


# ---- evaluator 分流：規則優先，模糊退 LLM ---- #


def test_evaluator_uses_rule_when_confident():
    """高信心 → 用規則、不呼叫 LLM。"""
    calls = {"n": 0}

    def counting_handler(system, user):
        calls["n"] += 1
        return '{"task_completion": 0.5, "response_quality": 0.5, "rationale": "x"}'

    llm = LLMClient(mock_handler=counting_handler)
    s = _sess(("幫我寫公告", "草稿..."), ("不對，重寫", "..."), ("還是不行，你沒懂", ""))
    generic_metrics.attach_cohort_efficiency([s])
    evaluator.evaluate_session(llm, s, _cohort_done=True)
    assert s["_metrics"]["completion_source"] == "rule"
    assert calls["n"] == 0            # 完全沒呼叫 LLM
    assert s["_metrics"]["completion"] < 0.5


def test_evaluator_falls_back_to_llm_when_unsure():
    """單輪低信心 → 退回 LLM judge。"""
    calls = {"n": 0}

    def counting_handler(system, user):
        calls["n"] += 1
        return '{"task_completion": 0.8, "response_quality": 0.8, "rationale": "ok"}'

    llm = LLMClient(mock_handler=counting_handler)
    s = _sess(("幫我寫公告", "草稿（無使用者後續回覆）"))
    generic_metrics.attach_cohort_efficiency([s])
    evaluator.evaluate_session(llm, s, _cohort_done=True)
    assert s["_metrics"]["completion_source"] == "llm"
    assert calls["n"] >= 1            # 有呼叫 LLM fallback
