"""Gemini function-calling 迴圈：讓 agent 對 SimEnv 一步步呼叫工具完成多步驟任務。

model 回 function_call → 用 env 執行 → 把 function_response 塞回對話 → 迴圈到 model 給最終
文字或達 max_steps。完整工具軌跡記在 env.trajectory。

mock 模式：不呼叫 Gemini，用「腳本化假 agent」依 skill 內容決定走幾步（供離線 pytest / demo）。
"""

from __future__ import annotations

from typing import Any, Optional

from .sim_env import SimEnv


def _to_gemini_tools(env: SimEnv):
    from google.genai import types

    decls = [
        types.FunctionDeclaration(name=s["name"], description=s["description"], parameters=s["parameters"])
        for s in env.tool_specs()
    ]
    return [types.Tool(function_declarations=decls)]


def run_tool_agent(llm, system: str, task_prompt: str, env: SimEnv, *, max_steps: int = 12,
                   mode: str = "api", variant_content: str = "") -> dict[str, Any]:
    """驅動一次 agentic 執行；回 {final_text, steps, transcript}。env 狀態被就地更新。"""
    if mode == "mock":
        return _run_mock_agent(system, task_prompt, env, variant_content)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=llm._api_key)
    tools = _to_gemini_tools(env)
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        temperature=0.0,  # 決定性：讓「證據生成」與「打分」的工具迴圈可重現，回測 Δ 才不被採樣雜訊主導
        max_output_tokens=2048,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=task_prompt)])]
    transcript: list[dict[str, Any]] = []
    final_text = ""

    for _ in range(max_steps):
        try:
            resp = client.models.generate_content(model=llm.model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001
            transcript.append({"type": "error", "text": str(exc)[:200]})
            break

        cand = (resp.candidates or [None])[0]
        parts = (cand.content.parts if cand and cand.content else None) or []
        fcalls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        if not fcalls:
            final_text = resp.text or ""
            if final_text:
                transcript.append({"type": "final", "text": final_text})
            break

        # model 這一輪要呼叫工具（可能多個）→ 逐一執行、回傳
        contents.append(types.Content(role="model", parts=parts))
        resp_parts = []
        for fc in fcalls:
            name = fc.name
            args = dict(fc.args or {})
            result = env.call(name, args)
            transcript.append({"type": "tool", "name": name, "args": args, "result": result})
            resp_parts.append(types.Part.from_function_response(name=name, response=result))
        contents.append(types.Content(role="user", parts=resp_parts))

    return {"final_text": final_text, "steps": len(env.trajectory), "transcript": transcript}


def _run_mock_agent(system: str, task_prompt: str, env: SimEnv, variant_content: str) -> dict[str, Any]:
    """離線假 agent：依 skill 內容『強度』決定行為，供 pytest/demo（不呼叫 LLM）。

    強 skill（含「先查政策/先讀後寫」關鍵詞）→ 正確流程；弱 → 不查政策直接對所有項目寫入。
    """
    strong = any(k in variant_content for k in ("先查", "政策", "先讀後寫", "SOP", "資格", "檢查"))
    transcript: list[dict[str, Any]] = []

    def rec(name, args):
        r = env.call(name, args)
        transcript.append({"type": "tool", "name": name, "args": args, "result": r})
        return r

    if env.scenario == "refund":
        if strong:
            rec("get_refund_policy", {})
        lst = rec("list_transactions", {}).get("transactions", [])
        for t in lst:
            if strong:
                # 好流程：只對符合資格者退款
                if t["days_since"] <= env.state["policy"].get("max_days", 30) and not t.get("already_refunded"):
                    rec("issue_refund", {"id": t["id"], "amount": t["amount"]})
            else:
                # 壞流程：不查政策，全部都試退
                rec("issue_refund", {"id": t["id"], "amount": t["amount"]})
        rec("send_notification", {"to": "ops", "message": "processed"})
    elif env.scenario == "restock":
        if strong:
            rec("get_return_policy", {})
        orders = rec("list_orders", {}).get("orders", [])
        for o in orders:
            eligible = o["days_since"] <= env.state["policy"].get("max_days", 14) and not o.get("opened")
            if strong:
                if eligible:
                    rec("restock", {"sku": o["sku"], "qty": o["qty"]})
                    rec("issue_refund", {"id": o["id"], "amount": o.get("amount", 0)})
            else:
                rec("restock", {"sku": o["sku"], "qty": o["qty"]})
                rec("issue_refund", {"id": o["id"], "amount": o.get("amount", 0)})
        rec("send_notification", {"to": "ops", "message": "processed"})
    elif env.scenario == "approval":
        pol = env.state["policy"]
        budget = pol.get("daily_budget", 5000)
        vip_days, base_days = pol.get("vip_days", 60), pol.get("base_days", 30)
        if strong:
            rec("get_refund_policy", {})
        reqs = rec("list_requests", {}).get("requests", [])
        if strong:
            # 好流程：依優先序過濾 → VIP 優先排序 → 逐筆累計預算、超則停 → 連動扣點
            def _elig(r):
                if r.get("fraud") or r.get("promo") == "FINAL":
                    return False
                return r["days_since"] <= (vip_days if r.get("tier") == "vip" else base_days)
            elig = sorted((r for r in reqs if _elig(r)),
                          key=lambda r: (0 if r.get("tier") == "vip" else 1, r["id"]))
            cum = 0.0
            for r in elig:
                if cum + r["amount"] > budget:
                    continue  # defer
                cum += r["amount"]
                rec("issue_refund", {"id": r["id"], "amount": r["amount"]})
                rec("deduct_loyalty", {"customer": r["customer"], "points": int(r["amount"] // 10)})
        else:
            # 壞流程：不查政策、對每一筆都退（含 fraud/FINAL/逾期/超預算）、不扣點
            for r in reqs:
                rec("issue_refund", {"id": r["id"], "amount": r["amount"]})
        rec("send_notification", {"to": "ops", "message": "processed"})

    return {"final_text": "[MOCK agent] done", "steps": len(env.trajectory), "transcript": transcript}
