from fizzbuzz import fizzbuzz


def test_fizz():
    assert fizzbuzz(3) == "Fizz"


def test_buzz():
    assert fizzbuzz(5) == "Buzz"


def test_fizzbuzz():
    assert fizzbuzz(15) == "FizzBuzz"


def test_number():
    assert fizzbuzz(7) == "7"


def test_number_two():
    assert fizzbuzz(1) == "1"
