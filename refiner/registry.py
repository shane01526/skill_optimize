"""Skill 註冊表：skill_name → {skill_id, version, content_sha, history}。

改寫自 ``third_party/skillclaw/evolve_server/core/skill_registry.py``，
差異：改用**本機 JSON 檔**持久化（非 OSS/Nacos），適合個人版 MVP。

這是文件 line 61 的核心：skill hub 上架時必須有 skill_id，讓後續的
使用紀錄、評估結果、Skill 精煉都能對齊到同一個 Skill。
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from .skillmd import compute_skill_id

_HISTORY_CAP = 20
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# 上架時必填的 front-matter 欄位（對齊 Skill 精煉機制_0714.md「Skill 上架流程」）
REQUIRED_FIELDS = ("skill_id", "name", "description")


class SkillValidationError(Exception):
    """Skill 上架驗證失敗（欄位不全 / skill_id 不一致 / 唯一性衝突）。"""


class SkillRegistry:
    """維護持久化的 skill_name -> {skill_id, version, content_sha, history}。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self._map: dict[str, dict[str, Any]] = {}
        if path and os.path.exists(path):
            self.load()

    # -- persistence -------------------------------------------------- #

    def load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            self._map = self._normalise(raw)

    def save(self, path: Optional[str] = None) -> None:
        target = path or self.path
        if not target:
            raise ValueError("SkillRegistry.save 需要 path")
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self._map, fh, ensure_ascii=False, indent=2)

    # -- backward compat: 舊格式為 {name: id_str} -------------------- #

    @staticmethod
    def _normalise(raw: dict) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, val in raw.items():
            if isinstance(val, str):
                out[name] = {"skill_id": val, "version": 1, "content_sha": "", "history": []}
            elif isinstance(val, dict):
                out[name] = val
            else:
                out[name] = {
                    "skill_id": compute_skill_id(name),
                    "version": 1,
                    "content_sha": "",
                    "history": [],
                }
        return out

    # -- 上架驗證（Skill 上架流程）------------------------------------ #

    def validate(self, skill: dict[str, Any]) -> list[str]:
        """檢查一份 skill dict 是否可上架，回傳錯誤清單（空 = 通過）。

        對齊 0714 文件「Skill 上架流程」step 3：檢查 skill_id 是否唯一、欄位是否完整。
        - 必填欄位：skill_id / name / description。
        - skill_id 格式：小寫字母/數字/連字號的 slug（對齊 doc 範例 ``skill_id: coding-debug``；
          skill_id 是作者提供的識別碼，非強制等於 SHA-256(name)——後者只是未提供時的預設產生器）。
        - 唯一性：同一 skill_id 若已對應到「不同 name」→ 衝突。
        """
        errors: list[str] = []
        for field in REQUIRED_FIELDS:
            if not str(skill.get(field) or "").strip():
                errors.append(f"缺少必填欄位：{field}")

        name = str(skill.get("name") or "").strip()
        skill_id = str(skill.get("skill_id") or "").strip()
        if skill_id and not _SLUG_RE.match(skill_id):
            errors.append(f"skill_id 格式不合法（需小寫 slug，如 coding-debug）：{skill_id}")
        if name and skill_id:
            # 唯一性：同 id 已存在但對應不同 name
            for existing_name, entry in self._map.items():
                if entry.get("skill_id") == skill_id and existing_name != name:
                    errors.append(
                        f"skill_id 衝突：{skill_id} 已被 '{existing_name}' 使用"
                    )
                    break
        return errors

    def register(self, skill: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
        """驗證並上架一份 skill，回傳 {ok, skill_id, name, errors}。

        通過才建立 registry entry（沿用 get_or_create）。strict=True 時驗證失敗直接 raise。
        """
        errors = self.validate(skill)
        name = str(skill.get("name") or "").strip()
        if errors:
            if strict:
                raise SkillValidationError("; ".join(errors))
            return {"ok": False, "skill_id": skill.get("skill_id", ""), "name": name, "errors": errors}
        # 沿用作者提供的 skill_id（doc 範例為 slug，如 coding-debug）；缺才用 SHA-256 產生
        sid = str(skill.get("skill_id") or "").strip() or compute_skill_id(name)
        entry = self._map.get(name)
        if entry:
            entry["skill_id"] = sid  # 對齊上架宣告
        else:
            self._map[name] = {"skill_id": sid, "version": 0, "content_sha": "", "history": []}
        return {"ok": True, "skill_id": sid, "name": name, "errors": []}

    # -- lookup / generate -------------------------------------------- #

    def get_or_create(self, skill_name: str) -> str:
        entry = self._map.get(skill_name)
        if entry:
            return entry["skill_id"]
        sid = compute_skill_id(skill_name)
        self._map[skill_name] = {"skill_id": sid, "version": 0, "content_sha": "", "history": []}
        return sid

    def get(self, skill_name: str) -> Optional[str]:
        entry = self._map.get(skill_name)
        return entry["skill_id"] if entry else None

    def get_version(self, skill_name: str) -> int:
        entry = self._map.get(skill_name)
        return entry.get("version", 0) if entry else 0

    def get_content_sha(self, skill_name: str) -> str:
        entry = self._map.get(skill_name)
        return entry.get("content_sha", "") if entry else ""

    def record_update(
        self,
        skill_name: str,
        new_content_sha: str,
        action: str = "create",
        *,
        timestamp: Optional[str] = None,
        rationale: str = "",
    ) -> int:
        """記錄一次內容變更，回傳新的 version。history 上限 20 筆。

        ``timestamp`` 可注入（測試 / 可重現性用）；未提供時用當下 UTC。
        """
        entry = self._map.get(skill_name)
        if not entry:
            self.get_or_create(skill_name)
            entry = self._map[skill_name]

        new_version = entry.get("version", 0) + 1
        entry["version"] = new_version
        entry["content_sha"] = new_content_sha

        history: list = entry.setdefault("history", [])
        history.append(
            {
                "version": new_version,
                "content_sha": new_content_sha,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "action": action,
                "rationale": rationale,
            }
        )
        if len(history) > _HISTORY_CAP:
            entry["history"] = history[-_HISTORY_CAP:]
        return new_version

    def all_entries(self) -> dict[str, dict[str, Any]]:
        return deepcopy(self._map)

    def entry(self, skill_name: str) -> Optional[dict[str, Any]]:
        e = self._map.get(skill_name)
        return deepcopy(e) if e else None
