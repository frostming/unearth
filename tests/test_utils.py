import logging
from unittest import mock

from unearth.utils import LazySequence, get_netrc_auth


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


def test_get_netrc_auth_when_unparsable(caplog, monkeypatch, tmp_path):
    url = "https://test.invalid/blah"
    netrc_path = tmp_path / "netrc"
    netrc_path.write_text("invalid netrc entry", encoding="utf8")
    monkeypatch.setenv("NETRC", str(netrc_path))
    caplog.set_level(logging.WARNING)

    get_netrc_auth(url)

    msgs = [i.msg for i in caplog.records]
    msg = "Couldn't parse netrc because of %s: %s"
    assert msg in msgs


def test_get_netrc_auth_when_netrc_missing(caplog, monkeypatch, tmp_path):
    url = "https://test.invalid/blah"
    monkeypatch.setenv("NETRC", str(tmp_path / "bogus"))
    caplog.set_level(logging.WARNING)

    get_netrc_auth(url)

    msgs = [i.msg for i in caplog.records]
    msg = "Couldn't parse netrc because of %s: %s"
    assert msg not in msgs
