import pytest

from unearth.collector import collect_links_from_location
from unearth.link import Link


def test_collector_skip_insecure_hosts(pypi, session, caplog):
    collected = list(
        collect_links_from_location(session, Link("http://insecure.com/simple/click"))
    )
    assert not collected
    assert "not being trusted" in caplog.records[0].message


def test_collector_skip_vcs_link(pypi, session, caplog):
    collected = list(
        collect_links_from_location(
            session, Link("git+https://github.com/pallets/click.git")
        )
    )
    assert not collected
    assert "because it is a VCS link" in caplog.records[0].message


def test_collect_links_from_404_page(pypi, session):
    collected = list(
        collect_links_from_location(
            session, Link("https://test.pypi.org/simple/not-found")
        )
    )
    assert not collected


def test_skip_non_html_archive(pypi, session, caplog):
    collected = list(
        collect_links_from_location(
            session, Link("https://test.pypi.org/files/click-8.1.3-py3-none-any.whl")
        )
    )
    assert not collected
    assert "NotHTML: only HTML is supported" in caplog.records[0].message


def test_collect_links_from_index_page(pypi, session):
    collected = sorted(
        collect_links_from_location(
            session, Link("https://test.pypi.org/simple/click")
        ),
        key=lambda link: link.filename,
    )
    assert len(collected) == 4


@pytest.mark.parametrize("filename", ["findlinks", "findlinks/index.html"])
def test_collect_links_from_local_file(pypi, session, fixtures_dir, filename):
    link = Link.from_path(fixtures_dir / filename)
    collected = sorted(
        collect_links_from_location(session, link),
        key=lambda link: link.filename,
    )
    assert [link.filename for link in collected] == [
        "click-8.1.3-py3-none-any.whl",
        "click-8.1.3.tar.gz",
        "first-2.0.3-py2.py3-none-any.whl",
        "first-2.0.3.tar.gz",
    ]


def test_collect_links_from_local_dir_expand(pypi, session, fixtures_dir):
    link = Link.from_path(fixtures_dir / "findlinks")
    collected = sorted(
        collect_links_from_location(session, link, expand=True),
        key=lambda link: link.filename,
    )
    assert [link.filename for link in collected] == [
        "Jinja2-3.1.2-py3-none-any.whl",
        "click-8.1.3-py3-none-any.whl",
        "click-8.1.3.tar.gz",
        "first-2.0.3-py2.py3-none-any.whl",
        "first-2.0.3.tar.gz",
    ]
