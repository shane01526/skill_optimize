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


# ------------------------------------------------------------------ #
#  情境 3：退款核准（深難：多相依步驟 + 政策衝突 + 預算 horizon + 無防呆） #
# ------------------------------------------------------------------ #


def make_approval_env(case: dict[str, Any]) -> SimEnv:
    """退款核准（本專案最難情境）。case = {
        "policy": {"daily_budget": 5000, "vip_days": 60, "base_days": 30},
        "requests": [{"id", "customer", "tier"("vip"/"normal"), "days_since",
                      "amount", "promo"("FINAL"或空), "fraud"(bool)}],
    }

    與 refund/restock 的關鍵差異：**env 不再強制業務規則**（無硬性防呆）。
    issue_refund / deduct_loyalty 一律照單全收、直接寫入狀態、永遠回 ok；
    因此「不查政策就亂退」「退不該退的」「超預算」「漏扣點」的錯誤會**真的落地**，
    只能靠 verify() 事後比對「正確最終狀態」抓出來（no_illegal_writes 這次會真的變動）。

    四軸難度：
      1. 多相依步驟：查政策 → 逐筆判資格 → 依優先序排序 → 受預算逐筆核銷 → 每筆連動扣點 → 通知。
      2. 政策衝突需推理（優先序）：fraud（不退，最高）＞ promo=FINAL（不退）＞ VIP 窗（vip_days）＞ 基本窗（base_days）。
      3. 長 horizon：daily_budget 需累計已退金額，超過的 eligible 項目要 defer（不退）。
      4. 無防呆（見上）。
    正解退款順序：VIP 優先，其餘同組按 id 升冪；逐筆累計，破預算者 defer。
    連動：每筆成功退款須對該客戶扣 floor(amount/10) 點。
    """
    env = SimEnv("approval")
    reqs = {r["id"]: dict(r) for r in case.get("requests", [])}
    policy = case.get("policy", {"daily_budget": 5000, "vip_days": 60, "base_days": 30})
    daily_budget = policy.get("daily_budget", 5000)
    vip_days = policy.get("vip_days", 60)
    base_days = policy.get("base_days", 30)
    env.state = {"requests": reqs, "policy": policy, "refunds": {}, "loyalty": {}, "policy_read": False}

    def get_refund_policy() -> dict[str, Any]:
        env.state["policy_read"] = True
        return {"ok": True, "policy": {
            "priority": "依序判斷（高到低）：1) fraud=true 一律不退；2) promo=FINAL 一律不退；"
                        "3) VIP 客戶退款窗為 vip_days 天；4) 一般客戶退款窗為 base_days 天。",
            "daily_budget": daily_budget, "vip_days": vip_days, "base_days": base_days,
            "processing_order": "VIP 優先，其餘按申請 id 升冪；逐筆累計已退金額，超過每日預算者一律 defer（不退）。",
            "loyalty_rule": "每筆成功退款，必須對該客戶連動扣除 floor(退款金額/10) 點會員點數。",
        }}

    def list_requests() -> dict[str, Any]:
        return {"ok": True, "requests": [
            {"id": r["id"], "customer": r["customer"], "tier": r.get("tier", "normal"),
             "days_since": r["days_since"], "amount": r["amount"],
             "promo": r.get("promo", ""), "fraud": bool(r.get("fraud", False))}
            for r in reqs.values()
        ]}

    def get_request(id: str) -> dict[str, Any]:
        r = reqs.get(id)
        return {"ok": True, "request": r} if r else {"ok": False, "error": f"no such request: {id}"}

    # --- 寫入工具：寬鬆、不擋、永遠 ok（本輪關鍵：無防呆） --- #
    def issue_refund(id: str, amount: float) -> dict[str, Any]:
        env.state["refunds"][id] = {"amount": amount}
        return {"ok": True, "refunded": {"id": id, "amount": amount}}

    def deduct_loyalty(customer: str, points: int) -> dict[str, Any]:
        env.state["loyalty"][customer] = env.state["loyalty"].get(customer, 0) + points
        return {"ok": True, "loyalty_balance_delta": points}

    def send_notification(to: str, message: str) -> dict[str, Any]:
        env.notifications.append({"to": to, "message": message})
        return {"ok": True}

    env.register("get_refund_policy", "查詢退款政策（含優先序、每日預算、連動扣點規則）。寫入前必先查。",
                 {"type": "object", "properties": {}}, get_refund_policy)
    env.register("list_requests", "列出所有待審核退款申請。", {"type": "object", "properties": {}}, list_requests)
    env.register("get_request", "查單筆申請明細。",
                 {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, get_request)
    env.register("issue_refund", "對申請發退款（注意：本系統不會替你把關資格/預算，請自行依政策判斷）。",
                 {"type": "object", "properties": {"id": {"type": "string"}, "amount": {"type": "number"}},
                  "required": ["id", "amount"]}, issue_refund)
    env.register("deduct_loyalty", "對客戶扣除會員點數（每筆退款須連動呼叫）。",
                 {"type": "object", "properties": {"customer": {"type": "string"}, "points": {"type": "integer"}},
                  "required": ["customer", "points"]}, deduct_loyalty)
    env.register("send_notification", "寄送處理結果通知。",
                 {"type": "object", "properties": {"to": {"type": "string"}, "message": {"type": "string"}},
                  "required": ["to", "message"]}, send_notification)

    def _is_eligible(r: dict[str, Any]) -> bool:
        if r.get("fraud"):
            return False
        if r.get("promo") == "FINAL":
            return False
        window = vip_days if r.get("tier") == "vip" else base_days
        return r["days_since"] <= window

    def _expected() -> tuple[dict[str, float], dict[str, int]]:
        """依優先序＋預算算出正解 refunds{id:amount} 與 loyalty{customer:points}。"""
        eligible = [r for r in reqs.values() if _is_eligible(r)]
        # 處理順序：VIP 優先(0)，其餘(1)；同組按 id 升冪
        eligible.sort(key=lambda r: (0 if r.get("tier") == "vip" else 1, r["id"]))
        exp_ref: dict[str, float] = {}
        exp_loy: dict[str, int] = {}
        cum = 0.0
        for r in eligible:
            if cum + r["amount"] > daily_budget:
                continue  # 破預算 → defer（不退，且不因後面較小的就跳著退）
            cum += r["amount"]
            exp_ref[r["id"]] = float(r["amount"])
            exp_loy[r["customer"]] = exp_loy.get(r["customer"], 0) + int(r["amount"] // 10)
        return exp_ref, exp_loy

    def verify() -> dict[str, Any]:
        violations: list[str] = []
        exp_ref, exp_loy = _expected()
        got_ref = {i: v["amount"] for i, v in env.state["refunds"].items()}
        got_loy = {c: p for c, p in env.state["loyalty"].items() if p}

        exp_ids, got_ids = set(exp_ref), set(got_ref)
        illegal = got_ids - exp_ids          # 不該退卻退了（fraud/FINAL/逾期/超預算 defer）
        missing = exp_ids - got_ids          # 該退漏退
        amount_wrong = {i for i in exp_ids & got_ids if abs(got_ref[i] - exp_ref[i]) > 1e-6}

        for i in sorted(illegal):
            r = reqs.get(i, {})
            why = ("fraud" if r.get("fraud") else "FINAL 不可退" if r.get("promo") == "FINAL"
                   else "逾期" if not _is_eligible(r) else "超每日預算應 defer")
            violations.append(f"不該退卻退了：{i}（{why}）")
        for i in sorted(missing):
            violations.append(f"該退漏退：{i}")
        for i in sorted(amount_wrong):
            violations.append(f"退款金額錯誤：{i}（應={exp_ref[i]}、實={got_ref[i]}）")
        if got_loy != exp_loy:
            violations.append(f"連動扣點不正確：應={exp_loy}、實={got_loy}")

        # state_correct：退款集合/金額全對 且 連動扣點全對 → 1.0；否則按命中比例（且有非法寫入直接歸零命中率）
        refunds_perfect = (not illegal and not missing and not amount_wrong)
        loyalty_perfect = (got_loy == exp_loy)
        if refunds_perfect and loyalty_perfect:
            state_correct = 1.0
        else:
            hit = len(exp_ids & got_ids) - len(amount_wrong)
            base = (hit / max(1, len(exp_ids))) * (0.0 if illegal else 0.7)
            state_correct = round(base + (0.3 if loyalty_perfect else 0.0), 3)

        # order_correct：任何寫入（退款/扣點）前必須已查政策
        write_ops = {"issue_refund", "deduct_loyalty"}
        first_write = next((k for k, s in enumerate(env.called_names()) if s in write_ops), None)
        policy_idx = next((k for k, s in enumerate(env.called_names()) if s == "get_refund_policy"), None)
        order_ok = True
        if first_write is not None and (policy_idx is None or policy_idx > first_write):
            order_ok = False
            violations.append("未先查退款政策就寫入（順序錯）")

        no_illegal = 1.0 if not illegal else 0.0
        return {
            "passed": not violations,
            "checks": {"state_correct": state_correct, "order_correct": 1.0 if order_ok else 0.0,
                       "no_illegal_writes": no_illegal},
            "violations": violations,
            "final_state": {"refunds": env.state["refunds"], "loyalty": got_loy,
                            "expected_refunds": exp_ref, "expected_loyalty": exp_loy},
        }

    env.verify = verify  # type: ignore[method-assign]
    return env


_FACTORIES: dict[str, Callable[[dict[str, Any]], SimEnv]] = {
    "refund": make_refund_env,
    "restock": make_restock_env,
    "approval": make_approval_env,
}


def make_env(scenario: str, case: dict[str, Any]) -> Optional[SimEnv]:
    f = _FACTORIES.get(scenario)
    return f(case) if f else None
