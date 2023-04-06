from unittest import mock

from unearth.utils import LazySequence


def test_lazy_sequence():
    func = mock.Mock()

    def gen(size):
        for i in range(size):
            func()
            yield i

    seq = LazySequence(gen(5))
    assert bool(seq) is True
    assert func.call_count == 1
    assert seq[0] == 0
    assert func.call_count == 1
    assert seq[1] == 1
    assert func.call_count == 2
    assert 3 in seq
    assert func.call_count == 4
    assert len(seq) == 5
    assert list(seq) == [0, 1, 2, 3, 4]
    assert func.call_count == 5
