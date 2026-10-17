from cameras import find_camera

PHONE_CONNECTED = [(0, "Roman's iPhone Camera"), (1, "MacBook Pro Camera")]
PHONE_GONE = [(0, "MacBook Pro Camera")]


def test_finds_the_phone_wherever_it_sorts():
    assert find_camera("iphone", PHONE_CONNECTED) == 0
    assert find_camera("MacBook", PHONE_CONNECTED) == 1


def test_missing_camera_is_none_not_another_camera():
    assert find_camera("iPhone", PHONE_GONE) is None
    assert find_camera("iPhone", []) is None
