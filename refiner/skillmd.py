"""SKILL.md 解析 / 產生 + 精煉版 JSON 解析工具。

改寫自 ``third_party/skillclaw/evolve_server/core/utils.py``，
但額外支援本專案在 front-matter 加入的 ``skill_id`` / ``version`` 欄位
（見 Skill 精煉機制_new.md line 63-70：skill hub 上架時必須有 skill_id）。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - yaml 是硬需求，但給清楚訊息
    yaml = None  # type: ignore


# ------------------------------------------------------------------ #
#  skill_id：與 SkillClaw 一致 = SHA-256(name) 前 12 個 hex 字元        #
# ------------------------------------------------------------------ #


def compute_skill_id(name: str) -> str:
    """回傳穩定的 skill_id（跨機器 / 重啟都一致）。"""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]


def content_sha(content: str) -> str:
    """SKILL.md 內容的 SHA-256（用於衝突偵測與版本追蹤）。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ #
#  SKILL.md 解析                                                       #
# ------------------------------------------------------------------ #


def parse_skill_md(raw_md: str, *, fallback_name: str = "unknown") -> dict[str, Any]:
    """解析一份 SKILL.md，回傳結構化 dict。

    回傳鍵：``skill_id``, ``name``, ``version``, ``description``,
    ``category``, ``content``（body）, ``extra_frontmatter``。
    """
    result: dict[str, Any] = {
        "skill_id": "",
        "name": fallback_name,
        "version": "",
        "description": "",
        "category": "general",
        "content": "",
        "extra_frontmatter": {},
    }
    text = raw_md.lstrip("﻿")  # 去 BOM
    if not text.startswith("---"):
        result["content"] = text.strip()
        result["skill_id"] = compute_skill_id(result["name"])
        return result

    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        result["content"] = text.strip()
        result["skill_id"] = compute_skill_id(result["name"])
        return result

    fm_text = text[3:end_idx].strip()
    body = text[end_idx + 4:].strip()

    fm: dict[str, Any] = {}
    if yaml is not None:
        try:
            loaded = yaml.safe_load(fm_text)
            if isinstance(loaded, dict):
                fm = loaded
        except Exception:
            fm = {}
    if not fm:  # yaml 缺席或解析失敗 → regex 退回
        for key in ("skill_id", "name", "version", "description", "category"):
            m = re.search(rf'^{key}:\s*["\']?(.*?)["\']?\s*$', fm_text, re.MULTILINE)
            if m:
                fm[key] = m.group(1)

    name = str(fm.get("name") or fallback_name)
    result["name"] = name
    result["description"] = str(fm.get("description", ""))
    result["category"] = str(fm.get("category", "general"))
    result["version"] = str(fm.get("version", ""))
    result["skill_id"] = str(fm.get("skill_id") or compute_skill_id(name))
    extra = {
        k: v
        for k, v in fm.items()
        if k not in ("skill_id", "name", "version", "description", "category")
    }
    if extra:
        result["extra_frontmatter"] = extra
    result["content"] = body
    return result


# ------------------------------------------------------------------ #
#  SKILL.md 產生                                                       #
# ------------------------------------------------------------------ #


def build_skill_md(skill: dict[str, Any]) -> str:
    """把 skill dict 產生成 SKILL.md 文字（含 skill_id / version front-matter）。"""
    name = skill.get("name", "unknown")
    description = skill.get("description", "")
    category = skill.get("category", "general")
    content = skill.get("content", "")
    skill_id = skill.get("skill_id") or compute_skill_id(name)
    version = skill.get("version")

    needs_quoting = any(c in description for c in ":{}[],\"'#&*!|>%@`\n")
    if needs_quoting:
        escaped = description.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        desc_line = f'description: "{escaped}"'
    else:
        desc_line = f"description: {description}"

    fm_lines = [f"skill_id: {skill_id}", f"name: {name}"]
    if version not in (None, ""):
        fm_lines.append(f"version: {version}")
    fm_lines.append(desc_line)
    fm_lines.append(f"category: {category}")

    extra_fm = skill.get("extra_frontmatter")
    if isinstance(extra_fm, dict) and yaml is not None:
        for key, value in extra_fm.items():
            if key not in ("skill_id", "name", "version", "description", "category"):
                fm_lines.append(f"{key}: {yaml.dump(value, default_flow_style=True).strip()}")

    return "---\n" + "\n".join(fm_lines) + "\n---\n\n" + str(content).strip() + "\n"


# ------------------------------------------------------------------ #
#  LLM 輸出 JSON 解析（strict JSON，允許 markdown fence）              #
# ------------------------------------------------------------------ #


def extract_json_object(text: str) -> Optional[dict[str, Any]]:
    """從 LLM 輸出抽出第一個 JSON 物件（容忍 ```json fence 與前後雜訊）。"""
    clean = re.sub(r"```(?:json)?\s*", "", str(text or "").strip()).strip().rstrip("`")
    if not clean:
        return None
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(clean[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            return None
    return None
