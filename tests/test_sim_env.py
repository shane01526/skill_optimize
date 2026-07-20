"""模擬環境 + verifier + 工具迴圈（mock）：驗證多步驟業務流程的客觀狀態 gate。

重點：env 內部強制業務規則（違反則拒絕寫入），verify() 依最終狀態客觀 pass/fail，
且好 skill（有 SOP）與弱 baseline 的行為被 verify 拉開。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refiner.sim_env import make_env, make_refund_env, make_restock_env
from refiner.tool_agent import run_tool_agent

_REFUND_CASE = {
    "scenario": "refund",
    "policy": {"max_days": 30},
    "transactions": [
        {"id": "TX-1", "amount": 100, "days_since": 3, "already_refunded": False},   # 該退
        {"id": "TX-2", "amount": 250, "days_since": 40, "already_refunded": False},  # 逾期，不該退
        {"id": "TX-3", "amount": 80, "days_since": 5, "already_refunded": True},     # 已退過，不該退
        {"id": "TX-4", "amount": 60, "days_since": 10, "already_refunded": False},   # 該退
    ],
}

_RESTOCK_CASE = {
    "scenario": "restock",
    "policy": {"max_days": 14},
    "inventory": {"SKU-A": 10, "SKU-B": 3, "SKU-C": 0},
    "orders": [
        {"id": "OR-1", "sku": "SKU-A", "qty": 2, "amount": 400, "days_since": 3, "opened": False},   # 該退
        {"id": "OR-2", "sku": "SKU-B", "qty": 1, "amount": 250, "days_since": 20, "opened": False},  # 逾期
        {"id": "OR-3", "sku": "SKU-C", "qty": 5, "amount": 900, "days_since": 1, "opened": True},    # 拆封
        {"id": "OR-4", "sku": "SKU-A", "qty": 1, "amount": 180, "days_since": 10, "opened": False},  # 該退
    ],
}


# --- refund env：規則強制 + verifier ------------------------------------ #

def test_refund_legal_flow_passes():
    """先查政策 → 只退符合資格者 → verify 全過。"""
    env = make_refund_env(_REFUND_CASE)
    env.call("get_refund_policy", {})
    env.call("issue_refund", {"id": "TX-1", "amount": 100})
    env.call("issue_refund", {"id": "TX-4", "amount": 60})
    env.call("send_notification", {"to": "ops", "message": "done"})
    v = env.verify()
    assert v["passed"] is True
    assert v["checks"] == {"state_correct": 1.0, "order_correct": 1.0, "no_illegal_writes": 1.0}
    assert v["violations"] == []


def test_refund_env_rejects_ineligible_writes():
    """env 對逾期/已退/超額直接拒絕寫入（不改狀態）。"""
    env = make_refund_env(_REFUND_CASE)
    assert env.call("issue_refund", {"id": "TX-2", "amount": 250})["ok"] is False  # 逾期
    assert env.call("issue_refund", {"id": "TX-3", "amount": 80})["ok"] is False   # 已退過
    assert env.call("issue_refund", {"id": "TX-1", "amount": 999})["ok"] is False  # 超額
    assert env.state["refunds"] == {}  # 沒有任何非法寫入落地


def test_refund_no_policy_first_flags_order_violation():
    """未先查政策就退款 → order_correct=0（順序違規）。"""
    env = make_refund_env(_REFUND_CASE)
    env.call("issue_refund", {"id": "TX-1", "amount": 100})
    env.call("issue_refund", {"id": "TX-4", "amount": 60})
    v = env.verify()
    assert v["checks"]["order_correct"] == 0.0
    assert any("順序" in x for x in v["violations"])


def test_refund_missing_eligible_flags_state():
    """該退的漏退 → state 不滿分且列違規。"""
    env = make_refund_env(_REFUND_CASE)
    env.call("get_refund_policy", {})
    env.call("issue_refund", {"id": "TX-1", "amount": 100})  # 漏掉 TX-4
    v = env.verify()
    assert v["passed"] is False
    assert v["checks"]["state_correct"] < 1.0
    assert any("TX-4" in x for x in v["violations"])


# --- restock env --------------------------------------------------------- #

def test_restock_legal_flow_passes():
    env = make_restock_env(_RESTOCK_CASE)
    env.call("get_return_policy", {})
    for oid, sku, qty, amt in [("OR-1", "SKU-A", 2, 400), ("OR-4", "SKU-A", 1, 180)]:
        env.call("restock", {"sku": sku, "qty": qty})
        env.call("issue_refund", {"id": oid, "amount": amt})
    env.call("send_notification", {"to": "ops", "message": "done"})
    v = env.verify()
    assert v["passed"] is True
    assert v["checks"]["state_correct"] == 1.0
    assert env.state["restocked"] == {"SKU-A": 3}


def test_restock_env_rejects_ineligible_refund():
    env = make_restock_env(_RESTOCK_CASE)
    assert env.call("issue_refund", {"id": "OR-2", "amount": 250})["ok"] is False  # 逾期
    assert env.call("issue_refund", {"id": "OR-3", "amount": 900})["ok"] is False  # 拆封
    assert env.state["refunds"] == {}


# --- 工具迴圈（mock）：強 skill vs 弱 baseline 被拉開 ------------------- #

def test_mock_agent_strong_skill_passes_refund():
    env = make_env("refund", _REFUND_CASE)
    strong_skill = "SOP：處理前先查政策，逐筆核對資格，符合才退款。"
    run = run_tool_agent(None, "sys", "處理退款", env, mode="mock", variant_content=strong_skill)
    v = env.verify()
    assert run["steps"] >= 3
    assert "get_refund_policy" in env.called_names()
    assert v["passed"] is True
    assert v["checks"]["state_correct"] == 1.0


def test_mock_agent_weak_baseline_fails_refund():
    """弱 baseline（無 SOP 關鍵詞）→ 不查政策、對全部項目亂退 → verify 拉低。"""
    env = make_env("refund", _REFUND_CASE)
    weak_skill = "處理這個請求。"
    run = run_tool_agent(None, "sys", "處理退款", env, mode="mock", variant_content=weak_skill)
    v = env.verify()
    assert "get_refund_policy" not in env.called_names()
    assert v["passed"] is False
    assert v["checks"]["order_correct"] == 0.0
    # 逾期/已退在 env 被擋，故 no_illegal_writes 仍為 1，但漏查政策使 order 錯、且結果非全對
    assert v["checks"]["state_correct"] < 1.0 or v["checks"]["order_correct"] == 0.0


def test_mock_agent_differentiates_restock():
    strong = make_env("restock", _RESTOCK_CASE)
    weak = make_env("restock", _RESTOCK_CASE)
    run_tool_agent(None, "s", "退貨", strong, mode="mock", variant_content="先查退貨政策，逐筆核對資格。")
    run_tool_agent(None, "s", "退貨", weak, mode="mock", variant_content="處理一下。")
    sv, wv = strong.verify(), weak.verify()
    assert sv["checks"]["state_correct"] >= wv["checks"]["state_correct"]
    assert sv["checks"]["order_correct"] == 1.0
    assert wv["checks"]["order_correct"] == 0.0
