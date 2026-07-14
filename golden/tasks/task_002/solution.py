# 參考解答（僅供離線 simulate 模式使用；codex 真跑時不需要）。
# 見 task_001/solution.py 的說明。
# 額外提供 _PARTIAL_SOLUTION：中等強度 skill 只修好部分（示範 partial pass）。
_SOLUTION = '''\
def fizzbuzz(n: int) -> str:
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return str(n)
'''

# partial：修好 FizzBuzz 順序，但忘了把數字轉成 str（test_number 仍失敗）
_PARTIAL_SOLUTION = '''\
def fizzbuzz(n: int) -> str:
    if n % 15 == 0:
        return "FizzBuzz"
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return n
'''
