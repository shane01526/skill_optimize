"""registry：skill_id 穩定性、version 遞增、history 上限、持久化。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refiner.registry import SkillRegistry, SkillValidationError
from refiner.skillmd import compute_skill_id


def test_skill_id_stable_across_instances():
    assert compute_skill_id("coding-debug") == compute_skill_id("coding-debug")
    assert len(compute_skill_id("coding-debug")) == 12


def test_get_or_create_and_version_increment(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    sid = reg.get_or_create("coding-debug")
    assert sid == compute_skill_id("coding-debug")
    assert reg.get_version("coding-debug") == 0

    v1 = reg.record_update("coding-debug", "sha1", action="improve_skill", timestamp="2026-01-01T00:00:00+00:00")
    v2 = reg.record_update("coding-debug", "sha2", action="improve_skill", timestamp="2026-01-02T00:00:00+00:00")
    assert v1 == 1 and v2 == 2
    assert reg.get_content_sha("coding-debug") == "sha2"


def test_history_capped_at_20(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    reg.get_or_create("x")
    for i in range(30):
        reg.record_update("x", f"sha{i}", timestamp=f"2026-01-01T00:00:{i:02d}+00:00")
    hist = reg.entry("x")["history"]
    assert len(hist) == 20
    assert hist[-1]["content_sha"] == "sha29"


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "reg.json")
    reg = SkillRegistry(path)
    reg.get_or_create("skill-a")
    reg.record_update("skill-a", "shaA", timestamp="2026-01-01T00:00:00+00:00")
    reg.save()

    reg2 = SkillRegistry(path)
    assert reg2.get_version("skill-a") == 1
    assert reg2.get("skill-a") == compute_skill_id("skill-a")


def test_legacy_format_normalised(tmp_path):
    import json

    path = str(tmp_path / "reg.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"old-skill": "abc123"}, fh)
    reg = SkillRegistry(path)
    e = reg.entry("old-skill")
    assert e["skill_id"] == "abc123" and e["version"] == 1


# ---- 上架驗證（Skill 上架流程）--------------------------------- #


def test_register_valid_skill(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    r = reg.register({"skill_id": "coding-debug", "name": "coding-debug", "description": "d"})
    assert r["ok"] is True
    assert r["skill_id"] == "coding-debug"  # 沿用作者 slug，非 hash
    assert reg.get("coding-debug") == "coding-debug"


def test_register_missing_field(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    r = reg.register({"skill_id": "x", "name": "x"})  # 缺 description
    assert r["ok"] is False
    assert any("description" in e for e in r["errors"])


def test_register_bad_slug(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    r = reg.register({"skill_id": "Bad ID!", "name": "n", "description": "d"})
    assert r["ok"] is False
    assert any("格式" in e for e in r["errors"])


def test_register_id_uniqueness_conflict(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    reg.register({"skill_id": "shared", "name": "skill-a", "description": "d"})
    r = reg.register({"skill_id": "shared", "name": "skill-b", "description": "d"})
    assert r["ok"] is False
    assert any("衝突" in e for e in r["errors"])


def test_register_strict_raises(tmp_path):
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    import pytest
    with pytest.raises(SkillValidationError):
        reg.register({"name": "n"}, strict=True)


def test_same_id_same_name_is_ok(tmp_path):
    """同一 skill 的多個變體共用 skill_id + name → 視為同一 skill，不算衝突。"""
    reg = SkillRegistry(str(tmp_path / "reg.json"))
    a = reg.register({"skill_id": "coding-debug", "name": "coding-debug", "description": "d"})
    b = reg.register({"skill_id": "coding-debug", "name": "coding-debug", "description": "d2"})
    assert a["ok"] and b["ok"]
