"""String Calculator —— 內含 bug 的起始碼（golden task_001）。

已知 bug：
  1. 空字串未處理 → int("") 會拋例外。
  2. 只用逗號切，未支援換行符分隔。
  3. 未忽略 > 1000 的數字。
"""


def add(numbers: str) -> int:
    parts = numbers.split(",")
    total = 0
    for p in parts:
        total += int(p)
    return total
