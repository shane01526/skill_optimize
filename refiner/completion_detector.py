"""規則式 completion detector：從使用者後續行為/回覆推斷任務是否達標（零 LLM）。

思路來自 IR / 推薦系統的 implicit feedback：不問使用者「滿意嗎」，而是看他
「接下來做什麼」——重述同一需求、說「不對」、要求重試 = 未達標；說「謝謝就是這個」、
採用產物、接著問新任務、或會話自然結束 = 達標。全部用關鍵詞 / 正則 / 文字相似度判斷，
不呼叫 LLM。

輸出 {completion: 0..1, confidence: 0..1, signals: [...], verdict}，供 evaluator 當
general 任務的達標 gate（信心足 → 直接用；不足 → 由 evaluator fallback 到 LLM judge）。

限制：訊號來自「agent 回覆後使用者的下一輪」，故在**多輪真實對話**最有效；單輪
headless session（無後續 user turn）會落在低信心，觸發 fallback。
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# ------------------------------------------------------------------ #
#  訊號關鍵詞表（中英雙語，可擴充）。權重為該訊號的強度。               #
# ------------------------------------------------------------------ #

# 未達標（負向），權重越大訊號越強
_NEGATIVE = {
    r"不對|錯了|不是這個|不是我要|你誤會|理解錯|搞錯|重來|還是不(對|行|能)|沒有解決|沒解決": 1.0,
    r"\b(wrong|incorrect|not what i|that'?s not|doesn'?t work|still (broken|failing|not)|try again|redo|nope)\b": 1.0,
}
# coding 接續：要求繼續修 = 未達標
_CODING_RETRY = {
    r"還是(失敗|錯|不過)|再(試|修|跑)一次|修(一下|好)|繼續修|沒過": 0.9,
    r"\b(still failing|still broken|fix (it|this|that)|error again|test.*fail)\b": 0.9,
}
# 達標（正向 / 確認），權重越大訊號越強
_POSITIVE = {
    r"謝謝|感謝|讚|太好了|就是這個|可以了|對了|沒問題了|正確|完美|太棒|收到.*可用": 1.0,
    r"\b(thanks|thank you|perfect|great|awesome|lgtm|looks good|works now|that'?s (it|right|correct)|nailed it)\b": 1.0,
}
# 接續新任務（隱含前一件已完成）= 達標（弱）
_CONTINUE_NEXT = {
    r"接(著|下來)|下一(個|步|題)|再(幫我|做|寫)(另|一)|換(一|個)|然後(幫我|請)|另外(一件|還有)": 0.6,
    r"\b(next|now (do|let'?s)|another|move on|also (do|add)|then (do|please))\b": 0.6,
}
# 採用產物（達標，強）：使用者說已套用/合併，或成功寫檔/套 patch
_ADOPT_TEXT = {
    r"已(套用|採用|合併|merge|貼上|用了)|直接用|收下|merged|applied|committed": 1.0,
}
_ADOPT_TOOLS = ("apply_patch", "write", "commit", "merge")


def _match_any(patterns: dict[str, float], text: str) -> list[tuple[str, float]]:
    """回傳 [(命中的片語, 權重)]。"""
    hits: list[tuple[str, float]] = []
    for pat, weight in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            hits.append((m.group(0), weight))
    return hits


def _user_turns(turns: list[dict[str, Any]]) -> list[int]:
    """回傳「看起來是使用者輸入」的 turn index（有 prompt_text 的視為含 user 輸入）。"""
    return [i for i, t in enumerate(turns) if str(t.get("prompt_text") or "").strip()]


def _reformulation_ratio(a: str, b: str) -> float:
    """兩段 user prompt 的文字相似度（0..1），difflib，不需 LLM。"""
    a, b = a.strip(), b.strip()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


_REFORMULATION_THRESHOLD = 0.7


def detect_completion(session: dict[str, Any]) -> dict[str, Any]:
    """從使用者後續行為推斷達標。回 {completion, confidence, signals, verdict}。

    彙總各訊號的帶號權重 → raw ∈ [-1,1] → completion=(raw+1)/2；
    confidence = 命中訊號強度總和（正規化到 0..1）。無訊號 → confidence≈0（交由 fallback）。
    """
    turns = session.get("turns") or []
    signals: list[dict[str, Any]] = []

    def add(stype: str, direction: int, weight: float, evidence: str) -> None:
        signals.append({"type": stype, "direction": direction, "weight": round(weight, 3), "evidence": evidence[:80]})

    user_idx = _user_turns(turns)

    # 逐個「後續 user turn」找訊號（第 2 個含以後的 user 輸入才算「回覆」）
    for k, idx in enumerate(user_idx):
        text = str(turns[idx].get("prompt_text") or "")
        is_followup = k >= 1  # 第一個 user turn 是原始任務，不算回饋
        if is_followup:
            for phrase, w in _match_any(_NEGATIVE, text):
                add("negative", -1, w, phrase)
            for phrase, w in _match_any(_CODING_RETRY, text):
                add("coding_retry", -1, w, phrase)
            for phrase, w in _match_any(_POSITIVE, text):
                add("positive", +1, w, phrase)
            for phrase, w in _match_any(_CONTINUE_NEXT, text):
                add("continue_next", +1, w, phrase)
            for phrase, w in _match_any(_ADOPT_TEXT, text):
                add("adopt", +1, w, phrase)
            # 重述：與「前一個 user turn」高度重疊
            prev_text = str(turns[user_idx[k - 1]].get("prompt_text") or "")
            ratio = _reformulation_ratio(prev_text, text)
            if ratio >= _REFORMULATION_THRESHOLD:
                add("reformulation", -1, 0.8 * ratio, f"similarity={ratio:.2f}")

    # 採用產物：任何 turn 有成功的採用類工具呼叫
    for t in turns:
        for tc in t.get("tool_calls") or []:
            name = str((tc.get("function") or {}).get("name") or "").lower()
            if any(a in name for a in _ADOPT_TOOLS):
                # 該工具是否成功（無對應 error result）
                ok = not any(
                    r.get("has_error") for r in t.get("tool_results") or []
                    if str(r.get("tool_name") or "").lower() == name
                )
                if ok:
                    add("adopt_tool", +1, 0.7, name)
                    break

    # 會話自然結束（弱正向）：最後一個 turn 是 assistant 回覆、其後無 user 追問、且無工具錯誤
    if turns:
        last_user = user_idx[-1] if user_idx else -1
        ended_after_assistant = last_user < len(turns) - 1 or bool(str(turns[-1].get("response_text") or "").strip())
        had_error = any(r.get("has_error") for t in turns for r in (t.get("tool_results") or []))
        # 只有在「有過至少一次 assistant 回覆、且沒有任何負向訊號」時才給
        has_negative = any(s["direction"] < 0 for s in signals)
        if len(user_idx) <= 1 and ended_after_assistant and not had_error and not has_negative:
            add("session_end", +1, 0.25, "no follow-up, no error")

    # ---- 彙總 ---- #
    if not signals:
        return {"completion": 0.5, "confidence": 0.0, "signals": [], "verdict": "unknown"}

    pos = sum(s["weight"] for s in signals if s["direction"] > 0)
    neg = sum(s["weight"] for s in signals if s["direction"] < 0)
    total = pos + neg
    raw = (pos - neg) / total if total else 0.0          # ∈ [-1, 1]
    completion = round((raw + 1) / 2, 3)                  # ∈ [0, 1]
    # 信心：訊號總強度越高越有信心（用 tanh 飽和到 0..1）
    confidence = round(_saturate(total), 3)
    verdict = "completed" if completion >= 0.5 else "not_completed"
    return {"completion": completion, "confidence": confidence, "signals": signals, "verdict": verdict}


def _saturate(x: float) -> float:
    """把非負的訊號強度總和壓到 0..1：1 個強訊號(權重~1) → ~0.66，2 個 → ~0.85。"""
    import math

    return math.tanh(x)
