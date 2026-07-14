"""版本 B 轉接：把本專案 logs/*.json 轉成 SkillClaw evolve_server 的 session dict，
並可實際驅動 SkillClaw 原生 pipeline（summarize → judge → aggregate → evolve → verify），
產出「版本 B 精煉後的 skill」，供與版本 A 對照。

SkillClaw session dict 需要的關鍵欄位（見 evolve_server/pipeline/summarizer.py）：
  turns[]: prompt_text / response_text / tool_calls / tool_results /
           read_skills(list of {skill_name}) / prm_score
  可選：aggregate、benchmark、task_id

前提：SkillClaw 以 git submodule 置於 third_party/skillclaw/
  （clone 時記得 `git submodule update --init`）。

用法（僅轉檔，不需 API key）：
  python third_party/adapt_to_skillclaw.py --out sessions.json

用法（僅跑 summarize + aggregate，需 OPENAI_API_KEY）：
  python third_party/adapt_to_skillclaw.py --run-summarize

用法（★完整精煉：summarize+judge+aggregate+evolve+verify，需 OPENAI_API_KEY）：
  python third_party/adapt_to_skillclaw.py --refine          # 需有效 key
  python third_party/adapt_to_skillclaw.py --refine --mock   # 離線模擬
  → 產出 output/skillclaw_result/{result.json, coding-debug.skillclaw.SKILL.md}
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Optional

HERE = os.path.dirname(os.path.abspath(__file__))                 # third_party/
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))          # 專案根目錄
SKILLCLAW_DIR = os.path.join(HERE, "skillclaw")                   # submodule 路徑


def to_skillclaw_session(rec: dict[str, Any], *, for_judge: bool = False) -> dict[str, Any]:
    """本專案實驗紀錄 → SkillClaw session dict。

    for_judge=False（預設）：把 pytest pass_rate 塞進 ``benchmark.overall_score``，
      讓 SkillClaw 直接採信硬指標（此時 session_judge 會跳過該 session）。
    for_judge=True：不塞 benchmark，改把 pass_rate 存進 ``_pass_rate``（僅供報告顯示），
      讓 SkillClaw session_judge 真的執行，取得四維 judge 分數供與版本 A 對照。
    """
    skill_name = rec.get("skill_name") or ""
    turns_in = rec.get("turns") or []
    turns_out = []
    for t in turns_in:
        turn = {
            "prompt_text": t.get("prompt_text", ""),
            "response_text": t.get("response_text", ""),
            "tool_calls": t.get("tool_calls") or [],
            "tool_results": t.get("tool_results") or [],
            "read_skills": t.get("read_skills") or ([{"skill_name": skill_name}] if skill_name else []),
        }
        # 把本專案綜合分數映成 SkillClaw 的 prm_score（0..1）
        if not for_judge and rec.get("_score") is not None:
            turn["prm_score"] = rec["_score"]
        turns_out.append(turn)

    session: dict[str, Any] = {
        "session_id": rec.get("session_id", ""),
        "task_id": rec.get("task_id", ""),
        "variant_label": rec.get("variant_label", ""),
        "turns": turns_out,
    }
    test = rec.get("test") or {}
    pass_rate = test.get("pass_rate", 0.0) if test else None
    if for_judge:
        # 不塞 benchmark（否則 judge 會 skip）；pass_rate 另存供報告顯示
        if pass_rate is not None:
            session["_pass_rate"] = pass_rate
    elif test:
        session["benchmark"] = {"overall_score": pass_rate}
    return session


def load_and_convert(logs_dir: str, *, for_judge: bool = False) -> list[dict[str, Any]]:
    sessions = []
    for path in sorted(glob.glob(os.path.join(logs_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for rec in (data if isinstance(data, list) else [data]):
            if isinstance(rec, dict):
                sessions.append(to_skillclaw_session(rec, for_judge=for_judge))
    return sessions


class MockAsyncLLM:
    """離線 Mock，介面同 SkillClaw AsyncLLMClient（async chat(messages, **kw)）。

    依 system prompt 特徵判斷 SkillClaw 目前在哪個階段，回傳形狀正確的假輸出，
    讓 SkillClaw 原生 summarizer/session_judge/execution/skill_verifier 能真的跑完。
    分數依 session trajectory 內的 ``strength=`` 訊號分化（v_a>v_b>v_c）。
    這不是真精煉，只用於離線對照 demo；有有效 OpenAI-compatible key 時請拿掉 --mock。
    """

    def __init__(self, model: str = "mock") -> None:
        self.model = model

    async def chat(self, messages, **kwargs) -> str:  # noqa: ANN001
        import re

        system = ""
        user = ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
            elif m.get("role") == "user":
                user = m.get("content", "")
        s = system.lower()

        # session_judge：四維分數（依 strength 分化）
        if "session-level evaluator" in s or "task_completion" in s:
            m = re.search(r"strength=([0-9.]+)", user)
            base = float(m.group(1)) if m else 0.7
            base = max(0.0, min(1.0, base))
            tc, rq, ef, tu = base, base, min(1.0, base + 0.05), base
            overall = round(tc * 0.55 + rq * 0.30 + ef * 0.05 + tu * 0.10, 3)
            return json.dumps({
                "task_completion": tc, "response_quality": rq, "efficiency": ef,
                "tool_usage": tu, "overall_score": overall,
                "rationale": "[MOCK-B] 依 trajectory strength 訊號推估。",
            })

        # skill_verifier：發布閘
        if "final publication gate" in s or "safe_to_publish" in s:
            return json.dumps({
                "decision": "accept", "score": 0.84,
                "reason": "[MOCK-B] 候選有證據支撐、保留 baseline 具體資訊。",
                "checks": {"grounded_in_evidence": 0.85, "preserves_existing_value": 0.85,
                           "specificity_and_reusability": 0.82, "safe_to_publish": 0.84},
            })

        # execution evolve：improve_skill（合併 baseline + 勝出做法）
        if "skill evolution system" in s or "improve_skill" in s:
            cur = ""
            idx = user.find("Content:")
            if idx != -1:
                mm = re.search(r"```\s*\n?(.*?)```", user[idx:], re.DOTALL)
                if mm:
                    cur = mm.group(1).strip()
            merged = (cur or "When tests fail, look at the error and fix the code.").strip()
            merged += (
                "\n\n## 精煉補充（[MOCK-B] SkillClaw 由勝出變體證據萃取）\n"
                "- 先重現失敗測試以確認可重現，再定位最小修改點。\n"
                "- 把每個測試 case 當規格逐條對照，補齊缺漏分支（空輸入 / 邊界 / 需忽略的條件）。\n"
                "- 修完先跑相關測試快速回饋，全綠後再跑完整套件。\n"
            )
            return json.dumps({
                "action": "improve_skill",
                "rationale": "[MOCK-B] 勝出變體（v_a/v_b）共通做法：重現優先、以測試為規格、最小修改、分段驗證。",
                "skill": {
                    "name": "coding-debug",
                    "description": "Use for debugging failing unit tests in a Python project. Reproduce first, read tests as spec, make the smallest fix.",
                    "content": merged, "category": "coding",
                },
            })

        # create_skill from no-skill bucket
        if "no existing skill was referenced" in s:
            return json.dumps({"action": "skip", "rationale": "[MOCK-B] 無足夠共通 pattern。"})

        # summarizer（預設純文字）
        vm = re.search(r"variant[=\s\"]*([a-z_]+)", user)
        variant = vm.group(1) if vm else "?"
        return (
            f"[MOCK-B summary | variant={variant}] 代理人讀取 skill 後嘗試修復失敗測試："
            "先重現錯誤、逐條對照規格、最小修改，再跑測試驗證；skill 指引越具體，完成度越高。"
        )


def _load_baseline_skill() -> dict[str, Any]:
    """讀 baseline SKILL.md → SkillClaw skill dict（用其原生 parse_skill_content）。"""
    from evolve_server.core.utils import parse_skill_content

    path = os.path.join(PROJECT_ROOT, "skills", "coding-debug", "baseline", "SKILL.md")
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    return parse_skill_content("coding-debug", raw)


async def _run_refine(sessions: list[dict[str, Any]], model: str, *, mock: bool = False) -> dict[str, Any]:
    """跑 SkillClaw 原生 pipeline，回傳結構化結果。

    mock=True 時注入離線 MockAsyncLLM（介面相容），仍走 SkillClaw 原生階段。
    """
    from evolve_server.core.constants import NO_SKILL_KEY, DecisionAction
    from evolve_server.core.utils import build_skill_md
    from evolve_server.pipeline.aggregation import aggregate_sessions_by_skill
    from evolve_server.pipeline.execution import evolve_skill_from_sessions
    from evolve_server.pipeline.session_judge import judge_sessions_parallel
    from evolve_server.pipeline.skill_verifier import verify_skill_candidate
    from evolve_server.pipeline.summarizer import summarize_sessions_parallel

    if mock:
        llm = MockAsyncLLM(model="mock")
    else:
        from evolve_server.core.llm_client import AsyncLLMClient

        llm = AsyncLLMClient(model=model)
    baseline = _load_baseline_skill()

    result: dict[str, Any] = {
        "model": "mock" if mock else model,
        "num_sessions": len(sessions),
        "baseline": {
            "name": baseline.get("name"),
            "description": baseline.get("description"),
            "content": baseline.get("content"),
        },
        "action": None,
        "rationale": "",
        "accepted": False,
        "verify": None,
        "refined": None,
        "judge_scores": [],
        "error": None,
    }

    try:
        # 1. summarize
        await summarize_sessions_parallel(llm, sessions)
        # 2. judge（session dict 無 benchmark → 真的執行）
        await judge_sessions_parallel(llm, sessions)
        for s in sessions:
            js = s.get("_judge_scores") or {}
            if js:
                result["judge_scores"].append(
                    {
                        "session_id": s.get("session_id"),
                        "variant_label": s.get("variant_label"),
                        "pass_rate": s.get("_pass_rate"),
                        "overall_score": js.get("overall_score"),
                        "task_completion": js.get("task_completion"),
                        "response_quality": js.get("response_quality"),
                        "efficiency": js.get("efficiency"),
                        "tool_usage": js.get("tool_usage"),
                    }
                )
        # 3. aggregate
        groups = aggregate_sessions_by_skill(sessions)
        result["groups"] = {k: len(v) for k, v in groups.items()}

        # 4. evolve：合併所有非 no-skill 群組的 session 當證據（去重）
        evidence: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key, grp in groups.items():
            if key == NO_SKILL_KEY:
                continue
            for s in grp:
                sid = s.get("session_id", "")
                if sid not in seen:
                    seen.add(sid)
                    evidence.append(s)
        existing_names = [k for k in groups.keys() if k != NO_SKILL_KEY]

        evolve_result = await evolve_skill_from_sessions(
            llm, "coding-debug", evidence, baseline, existing_names
        )
        if not evolve_result:
            result["error"] = "evolve_skill_from_sessions returned None"
            return result

        result["action"] = evolve_result.get("action")
        result["rationale"] = evolve_result.get("rationale", "")

        if evolve_result.get("action") == DecisionAction.SKIP:
            return result

        candidate = evolve_result.get("skill") or {}
        result["refined"] = {
            "name": candidate.get("name"),
            "description": candidate.get("description"),
            "content": candidate.get("content"),
        }

        # 5. verify
        verdict = await verify_skill_candidate(
            llm, candidate, evidence, evolve_result["action"],
            current_skill=baseline, min_score=0.75,
        )
        result["verify"] = verdict
        result["accepted"] = bool(verdict.get("accepted"))
        result["_candidate_md"] = build_skill_md(candidate)
    except Exception as exc:  # noqa: BLE001
        import traceback

        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()[-2000:]

    return result


def _write_results(result: dict[str, Any], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    candidate_md = result.pop("_candidate_md", None)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    if candidate_md and result.get("accepted"):
        with open(os.path.join(out_dir, "coding-debug.skillclaw.SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write(candidate_md)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="版本 B：本專案 logs → SkillClaw session / 精煉")
    parser.add_argument("--logs", default=os.path.join(PROJECT_ROOT, "logs"))
    parser.add_argument("--out", default=os.path.join(HERE, "sessions_for_skillclaw.json"))
    parser.add_argument("--out-dir", default=os.path.join(PROJECT_ROOT, "output", "skillclaw_result"))
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--run-summarize", action="store_true",
                        help="只跑 summarize + aggregate（需 OPENAI_API_KEY）")
    parser.add_argument("--refine", action="store_true",
                        help="★完整精煉：summarize+judge+aggregate+evolve+verify（需 OPENAI_API_KEY）")
    parser.add_argument("--mock", action="store_true",
                        help="離線模擬：--refine 時注入 MockAsyncLLM，不呼叫 OpenAI（無金鑰時對照用）")
    args = parser.parse_args(argv)

    sys.path.insert(0, SKILLCLAW_DIR)
    logs_dir = os.path.abspath(args.logs)

    # 轉檔（僅轉檔模式用 benchmark 版；refine 用 for_judge 版）
    sessions = load_and_convert(logs_dir, for_judge=False)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(sessions, fh, ensure_ascii=False, indent=2)
    print(f"converted {len(sessions)} sessions → {args.out}")

    if args.refine:
        import asyncio

        judge_sessions = load_and_convert(logs_dir, for_judge=True)
        tag = "mock" if args.mock else args.model
        print(f"[refine] running SkillClaw pipeline on {len(judge_sessions)} sessions (llm={tag}) ...")
        result = asyncio.run(_run_refine(judge_sessions, args.model, mock=args.mock))
        _write_results(result, args.out_dir)
        print(f"[refine] action={result.get('action')} accepted={result.get('accepted')} "
              f"verify_score={(result.get('verify') or {}).get('score')}")
        if result.get("error"):
            print(f"[refine] ERROR: {result['error']}")
        print(f"[refine] wrote → {os.path.join(args.out_dir, 'result.json')}")
        return 0

    if args.run_summarize:
        import asyncio

        from evolve_server.core.llm_client import AsyncLLMClient
        from evolve_server.pipeline.aggregation import aggregate_sessions_by_skill
        from evolve_server.pipeline.summarizer import summarize_sessions_parallel

        llm = AsyncLLMClient(model=args.model)

        async def _run():
            await summarize_sessions_parallel(llm, sessions)
            groups = aggregate_sessions_by_skill(sessions)
            print("SkillClaw groups:", {k: len(v) for k, v in groups.items()})

        asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
