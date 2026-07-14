"""通用（場景無關）評分指標。

從 session 既有欄位（turns / tool_calls / tool_results / response_text /
runner_meta 計時）算出「效率類」原始指標，並以「同一 (goal, task) 的變體群（cohort）」
做 min-max 反向正規化 → 0..1 的效率分數（越省資源越高）。

cohort 明確按 ``(skill_name/goal, task_id)`` 分組：效率只跟「做同一件事（同 goal、
同 task）的其他變體」比較，即使 logs/ 混了多個 goal 或多個 task 也不會互相污染。

這些指標任何任務場景都能算，不依賴 pytest。效率分「越少越好」，因此**單獨使用會
獎勵擺爛**；務必與有效性訊號（completion judge）相乘使用（見 evaluator）。
"""

from __future__ import annotations

from typing import Any, Optional

# 效率各項在 efficiency_score 的權重（可調）。加總為 1.0。
EFFICIENCY_WEIGHTS = {
    "num_turns": 0.35,
    "elapsed_sec": 0.25,
    "num_tool_calls": 0.15,
    "tool_error_rate": 0.15,
    "response_chars": 0.10,
}

# 這些指標「越小越好」（反向正規化）。tool_error_rate 已是 0..1，直接 1-x。
_LOWER_IS_BETTER = ("num_turns", "elapsed_sec", "num_tool_calls", "response_chars")


def compute_raw_metrics(session: dict[str, Any]) -> dict[str, Any]:
    """從 session 算原始效率指標（任何場景通用）。

    回傳：num_turns / num_tool_calls / tool_error_rate / response_chars / elapsed_sec。
    elapsed_sec 若 runner_meta 無計時 → None（正規化時該項不計入）。
    """
    turns = session.get("turns") or []
    num_turns = len(turns)
    num_tool_calls = 0
    tool_results_total = 0
    tool_errors = 0
    response_chars = 0

    for t in turns:
        if not isinstance(t, dict):
            continue
        calls = t.get("tool_calls") or []
        num_tool_calls += len(calls)
        for r in t.get("tool_results") or []:
            tool_results_total += 1
            if isinstance(r, dict) and r.get("has_error"):
                tool_errors += 1
        response_chars += len(str(t.get("response_text") or ""))

    tool_error_rate = round(tool_errors / tool_results_total, 3) if tool_results_total else 0.0

    return {
        "num_turns": num_turns,
        "num_tool_calls": num_tool_calls,
        "tool_error_rate": tool_error_rate,
        "response_chars": response_chars,
        "elapsed_sec": _elapsed_of(session),
    }


def _elapsed_of(session: dict[str, Any]) -> Optional[float]:
    meta = session.get("runner_meta") or {}
    start = meta.get("started_at")
    end = meta.get("ended_at")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return round(float(end - start), 3)
    return None


def _minmax_reverse(value: float, lo: float, hi: float) -> float:
    """越小越好 → 最小值得 1.0、最大值得 0.0。lo==hi（無區別）→ 1.0。"""
    if hi <= lo:
        return 1.0
    return round((hi - value) / (hi - lo), 3)


def normalize_efficiency(
    raw: dict[str, Any],
    cohort: list[dict[str, Any]],
) -> dict[str, Any]:
    """把一筆 raw 指標，相對於 cohort（同一 (goal, task) 的變體 raw 指標）正規化成 0..1。

    - 「越小越好」項用 cohort 的 min/max 反向正規化。
    - tool_error_rate 直接 1 - rate（本身已 0..1，與 cohort 無關）。
    - 某項在 cohort 全部缺值（如 elapsed 於 mock）→ 該項不計入，權重按剩餘項重分配。
    回傳：{per_metric: {...0..1}, efficiency_score, used_metrics, skipped_metrics}。
    """
    per_metric: dict[str, float] = {}
    used_weights: dict[str, float] = {}
    skipped: list[str] = []

    for key in _LOWER_IS_BETTER:
        vals = [c.get(key) for c in cohort if isinstance(c.get(key), (int, float))]
        v = raw.get(key)
        if not isinstance(v, (int, float)) or not vals:
            skipped.append(key)
            continue
        per_metric[key] = _minmax_reverse(float(v), min(vals), max(vals))
        used_weights[key] = EFFICIENCY_WEIGHTS[key]

    # tool_error_rate：不需 cohort，直接反向
    er = raw.get("tool_error_rate")
    if isinstance(er, (int, float)):
        per_metric["tool_error_rate"] = round(1.0 - max(0.0, min(1.0, float(er))), 3)
        used_weights["tool_error_rate"] = EFFICIENCY_WEIGHTS["tool_error_rate"]
    else:
        skipped.append("tool_error_rate")

    if not used_weights:
        efficiency_score = 1.0  # 無任何可比指標 → 中性
    else:
        wsum = sum(used_weights.values())
        efficiency_score = round(
            sum(per_metric[k] * (used_weights[k] / wsum) for k in used_weights), 3
        )

    return {
        "per_metric": per_metric,
        "efficiency_score": efficiency_score,
        "used_metrics": sorted(used_weights.keys()),
        "skipped_metrics": sorted(set(skipped)),
    }


def _cohort_key(session: dict[str, Any]) -> tuple[str, str]:
    """cohort 分組鍵 = (goal, task)。goal 用 skill_name（同一 skill 的所有變體相同）。"""
    return (str(session.get("skill_name") or ""), str(session.get("task_id") or ""))


def attach_cohort_efficiency(sessions: list[dict[str, Any]]) -> None:
    """就地為每個 session 補 _metrics（raw + efficiency）。

    cohort **明確按 (goal, task) 分組**：效率只跟「同 goal、同 task 的其他變體」比較，
    即使傳入的 sessions 混了多個 goal / task 也不會互相污染。單一元素桶（該 goal+task
    只有一個變體）→ min==max → efficiency 中性 1.0。
    """
    # 先分桶
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in sessions:
        buckets.setdefault(_cohort_key(s), []).append(s)

    # 每桶各自算 raw 並在桶內正規化
    for key, bucket in buckets.items():
        raws = [compute_raw_metrics(s) for s in bucket]
        cohort_str = "::".join(key)
        for s, raw in zip(bucket, raws):
            eff = normalize_efficiency(raw, raws)
            existing = s.get("_metrics") or {}
            existing.update(
                {"raw": raw, **eff, "cohort_key": cohort_str, "cohort_size": len(bucket)}
            )
            s["_metrics"] = existing
