"""In-memory 模擬業務環境 + 工具 + 最終狀態 verifier（純 Python、無外部依賴）。

用於「多步驟流程 / 需要工具與外部狀態」的 agentic 任務：agent 透過 function-calling
一步步呼叫工具（查詢 → 判斷 → 寫入 → 通知），env 內部強制業務規則、記錄軌跡，
跑完後 `verify()` 客觀檢查最終狀態是否正確（達標 gate，像 coding 的 pytest）。

兩個情境：
  - refund   ：退款審核（查政策 → 查交易 → 依資格判斷 → 符合才退 → 通知）
  - restock  ：退貨/庫存（查訂單 → 驗退貨條件 → 補庫存 → 退款 → 確認）

skill 差異點：弱 baseline 常「不查政策/條件就直接寫入」「退不該退的」「跳過通知」；
好 skill 的 SOP 會強制「先讀後寫、逐條核對、失敗要停」。
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class SimEnv:
    """一個情境的模擬環境：持有狀態、工具、與軌跡。"""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.state: dict[str, Any] = {}
        self.trajectory: list[dict[str, Any]] = []   # 每步 {name, args, result, ok}
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {}
        self._tool_specs: list[dict[str, Any]] = []   # function declarations（給 LLM）
        self.notifications: list[dict[str, str]] = []

    # -- 工具註冊 ----------------------------------------------------- #

    def register(self, name: str, description: str, params: dict[str, Any], fn: Callable[..., dict[str, Any]]) -> None:
        self._tools[name] = fn
        self._tool_specs.append({"name": name, "description": description, "parameters": params})

    def tool_specs(self) -> list[dict[str, Any]]:
        return list(self._tool_specs)

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """執行一次工具呼叫，記軌跡，回傳結果 dict（含 ok）。未知工具/例外都安全回錯誤。"""
        fn = self._tools.get(name)
        if fn is None:
            res = {"ok": False, "error": f"unknown tool: {name}"}
        else:
            try:
                res = fn(**(args or {}))
            except TypeError as exc:
                res = {"ok": False, "error": f"bad arguments: {exc}"}
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": f"tool error: {exc}"}
        self.trajectory.append({"name": name, "args": args or {}, "result": res, "ok": bool(res.get("ok", True))})
        return res

    def called_names(self) -> list[str]:
        return [t["name"] for t in self.trajectory]

    # -- 由子情境覆寫 ------------------------------------------------- #

    def verify(self) -> dict[str, Any]:  # pragma: no cover - 由工廠設定
        raise NotImplementedError


# ------------------------------------------------------------------ #
#  情境 1：退款審核                                                    #
# ------------------------------------------------------------------ #


def make_refund_env(case: dict[str, Any]) -> SimEnv:
    """退款審核。case = {"transactions": [{id, amount, currency, days_since, already_refunded}], "policy": {...}}。

    政策（get_refund_policy 會回）：可退款需同時滿足
      - days_since <= max_days（未逾期）
      - not already_refunded（未退過）
      - 退款金額 <= 原交易金額
    正解：對「符合資格」的交易發全額退款並通知；對「不符」的**不可退**。
    """
    env = SimEnv("refund")
    txns = {t["id"]: dict(t) for t in case.get("transactions", [])}
    policy = case.get("policy", {"max_days": 30})
    env.state = {"transactions": txns, "policy": policy, "refunds": {}, "policy_read": False}

    def get_refund_policy() -> dict[str, Any]:
        env.state["policy_read"] = True
        return {"ok": True, "policy": {
            "rule": "可退款需同時：未逾期(days_since<=max_days)、未退過、退款金額<=原交易金額",
            "max_days": policy.get("max_days", 30),
        }}

    def list_transactions() -> dict[str, Any]:
        return {"ok": True, "transactions": [
            {"id": t["id"], "amount": t["amount"], "currency": t.get("currency", "TWD"),
             "days_since": t["days_since"], "already_refunded": t.get("already_refunded", False)}
            for t in txns.values()
        ]}

    def get_transaction(id: str) -> dict[str, Any]:
        t = txns.get(id)
        if not t:
            return {"ok": False, "error": f"no such transaction: {id}"}
        return {"ok": True, "transaction": t}

    def issue_refund(id: str, amount: float) -> dict[str, Any]:
        # env 強制業務規則：違反則拒絕寫入（回錯誤、不改狀態）
        t = txns.get(id)
        if not t:
            return {"ok": False, "error": f"no such transaction: {id}"}
        if id in env.state["refunds"]:
            return {"ok": False, "error": "already refunded in this session"}
        if t.get("already_refunded"):
            return {"ok": False, "error": "transaction was already refunded before"}
        if t["days_since"] > policy.get("max_days", 30):
            return {"ok": False, "error": "past refund window"}
        if amount > t["amount"] + 1e-9:
            return {"ok": False, "error": "refund amount exceeds original"}
        env.state["refunds"][id] = {"amount": amount}
        return {"ok": True, "refunded": {"id": id, "amount": amount}}

    def send_notification(to: str, message: str) -> dict[str, Any]:
        env.notifications.append({"to": to, "message": message})
        return {"ok": True}

    env.register("get_refund_policy", "查詢退款政策（退款前必先查）。", {"type": "object", "properties": {}}, get_refund_policy)
    env.register("list_transactions", "列出所有待審核交易。", {"type": "object", "properties": {}}, list_transactions)
    env.register("get_transaction", "查單筆交易明細。", {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, get_transaction)
    env.register("issue_refund", "對交易發退款（會被政策擋下不符者）。", {"type": "object", "properties": {"id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["id", "amount"]}, issue_refund)
    env.register("send_notification", "寄送處理結果通知。", {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}}, "required": ["to", "message"]}, send_notification)

    def verify() -> dict[str, Any]:
        violations: list[str] = []
        max_days = policy.get("max_days", 30)
        eligible = {i for i, t in txns.items()
                    if t["days_since"] <= max_days and not t.get("already_refunded")}
        refunded = set(env.state["refunds"].keys())

        # state_correct：該退的都退了（且金額=原額）、不該退的都沒退
        missing = eligible - refunded
        illegal = refunded - eligible   # env 應已擋下，但雙重保險
        amount_ok = all(abs(env.state["refunds"][i]["amount"] - txns[i]["amount"]) < 1e-6
                        for i in refunded & eligible)
        for i in missing:
            violations.append(f"該退未退：{i}")
        for i in illegal:
            violations.append(f"不該退卻退了：{i}")
        if not amount_ok:
            violations.append("退款金額與原交易不符")
        state_correct = 1.0 if (not missing and not illegal and amount_ok) else round(
            len(eligible & refunded) / max(1, len(eligible)) * (0.0 if illegal else 1.0), 3)

        # order_correct：發任何退款前必須已查過政策
        first_refund_idx = next((k for k, s in enumerate(env.called_names()) if s == "issue_refund"), None)
        policy_idx = next((k for k, s in enumerate(env.called_names()) if s == "get_refund_policy"), None)
        order_ok = True
        if first_refund_idx is not None and (policy_idx is None or policy_idx > first_refund_idx):
            order_ok = False
            violations.append("未先查退款政策就發退款（順序錯）")

        no_illegal = 1.0 if not illegal else 0.0
        return {
            "passed": not violations,
            "checks": {"state_correct": state_correct, "order_correct": 1.0 if order_ok else 0.0, "no_illegal_writes": no_illegal},
            "violations": violations,
            "final_state": {"refunds": env.state["refunds"], "notifications": len(env.notifications)},
        }

    env.verify = verify  # type: ignore[method-assign]
    return env


# ------------------------------------------------------------------ #
#  情境 2：退貨 / 庫存                                                 #
# ------------------------------------------------------------------ #


def make_restock_env(case: dict[str, Any]) -> SimEnv:
    """退貨/庫存。case = {"orders": [{id, sku, qty, days_since, opened}], "policy": {...}, "inventory": {sku: qty}}。

    政策：可退貨需 days_since<=max_days 且 not opened（未拆封）。
    正解：對「可退」訂單 → 補回庫存(qty) + 退款 + 通知；不可退的不可動庫存/不退款。
    """
    env = SimEnv("restock")
    orders = {o["id"]: dict(o) for o in case.get("orders", [])}
    policy = case.get("policy", {"max_days": 14})
    inventory = dict(case.get("inventory", {}))
    env.state = {"orders": orders, "policy": policy, "inventory": inventory,
                 "inventory_start": dict(inventory), "refunds": {}, "restocked": {}, "policy_read": False}

    def get_return_policy() -> dict[str, Any]:
        env.state["policy_read"] = True
        return {"ok": True, "policy": {"rule": "可退貨需：未逾期(days_since<=max_days)且未拆封(opened=false)",
                                       "max_days": policy.get("max_days", 14)}}

    def get_order(id: str) -> dict[str, Any]:
        o = orders.get(id)
        return {"ok": True, "order": o} if o else {"ok": False, "error": f"no such order: {id}"}

    def list_orders() -> dict[str, Any]:
        return {"ok": True, "orders": list(orders.values())}

    def restock(sku: str, qty: int) -> dict[str, Any]:
        env.state["inventory"][sku] = env.state["inventory"].get(sku, 0) + qty
        env.state["restocked"][sku] = env.state["restocked"].get(sku, 0) + qty
        return {"ok": True, "inventory": env.state["inventory"][sku]}

    def issue_refund(id: str, amount: float) -> dict[str, Any]:
        o = orders.get(id)
        if not o:
            return {"ok": False, "error": "no such order"}
        if o["days_since"] > policy.get("max_days", 14) or o.get("opened"):
            return {"ok": False, "error": "not eligible for return (past window or opened)"}
        if id in env.state["refunds"]:
            return {"ok": False, "error": "already refunded"}
        env.state["refunds"][id] = {"amount": amount}
        return {"ok": True}

    def send_notification(to: str, message: str) -> dict[str, Any]:
        env.notifications.append({"to": to, "message": message})
        return {"ok": True}

    env.register("get_return_policy", "查詢退貨政策（退貨前必先查）。", {"type": "object", "properties": {}}, get_return_policy)
    env.register("list_orders", "列出所有退貨申請。", {"type": "object", "properties": {}}, list_orders)
    env.register("get_order", "查單筆訂單。", {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, get_order)
    env.register("restock", "把退貨商品補回庫存。", {"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["sku", "qty"]}, restock)
    env.register("issue_refund", "對可退訂單發退款。", {"type": "object", "properties": {"id": {"type": "string"}, "amount": {"type": "number"}}, "required": ["id", "amount"]}, issue_refund)
    env.register("send_notification", "寄送處理結果通知。", {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}}, "required": ["to", "message"]}, send_notification)

    def verify() -> dict[str, Any]:
        violations: list[str] = []
        max_days = policy.get("max_days", 14)
        eligible = {i for i, o in orders.items() if o["days_since"] <= max_days and not o.get("opened")}
        refunded = set(env.state["refunds"].keys())
        missing = eligible - refunded
        illegal = refunded - eligible
        for i in missing:
            violations.append(f"可退貨未處理退款：{i}")
        for i in illegal:
            violations.append(f"不可退卻退款：{i}")

        # 庫存：可退訂單的 sku 應各被補回其 qty；不可退的不應補
        expected_restock: dict[str, int] = {}
        for i in eligible:
            o = orders[i]
            expected_restock[o["sku"]] = expected_restock.get(o["sku"], 0) + o["qty"]
        restock_ok = env.state["restocked"] == expected_restock
        if not restock_ok:
            violations.append(f"庫存補貨不正確：預期 {expected_restock}、實際 {env.state['restocked']}")

        first_refund = next((k for k, s in enumerate(env.called_names()) if s == "issue_refund"), None)
        policy_idx = next((k for k, s in enumerate(env.called_names()) if s == "get_return_policy"), None)
        order_ok = True
        if first_refund is not None and (policy_idx is None or policy_idx > first_refund):
            order_ok = False
            violations.append("未先查退貨政策就處理（順序錯）")

        state_correct = 1.0 if (not missing and not illegal and restock_ok) else round(
            len(eligible & refunded) / max(1, len(eligible)) * (0.0 if illegal else 0.7)
            + (0.3 if restock_ok else 0.0), 3)
        return {
            "passed": not violations,
            "checks": {"state_correct": state_correct, "order_correct": 1.0 if order_ok else 0.0,
                       "no_illegal_writes": 1.0 if not illegal else 0.0},
            "violations": violations,
            "final_state": {"refunds": env.state["refunds"], "restocked": env.state["restocked"]},
        }

    env.verify = verify  # type: ignore[method-assign]
    return env


_FACTORIES: dict[str, Callable[[dict[str, Any]], SimEnv]] = {
    "refund": make_refund_env,
    "restock": make_restock_env,
}


def make_env(scenario: str, case: dict[str, Any]) -> Optional[SimEnv]:
    f = _FACTORIES.get(scenario)
    return f(case) if f else None
