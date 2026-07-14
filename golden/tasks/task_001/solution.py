# 參考解答（僅供離線 simulate 模式使用；codex 真跑時不需要）。
# runner 在 mock/api 模式且變體「夠詳細」時，會把此檔覆蓋到 stringcalc.py，
# 模擬「好 skill → agent 成功修復」。這不是評分作弊，而是讓離線 demo 能重現
# 「測試通過率隨 skill 品質變化」的效果；真實評分請用 --mode codex。
_SOLUTION = '''\
def add(numbers: str) -> int:
    if not numbers:
        return 0
    parts = numbers.replace("\\n", ",").split(",")
    total = 0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        n = int(p)
        if n > 1000:
            continue
        total += n
    return total
'''

# partial：只加空字串特判，其餘 bug（換行分隔、忽略 >1000）保留 → 部分測試通過
_PARTIAL_SOLUTION = '''\
def add(numbers: str) -> int:
    if not numbers:
        return 0
    return sum(int(p) for p in numbers.split(","))
'''
