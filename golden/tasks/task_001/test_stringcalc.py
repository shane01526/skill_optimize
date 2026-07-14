from stringcalc import add


def test_empty():
    assert add("") == 0


def test_single():
    assert add("1") == 1


def test_comma():
    assert add("1,2,3") == 6


def test_newline():
    assert add("1\n2,3") == 6


def test_ignore_big():
    assert add("2,1001") == 2
