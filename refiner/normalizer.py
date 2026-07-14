"""統一 session 格式 + 來源轉換器。

統一 session schema（版本 A 內部格式）：
{
  "session_id": str,
  "skill_id": str,              # 明確記錄用了哪個 skill 變體（orchestrator 寫入，不靠推斷）
  "skill_name": str,
  "task_id": str,
  "turns": [ {                  # 每個 turn
      "prompt_text": str,
      "response_text": str,
      "tool_calls": [ {"id": str, "function": {"name": str, "arguments": str}} ],
      "tool_results": [ {"tool_call_id": str, "tool_name": str, "has_error": bool,
                          "error_type": str, "content": str, "command": str} ],
      "read_skills": [ {"skill_name": str} ],   # 用於 aggregation 分組
      "prm_score": float | None,
  } ],
  # 由 evaluator / summarizer 補上：
  "test": {"passed": int, "total": int, "pass_rate": float, "all_pass": bool},
  "_score": float,             # 綜合分數（硬+軟）
  "_success": bool,
}

支援兩種來源：
  A. 實驗額外紀錄（runner_codex 產生的 experiment log）—— 已接近統一格式。
  B. Codex 經典 CLI 的 rollout-*.jsonl（Phase 2 log 探勘）。
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Optional

from .skillmd import compute_skill_id, parse_skill_md

_SKILLMD_PATH_RE = re.compile(r"([A-Za-z0-9._/\\-]*?([A-Za-z0-9._-]+)[/\\]SKILL\.md)")

# ------------------------------------------------------------------ #
#  A. 實驗 log → 統一 session                                          #
# ------------------------------------------------------------------ #


def normalize_experiment_record(rec: dict[str, Any]) -> dict[str, Any]:
    """把 runner 產生的一筆實驗紀錄整理成統一 session。

    runner 已明確寫入 skill_id / skill_name / task_id / turns / test，
    這裡只做欄位補齊與 read_skills 標註（讓 aggregation 能依 skill 分組）。
    """
    skill_name = rec.get("skill_name") or rec.get("skill", "")
    skill_id = rec.get("skill_id") or (compute_skill_id(skill_name) if skill_name else "")

    turns = rec.get("turns") or []
    if not turns:
        # 沒有逐 turn 資料時，用 prompt/response 合成單一 turn
        turns = [
            {
                "prompt_text": rec.get("prompt", "") or rec.get("task_prompt", ""),
                "response_text": rec.get("response", "") or rec.get("final_output", ""),
                "tool_calls": rec.get("tool_calls") or [],
                "tool_results": rec.get("tool_results") or [],
            }
        ]

    # 明確標註 read_skills（用於 aggregation：session 用了哪個 skill）
    for t in turns:
        if skill_name and not t.get("read_skills"):
            t["read_skills"] = [{"skill_name": skill_name}]

    # actual_used_skill_ids（對齊 0714「任務執行流程」step 8）：
    # Phase 1 實驗中 runner 明確知道用了哪個變體 → 直接採用其 selected_skill_ids / skill_id。
    actual_ids = rec.get("actual_used_skill_ids") or rec.get("selected_skill_ids")
    if not actual_ids:
        actual_ids = [skill_id] if skill_id else []

    session: dict[str, Any] = {
        "session_id": rec.get("session_id") or f"{task_or(rec)}::{skill_name}",
        "skill_id": skill_id,
        "skill_name": skill_name,
        "variant_label": rec.get("variant_label") or skill_name,
        "task_id": rec.get("task_id", ""),
        "runner_mode": rec.get("runner_mode", ""),
        "actual_used_skill_ids": list(actual_ids),
        "turns": turns,
    }
    if isinstance(rec.get("test"), dict):
        session["test"] = rec["test"]
    if rec.get("_score") is not None:
        session["_score"] = rec["_score"]
    if rec.get("_success") is not None:
        session["_success"] = rec["_success"]
    if isinstance(rec.get("_judge_scores"), dict):
        session["_judge_scores"] = rec["_judge_scores"]
    return session


def task_or(rec: dict[str, Any]) -> str:
    return rec.get("task_id") or "task"


def load_experiment_sessions(logs_dir: str) -> list[dict[str, Any]]:
    """讀 logs_dir 下所有 *.json / *.jsonl 實驗紀錄 → 統一 sessions。"""
    sessions: list[dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(logs_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = data if isinstance(data, list) else [data]
        for rec in records:
            if isinstance(rec, dict):
                sessions.append(normalize_experiment_record(rec))
    for path in sorted(glob.glob(os.path.join(logs_dir, "*.jsonl"))):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if isinstance(rec, dict):
                    sessions.append(normalize_experiment_record(rec))
    return sessions


# ------------------------------------------------------------------ #
#  B. Codex rollout-*.jsonl → 統一 session（Phase 2 log 探勘）         #
# ------------------------------------------------------------------ #


def normalize_codex_rollout(path: str, *, skills_root: Optional[str] = None) -> Optional[dict[str, Any]]:
    """把一份 Codex 經典 CLI rollout-*.jsonl 轉成統一 session。

    rollout 格式：每行一個 JSON，含 ``timestamp`` 與 ``type``
    ∈ {session_meta, response_item}；response_item 內含 message / reasoning /
    function_call / function_call_output / usage。

    注意（文件的三個陷阱）：
      - rollout 沒有穩定的 skill_id 欄位 → 這裡用 heuristic 從對話文字中偵測
        使用者自訂 skill（見 detect_skill_references），非權威。
    """
    records: list[dict[str, Any]] = []
    session_meta: dict[str, Any] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("type") == "session_meta":
                session_meta = rec.get("payload", rec)
            records.append(rec)

    if not records:
        return None

    turns: list[dict[str, Any]] = []
    cur: dict[str, Any] = _new_turn()
    pending_calls: dict[str, dict[str, Any]] = {}

    for rec in records:
        rtype = rec.get("type")
        payload = rec.get("payload", rec)
        if rtype != "response_item":
            continue
        item_type = payload.get("type") or payload.get("role")
        role = payload.get("role")

        if role == "user" or item_type == "user":
            if cur["prompt_text"] or cur["response_text"] or cur["tool_calls"]:
                turns.append(cur)
                cur = _new_turn()
            cur["prompt_text"] = _text_of(payload)
        elif role == "assistant" or item_type in ("message", "assistant"):
            cur["response_text"] += _text_of(payload)
        elif item_type == "function_call":
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            call = {
                "id": call_id,
                "function": {
                    "name": payload.get("name", ""),
                    "arguments": payload.get("arguments", ""),
                },
            }
            cur["tool_calls"].append(call)
            pending_calls[call_id] = call
        elif item_type == "function_call_output":
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            out = payload.get("output", "")
            content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
            cur["tool_results"].append(
                {
                    "tool_call_id": call_id,
                    "tool_name": pending_calls.get(call_id, {}).get("function", {}).get("name", ""),
                    "has_error": "error" in content.lower()[:200],
                    "error_type": "",
                    "content": content[:2000],
                    "command": "",
                }
            )

    if cur["prompt_text"] or cur["response_text"] or cur["tool_calls"]:
        turns.append(cur)

    if skills_root is None:
        # 預設用專案的 skills/（供解析 rollout 內的相對 SKILL.md 路徑）
        skills_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
    skills, actual_ids = extract_used_skill_ids(turns, skills_root=skills_root)
    for t in turns:
        if skills:
            t["read_skills"] = [{"skill_name": s} for s in skills]

    primary_skill = sorted(skills)[0] if skills else ""
    return {
        "session_id": session_meta.get("id") or os.path.basename(path),
        "skill_id": (actual_ids[0] if actual_ids else (compute_skill_id(primary_skill) if primary_skill else "")),
        "skill_name": primary_skill,
        "task_id": "",
        "cwd": session_meta.get("cwd", ""),
        "actual_used_skill_ids": actual_ids,
        "turns": turns,
    }


def _new_turn() -> dict[str, Any]:
    return {
        "prompt_text": "",
        "response_text": "",
        "tool_calls": [],
        "tool_results": [],
        "read_skills": [],
    }


def _text_of(payload: dict[str, Any]) -> str:
    """從 message payload 抽純文字（content 可能是 str 或 list of blocks）。"""
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for blk in content:
            if isinstance(blk, dict):
                parts.append(str(blk.get("text") or blk.get("content") or ""))
            else:
                parts.append(str(blk))
        return "".join(parts)
    return str(payload.get("text") or "")


def detect_skill_references(turns: list[dict[str, Any]], skill_names: Optional[list[str]] = None) -> set[str]:
    """Heuristic：從對話 / 工具讀檔中偵測使用者自訂 skill 的引用。

    對應 Shane 0713 notes step 1-2：從對話中篩出使用者自訂 skill、
    並找出「更新過該 skill」的對話。若給定 skill_names 白名單則只認白名單。
    偵測訊號：讀 / 寫 SKILL.md 路徑、文字提到 skill 名稱。
    """
    names, _paths = _scan_skill_md(turns, skill_names)
    return names


def _scan_skill_md(
    turns: list[dict[str, Any]], skill_names: Optional[list[str]] = None
) -> tuple[set[str], set[str]]:
    """回傳 (skill 名稱集合, 實際被讀取的 SKILL.md 路徑集合)。"""
    found: set[str] = set()
    paths: set[str] = set()
    for t in turns:
        blob_parts = [t.get("prompt_text", ""), t.get("response_text", "")]
        for tc in t.get("tool_calls", []):
            blob_parts.append(json.dumps(tc.get("function", {}), ensure_ascii=False))
        for tr in t.get("tool_results", []):
            blob_parts.append(str(tr.get("path", "")))
        blob = " ".join(blob_parts)

        for m in _SKILLMD_PATH_RE.finditer(blob):
            paths.add(m.group(1))
            found.add(m.group(2))  # 目錄名 = skill 名
        if skill_names:
            for name in skill_names:
                if name and name in blob:
                    found.add(name)
    return found, paths


def extract_used_skill_ids(
    turns: list[dict[str, Any]],
    *,
    skills_root: Optional[str] = None,
    skill_names: Optional[list[str]] = None,
) -> tuple[set[str], list[str]]:
    """從 log 找出實際被讀取的 SKILL.md，開檔取 frontmatter 的 skill_id。

    對齊 0714 文件「任務執行流程」step 5-8：
      找出實際被讀取的 SKILL.md → 取出 skill_id → 記為 actual_used_skill_ids。
    開得了檔 → 讀 frontmatter skill_id；開不了（路徑非絕對或不存在）→ 用 compute_skill_id(名稱) 退回。

    回傳 (skill 名稱集合, 去重後的 skill_id 清單)。
    """
    names, paths = _scan_skill_md(turns, skill_names)
    ids: list[str] = []
    seen: set[str] = set()

    def _add(sid: str) -> None:
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)

    resolved_names: set[str] = set()
    for raw_path in paths:
        candidates = [raw_path]
        if skills_root:
            # 嘗試以 skills_root 解析（rollout 常記相對路徑）
            base = os.path.basename(os.path.dirname(raw_path))
            candidates.append(os.path.join(skills_root, base, "SKILL.md"))
        opened = False
        for cand in candidates:
            if os.path.isfile(cand):
                try:
                    with open(cand, "r", encoding="utf-8") as fh:
                        parsed = parse_skill_md(fh.read())
                    _add(parsed.get("skill_id") or compute_skill_id(parsed.get("name", "")))
                    resolved_names.add(os.path.basename(os.path.dirname(cand)))
                    opened = True
                    break
                except OSError:
                    pass
        if not opened:
            # 開不了檔 → 用目錄名退回
            base = os.path.basename(os.path.dirname(raw_path))
            _add(compute_skill_id(base))

    # 名稱有偵測到但沒對應到路徑者，也用名稱退回產生 id
    for name in names - resolved_names:
        _add(compute_skill_id(name))

    return names, ids


def load_codex_rollouts(sessions_dir: str) -> list[dict[str, Any]]:
    """遞迴讀 ~/.codex/sessions 下所有 rollout-*.jsonl。"""
    sessions: list[dict[str, Any]] = []
    pattern = os.path.join(sessions_dir, "**", "rollout-*.jsonl")
    for path in sorted(glob.glob(pattern, recursive=True)):
        s = normalize_codex_rollout(path)
        if s and s.get("turns"):
            sessions.append(s)
    return sessions
