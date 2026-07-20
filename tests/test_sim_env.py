"""模擬環境 + verifier + 工具迴圈（mock）：驗證多步驟業務流程的客觀狀態 gate。

重點：env 內部強制業務規則（違反則拒絕寫入），verify() 依最終狀態客觀 pass/fail，
且好 skill（有 SOP）與弱 baseline 的行為被 verify 拉開。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refiner.sim_env import make_approval_env, make_env, make_refund_env, make_restock_env
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


# --- approval env（深難：政策衝突＋預算＋連動扣點＋無防呆） ------------- #

_APPROVAL_CASE = {
    "scenario": "approval",
    "policy": {"daily_budget": 5000, "vip_days": 60, "base_days": 30},
    "requests": [
        {"id": "R1", "customer": "C1", "tier": "normal", "days_since": 10, "amount": 800,  "promo": "",      "fraud": False},  # 退
        {"id": "R2", "customer": "C2", "tier": "normal", "days_since": 45, "amount": 500,  "promo": "",      "fraud": False},  # 逾期
        {"id": "R3", "customer": "C3", "tier": "vip",    "days_since": 45, "amount": 1200, "promo": "",      "fraud": False},  # 退(VIP窗)
        {"id": "R4", "customer": "C4", "tier": "vip",    "days_since": 20, "amount": 900,  "promo": "FINAL", "fraud": False},  # FINAL
        {"id": "R5", "customer": "C5", "tier": "normal", "days_since": 5,  "amount": 2000, "promo": "",      "fraud": True},   # fraud
        {"id": "R6", "customer": "C6", "tier": "vip",    "days_since": 55, "amount": 1500, "promo": "",      "fraud": False},  # 退
        {"id": "R7", "customer": "C7", "tier": "normal", "days_since": 25, "amount": 700,  "promo": "",      "fraud": False},  # defer(超預算)
        {"id": "R8", "customer": "C8", "tier": "vip",    "days_since": 10, "amount": 1000, "promo": "",      "fraud": False},  # 退
    ],
}

# 正解：VIP 先、按 id → R3(1200)+R6(1500)+R8(1000)+R1(800)=4500；R7 破 5000 → defer
_EXPECTED_REFUNDS = {"R3", "R6", "R8", "R1"}
_EXPECTED_LOYALTY = {"C3": 120, "C6": 150, "C8": 100, "C1": 80}


def _process_correctly(env):
    """依正解對 approval env 下正確工具呼叫（查政策 → 只退 eligible 且不破預算 → 連動扣點）。"""
    env.call("get_refund_policy", {})
    for oid, cust, amt in [("R3", "C3", 1200), ("R6", "C6", 1500), ("R8", "C8", 1000), ("R1", "C1", 800)]:
        env.call("issue_refund", {"id": oid, "amount": amt})
        env.call("deduct_loyalty", {"customer": cust, "points": amt // 10})
    env.call("send_notification", {"to": "ops", "message": "done"})


def test_approval_correct_flow_passes():
    env = make_approval_env(_APPROVAL_CASE)
    _process_correctly(env)
    v = env.verify()
    assert v["passed"] is True, v["violations"]
    assert v["checks"] == {"state_correct": 1.0, "order_correct": 1.0, "no_illegal_writes": 1.0}
    assert set(env.state["refunds"].keys()) == _EXPECTED_REFUNDS
    assert v["final_state"]["expected_loyalty"] == _EXPECTED_LOYALTY


def test_approval_env_has_no_guardrails():
    """本輪關鍵：env 不擋任何寫入。對 fraud/逾期呼叫 issue_refund 仍回 ok 且狀態被寫入
    （與 refund/restock 情境相反），但 verify() 事後標為違規、no_illegal_writes=0。"""
    env = make_approval_env(_APPROVAL_CASE)
    assert env.call("issue_refund", {"id": "R5", "amount": 2000})["ok"] is True   # fraud，卻照退
    assert env.call("issue_refund", {"id": "R2", "amount": 500})["ok"] is True    # 逾期，卻照退
    assert "R5" in env.state["refunds"] and "R2" in env.state["refunds"]          # 錯誤真的落地
    v = env.verify()
    assert v["checks"]["no_illegal_writes"] == 0.0
    assert any("R5" in x for x in v["violations"])


def test_approval_over_budget_refund_flagged():
    """多退一筆使累計超預算（R7 本應 defer）→ state 不滿分且列違規。"""
    env = make_approval_env(_APPROVAL_CASE)
    _process_correctly(env)                              # 已退 4500
    env.call("issue_refund", {"id": "R7", "amount": 700})  # 破 5000
    env.call("deduct_loyalty", {"customer": "C7", "points": 70})
    v = env.verify()
    assert v["passed"] is False
    assert v["checks"]["no_illegal_writes"] == 0.0
    assert any("R7" in x and "預算" in x for x in v["violations"])


def test_approval_missing_loyalty_flagged():
    """連動扣點漏掉 → state_correct<1 且列違規（退款對但扣點錯）。"""
    env = make_approval_env(_APPROVAL_CASE)
    env.call("get_refund_policy", {})
    for oid, amt in [("R3", 1200), ("R6", 1500), ("R8", 1000), ("R1", 800)]:
        env.call("issue_refund", {"id": oid, "amount": amt})   # 只退不扣點
    v = env.verify()
    assert v["checks"]["state_correct"] < 1.0
    assert any("扣點" in x for x in v["violations"])


def test_mock_agent_differentiates_approval():
    strong = make_env("approval", _APPROVAL_CASE)
    weak = make_env("approval", _APPROVAL_CASE)
    run_tool_agent(None, "s", "核准退款", strong, mode="mock",
                   variant_content="先查政策，依優先序逐筆核對資格，累計預算，每退必扣點。")
    run_tool_agent(None, "s", "核准退款", weak, mode="mock", variant_content="處理一下。")
    sv, wv = strong.verify(), weak.verify()
    assert sv["passed"] is True
    assert sv["checks"]["state_correct"] == 1.0
    # 弱 baseline：無防呆使違規退款落地 → 明顯被拉開
    assert wv["checks"]["no_illegal_writes"] == 0.0
    assert wv["checks"]["state_correct"] < sv["checks"]["state_correct"]
    assert wv["checks"]["order_correct"] == 0.0
