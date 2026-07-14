"""FizzBuzz —— 內含 bug 的起始碼（golden task_002）。

已知 bug：
  1. 先檢查 %3、%5，導致 %15 的情況永遠回 "Fizz"（未先判斷 FizzBuzz）。
  2. 其餘數字回傳 int 而非 str。
"""


def fizzbuzz(n: int) -> str:
    if n % 3 == 0:
        return "Fizz"
    if n % 5 == 0:
        return "Buzz"
    return n
