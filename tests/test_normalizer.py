"""normalizer + skillmd：統一 session schema、rollout 解析、skill 偵測、SKILL.md 往返。"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refiner.normalizer import (
    detect_skill_references,
    normalize_codex_rollout,
    normalize_experiment_record,
)
from refiner.skillmd import build_skill_md, compute_skill_id, parse_skill_md


def test_normalize_experiment_record_shape():
    rec = {
        "session_id": "task_001::v_a",
        "skill_name": "coding-debug",
        "task_id": "task_001",
        "variant_label": "v_a",
        "turns": [{"prompt_text": "fix", "response_text": "done", "tool_calls": [], "tool_results": []}],
        "test": {"passed": 5, "total": 5, "pass_rate": 1.0, "all_pass": True},
        "_score": 0.9,
    }
    s = normalize_experiment_record(rec)
    assert s["skill_id"] == compute_skill_id("coding-debug")
    assert s["variant_label"] == "v_a"
    # read_skills 被標註 → aggregation 可分組
    assert s["turns"][0]["read_skills"] == [{"skill_name": "coding-debug"}]
    assert s["test"]["all_pass"] is True


def test_skillmd_roundtrip_preserves_skill_id_and_version():
    md = build_skill_md({"name": "coding-debug", "version": "1.0.0",
                         "description": "Use for debugging.", "content": "# Body\nsteps"})
    parsed = parse_skill_md(md)
    assert parsed["name"] == "coding-debug"
    assert parsed["skill_id"] == compute_skill_id("coding-debug")
    assert parsed["version"] == "1.0.0"
    assert "Body" in parsed["content"]


def test_skillmd_quotes_special_description():
    md = build_skill_md({"name": "x", "description": "Use: when foo, bar", "content": "b"})
    assert 'description: "' in md  # 含冒號/逗號 → 需引號
    assert parse_skill_md(md)["description"] == "Use: when foo, bar"


def test_detect_skill_references_from_paths():
    turns = [{
        "prompt_text": "read the skill",
        "response_text": "",
        "tool_calls": [{"function": {"name": "read", "arguments": '{"path": "skills/coding-debug/SKILL.md"}'}}],
        "tool_results": [{"path": "skills/coding-debug/SKILL.md"}],
    }]
    found = detect_skill_references(turns)
    assert "coding-debug" in found


def test_normalize_codex_rollout(tmp_path):
    # 造一個 minimal rollout-*.jsonl
    lines = [
        {"timestamp": "t0", "type": "session_meta", "payload": {"id": "sess1", "cwd": "/proj"}},
        {"timestamp": "t1", "type": "response_item", "payload": {"role": "user", "content": "read skills/coding-debug/SKILL.md and fix"}},
        {"timestamp": "t2", "type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "read", "arguments": '{"path":"skills/coding-debug/SKILL.md"}'}},
        {"timestamp": "t3", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "ok"}},
        {"timestamp": "t4", "type": "response_item", "payload": {"role": "assistant", "content": "fixed it"}},
    ]
    p = tmp_path / "rollout-2026.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    s = normalize_codex_rollout(str(p))
    assert s is not None
    assert s["session_id"] == "sess1"
    assert s["skill_name"] == "coding-debug"  # 從路徑偵測
    assert any(t["tool_calls"] for t in s["turns"])


def test_extract_used_skill_ids_reads_frontmatter():
    """對齊 0714：實際開檔取 frontmatter 的 skill_id（非只有目錄名）。"""
    from refiner.normalizer import extract_used_skill_ids

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skills_root = os.path.join(project_root, "skills", "coding-debug")
    turns = [{
        "prompt_text": "read skills/coding-debug/v_a/SKILL.md",
        "response_text": "",
        "tool_calls": [{"function": {"name": "read", "arguments": '{"path":"skills/coding-debug/v_a/SKILL.md"}'}}],
        "tool_results": [{"path": "skills/coding-debug/v_a/SKILL.md"}],
    }]
    names, ids = extract_used_skill_ids(turns, skills_root=skills_root)
    assert "v_a" in names
    assert "coding-debug" in ids  # frontmatter slug，非目錄名雜湊


def test_experiment_record_has_actual_used_skill_ids():
    rec = {
        "session_id": "task_001::v_a", "skill_name": "coding-debug", "skill_id": "coding-debug",
        "variant_label": "v_a", "task_id": "task_001", "selected_skill_ids": ["coding-debug"],
        "turns": [{"prompt_text": "x", "response_text": "y"}], "test": {"pass_rate": 1.0},
    }
    s = normalize_experiment_record(rec)
    assert s["actual_used_skill_ids"] == ["coding-debug"]
