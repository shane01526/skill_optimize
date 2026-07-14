"""Skill 精煉機制 — 版本 A（精簡自建 pipeline）。

借用 SkillClaw evolve_server 的核心設計（summarize → aggregate →
execute(improve/create/merge) → verify → registry），但去除 proxy / OSS /
dashboard / Nacos 等重架構，改成一個可離線、可讀、以檔案為主的個人版 MVP。

參考原始碼：``third_party/skillclaw/evolve_server/``
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
