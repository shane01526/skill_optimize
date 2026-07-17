"""一次性：把 ppt_table_of_content_source 的 HTML 論文抽成純文字 sources.md。

去掉 script/style/base64 圖與所有標籤，保留可讀文字（全文不截斷）。
只處理可行的兩篇小論文（42MB 那篇與 726K 字那篇因太大排除，見 plan 誠實聲明）。

用法：python tools/extract_sources.py
"""

from __future__ import annotations

import html as _html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_DIR = os.path.join(ROOT, "golden", "general_e2e", "ppt_table_of_content_source")

# (原始 HTML 檔名, 目標 task 目錄, 論文標題)
JOBS = [
    ("Teaching Claude why _ Anthropic.html", "ppt_outline_teaching", "Teaching Claude Why (Anthropic)"),
    ("Paving the way for AI agents in biology _ Anthropic.html", "ppt_outline_biology", "Paving the Way for AI Agents in Biology (Anthropic)"),
]


def html_to_text(raw: str) -> str:
    # 去 script/style/noscript
    raw = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    # 區塊標籤轉換行，方便段落切分
    raw = re.sub(r"</(p|div|section|article|h[1-6]|li|ul|ol|br|tr|table)\s*>", "\n", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    # 去掉其餘標籤
    raw = re.sub(r"<[^>]+>", " ", raw)
    # HTML entity 還原
    raw = _html.unescape(raw)
    # 去掉殘留的 data-uri / 超長 token（base64 等）
    raw = re.sub(r"\S{200,}", " ", raw)
    # 正規化空白
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    for fname, task_dir, title in JOBS:
        src = os.path.join(SRC_DIR, fname)
        if not os.path.exists(src):
            print(f"[skip] not found: {fname}")
            continue
        with open(src, "r", encoding="utf-8", errors="ignore") as fh:
            raw = fh.read()
        text = html_to_text(raw)
        out_dir = os.path.join(ROOT, "golden", "ppt_e2e", task_dir)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "sources.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(f"# SOURCE PAPER: {title}\n\n（由 {fname} 抽出的純文字全文，非即時查詢）\n\n{text}\n")
        print(f"[ok] {task_dir}/sources.md  chars={len(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
