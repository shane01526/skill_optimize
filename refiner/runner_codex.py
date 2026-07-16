"""Runner：對每個 (skill 變體 × golden task) 實際執行 coding 任務，產生實驗 log。

每個組合都在**獨立 workspace**（複製一份 task 目錄）執行，避免互相污染，
且能各自跑測試得到客觀通過率。

三種執行模式：
  - codex：呼叫經典 Codex CLI ``codex exec`` headless 跑，agent 直接改檔，
    並產生 ~/.codex/sessions/**/rollout-*.jsonl（主線，依使用者選擇）。
  - api  ：直接呼叫 LLM 當 coding agent，從回覆抽出程式碼區塊寫回檔案。
  - mock ：離線模擬——依變體 skill 的「指引強度」決定 agent 是否成功套用
    參考解答（solution.py）。讓沒有 API key 時也能重現「好 skill→高通過率」。

記錄 selected_skill_ids（不靠事後推斷，對應文件 line 80）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Optional

from .skillmd import compute_skill_id, parse_skill_md


def codex_available() -> bool:
    return shutil.which("codex") is not None


def _read_task_prompt(task_dir: str) -> str:
    prompt_path = os.path.join(task_dir, "prompt.md")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as fh:
            return fh.read()
    return "Fix the failing tests in this directory."


def _load_conversation(task_dir: str, variant_label: str):
    """讀 task 的 conversation.json（多輪對話腳本）當 turns。

    格式支援兩種：
      1. {"default": [turns...], "<variant>": [turns...]}  # 可依變體給不同後續回覆
      2. [turns...]                                          # 所有變體共用
    每個 turn 至少含 prompt_text / response_text；缺 tool_calls/results 會補空。
    找不到檔或格式不符 → 回 None（退回原本的單輪執行）。
    """
    path = os.path.join(task_dir, "conversation.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None

    if isinstance(data, dict):
        raw_turns = data.get(variant_label) or data.get("default")
    elif isinstance(data, list):
        raw_turns = data
    else:
        raw_turns = None
    if not isinstance(raw_turns, list) or not raw_turns:
        return None

    turns = []
    for t in raw_turns:
        if not isinstance(t, dict):
            continue
        turns.append(
            {
                "prompt_text": str(t.get("prompt_text") or ""),
                "response_text": str(t.get("response_text") or ""),
                "tool_calls": t.get("tool_calls") or [],
                "tool_results": t.get("tool_results") or [],
            }
        )
    return turns or None


def _read_task_type(task_dir: str) -> str:
    """讀 task.json 的 task_type（標籤優先）；否則以有無 test_*.py 偵測回退。"""
    task_json = os.path.join(task_dir, "task.json")
    if os.path.exists(task_json):
        try:
            with open(task_json, "r", encoding="utf-8") as fh:
                tt = str(json.load(fh).get("task_type") or "").strip().lower()
            if tt in ("coding", "general"):
                return tt
        except (json.JSONDecodeError, OSError):
            pass
    has_tests = any(f.startswith("test_") and f.endswith(".py") for f in os.listdir(task_dir)) if os.path.isdir(task_dir) else False
    return "coding" if has_tests else "general"


def _load_variant(skill_md_path: str) -> dict[str, Any]:
    with open(skill_md_path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    return parse_skill_md(raw, fallback_name=os.path.basename(os.path.dirname(skill_md_path)))


def _compose_instruction(task_prompt: str, variant: dict[str, Any]) -> str:
    return (
        "You are a coding agent. Use the following SKILL to guide your work.\n\n"
        f"===== SKILL: {variant.get('name')} =====\n"
        f"{variant.get('content', '')}\n"
        "===== END SKILL =====\n\n"
        f"## Task\n{task_prompt}\n\n"
        "Edit the code in the current directory to make the tests pass. "
        "Return the full corrected content of the file you changed inside a "
        "```python code block, and explain the fix briefly."
    )


def prepare_workspace(task_dir: str, workspaces_root: str, task_id: str, variant_name: str) -> str:
    """複製 task 目錄成獨立 workspace，回傳其路徑。"""
    ws = os.path.join(workspaces_root, f"{task_id}__{variant_name}")
    if os.path.exists(ws):
        shutil.rmtree(ws)
    shutil.copytree(task_dir, ws)
    return ws


def run_variant_on_task(
    *,
    skill_md_path: str,
    task_dir: str,
    task_id: str,
    workspaces_root: str,
    mode: str = "auto",
    llm=None,
    timeout: int = 600,
) -> tuple[dict[str, Any], str]:
    """執行一個 (變體 × task)，回傳 (實驗紀錄, workspace 路徑)。"""
    variant = _load_variant(skill_md_path)
    skill_name = variant.get("name", "")
    variant_label = os.path.basename(os.path.dirname(skill_md_path))
    skill_id = variant.get("skill_id") or compute_skill_id(skill_name)
    task_prompt = _read_task_prompt(task_dir)
    instruction = _compose_instruction(task_prompt, variant)

    ws = prepare_workspace(task_dir, workspaces_root, task_id, variant_label)

    chosen = mode
    if mode == "auto":
        chosen = "codex" if codex_available() else "mock"

    # 多輪對話任務：若 task 附 conversation.json，直接用預寫腳本當 turns（可重現、供
    # completion detector 判定），不再合成單輪。codex 模式仍實跑（腳本僅供離線 demo）。
    convo_turns = None
    if chosen in ("mock", "api"):
        convo_turns = _load_conversation(task_dir, variant_label)

    # 通用計時：三種模式都記 started/ended（供 generic_metrics 算 elapsed_sec）
    started = time.time()
    if convo_turns is not None:
        turns, meta = convo_turns, {"source": "conversation.json", "variant": variant_label}
    elif chosen == "codex":
        turns, meta = _run_codex(instruction, ws, timeout)
    elif chosen == "api":
        turns, meta = _run_llm_agent(instruction, ws, llm)
    else:  # mock
        turns, meta = _run_mock(instruction, ws, variant, meta_label=variant_label)
    ended = time.time()
    meta.setdefault("started_at", started)
    meta.setdefault("ended_at", ended)

    rec = {
        "session_id": f"{task_id}::{variant_label}",
        "skill_id": skill_id,
        "skill_name": skill_name,
        "variant_label": variant_label,
        "task_id": task_id,
        "task_type": _read_task_type(task_dir),
        "variant_path": skill_md_path,
        "selected_skill_ids": [skill_id],
        "runner_mode": chosen,
        "runner_meta": meta,
        "workspace": ws,
        "turns": turns,
    }
    return rec, ws


# ------------------------------------------------------------------ #
#  codex 模式                                                          #
# ------------------------------------------------------------------ #


def _run_codex(instruction: str, ws: str, timeout: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.time()
    try:
        proc = subprocess.run(
            ["codex", "exec", "--skip-git-repo-check", instruction],
            capture_output=True, text=True, timeout=timeout, cwd=ws,
        )
        stdout, stderr, rc = proc.stdout, proc.stderr, proc.returncode
    except Exception as exc:  # noqa: BLE001
        stdout, stderr, rc = "", str(exc), -1
    meta = {"returncode": rc, "stderr_tail": (stderr or "")[-800:], "started_at": started, "ended_at": time.time()}
    turns = [{"prompt_text": instruction, "response_text": stdout or "", "tool_calls": [], "tool_results": []}]
    return turns, meta


# ------------------------------------------------------------------ #
#  api 模式                                                            #
# ------------------------------------------------------------------ #


def _run_llm_agent(instruction: str, ws: str, llm) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from .llm import LLMClient

    client = llm or LLMClient()
    system = "You are a coding agent that fixes failing tests by editing files. Always return the full corrected file in a ```python block."
    try:
        response = client.chat(system, instruction, temperature=0.2, max_tokens=4096)
    except Exception as exc:  # noqa: BLE001
        response = f"[runner error] {exc}"
    applied = _apply_python_block(response, ws)
    turns = [{"prompt_text": instruction, "response_text": response, "tool_calls": [], "tool_results": []}]
    return turns, {"provider": getattr(client, "provider", "?"), "model": getattr(client, "model", "?"), "applied_file": applied}


def _apply_python_block(response: str, ws: str) -> Optional[str]:
    """從 LLM 回覆抽第一個 python code block，寫回 workspace 內非 test 的 .py。"""
    m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if not m:
        return None
    code = m.group(1)
    targets = [f for f in os.listdir(ws) if f.endswith(".py") and not f.startswith("test_") and f != "solution.py"]
    if not targets:
        return None
    target = os.path.join(ws, sorted(targets)[0])
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(code)
    return target


# ------------------------------------------------------------------ #
#  mock 模式（離線模擬）                                               #
# ------------------------------------------------------------------ #


def _variant_strength(variant: dict[str, Any]) -> float:
    """依 skill 內容估算「指引強度」0..1：具體步驟越多越強。"""
    content = variant.get("content", "")
    desc = variant.get("description", "")
    signals = [
        "重現" in content or "reproduce" in content.lower(),
        "最小" in content or "smallest" in content.lower(),
        "規格" in content or "spec" in content.lower(),
        "邊界" in content or "邊界值" in content or "boundary" in content.lower(),
        "分隔符" in content or "空字串" in content or "忽略" in content,
        len(content) > 200,
        len(desc) > 60,
    ]
    return round(sum(1 for s in signals if s) / len(signals), 3)


def _run_mock(instruction: str, ws: str, variant: dict[str, Any], meta_label: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """依變體強度決定是否套用參考解答，模擬 agent 成敗。"""
    strength = _variant_strength(variant)
    applied = None
    if strength >= 0.6:  # 指引夠強 → agent 成功修好
        applied = _apply_solution(ws)
    elif strength >= 0.4:  # 中等 → 只修部分（示範 partial pass）
        applied = _apply_solution(ws, partial=True)
    # 太弱 → 不改，維持原 bug（全紅）

    response = (
        f"[MOCK agent | variant={meta_label} | strength={strength}] "
        + ("依 skill 指引重現失敗、逐條對照規格、最小修改後套用修正。" if applied else "指引過於籠統，未能定位修正點。")
    )
    turns = [{
        "prompt_text": instruction,
        "response_text": response,
        "tool_calls": [{"id": "c1", "function": {"name": "run_tests", "arguments": "pytest -q"}}],
        "tool_results": [{"tool_call_id": "c1", "tool_name": "run_tests", "has_error": not applied, "content": "applied fix" if applied else "still failing"}],
    }]
    return turns, {"strength": strength, "applied_file": applied}


def _apply_solution(ws: str, partial: bool = False) -> Optional[str]:
    """把 solution.py 裡的 _SOLUTION 套到 workspace 的目標檔。partial=套 _PARTIAL_SOLUTION（只修一半）。

    每個 golden task 的 solution.py 都定義 ``_SOLUTION``（完整解）與可選的
    ``_PARTIAL_SOLUTION``（中等強度 skill 的部分解）。task 無關，故不寫死任何檔名。
    """
    sol_path = os.path.join(ws, "solution.py")
    if not os.path.exists(sol_path):
        return None
    ns: dict[str, Any] = {}
    with open(sol_path, "r", encoding="utf-8") as fh:
        exec(fh.read(), ns)  # noqa: S102 - 受控的本地 golden 檔
    solution = ns.get("_PARTIAL_SOLUTION") if partial else ns.get("_SOLUTION")
    if not solution and partial:
        solution = ns.get("_SOLUTION")  # 無 partial 定義時退回完整解
    if not solution:
        return None
    targets = [f for f in os.listdir(ws) if f.endswith(".py") and not f.startswith("test_") and f != "solution.py"]
    if not targets:
        return None
    target = os.path.join(ws, sorted(targets)[0])
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(solution)
    return target


def save_experiment_log(record: dict[str, Any], logs_dir: str) -> str:
    os.makedirs(logs_dir, exist_ok=True)
    safe = record["session_id"].replace("/", "_").replace("::", "__")
    path = os.path.join(logs_dir, f"{safe}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    return path
