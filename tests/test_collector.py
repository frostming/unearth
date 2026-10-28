import pytest

from unearth import PackageFinder
from unearth.collector import collect_links_from_location
from unearth.link import Link


@pytest.mark.parametrize(
    "attribute,version,reason",
    [
        ("", "2.0", None),
        ("data-yanked", "1.0", ""),
        ('data-yanked=""', "1.0", ""),
        ('data-yanked="broken release"', "1.0", "broken release"),
    ],
)
def test_yanked_attribute_presence_controls_package_selection(
    pypi, pypi_session, attribute, version, reason
):
    @pypi.route("/simple/yank-demo/")
    def index():
        body = (
            '<a href="/files/yank_demo-1.0-py3-none-any.whl">1.0</a>'
            f'<a href="/files/yank_demo-2.0-py3-none-any.whl" {attribute}>2.0</a>'
        )
        return body, 200, {"Content-Type": "text/html"}

    finder = PackageFinder(
        session=pypi_session, index_urls=["https://test.pypi.org/simple/"]
    )
    assert finder.find_best_match("yank-demo").best.version == version
    pinned = finder.find_best_match("yank-demo==2.0").best
    assert pinned.version == "2.0"
    assert pinned.link.yank_reason == reason


def test_collector_skip_insecure_hosts(pypi_session, caplog):
    collected = list(
        collect_links_from_location(
            pypi_session, Link("http://insecure.com/simple/click")
        )
    )
    assert not collected
    assert "not being trusted" in caplog.records[0].message


def test_collector_skip_vcs_link(pypi_session, caplog):
    collected = list(
        collect_links_from_location(
            pypi_session, Link("git+https://github.com/pallets/click.git")
        )
    )
    assert not collected
    assert "It is a VCS link" in caplog.records[0].message


def test_collect_links_from_404_page(pypi_session):
    link = Link("https://test.pypi.org/simple/not-found")
    collected = list(collect_links_from_location(pypi_session, link))
    assert collected == [link]


def test_skip_non_html_archive(pypi_session, caplog):
    link = Link("https://test.pypi.org/files/click-8.1.3-py3-none-any.whl")
    collected = list(collect_links_from_location(pypi_session, link))
    assert collected == [link]
    assert "Content-Type unsupported" in caplog.records[0].message


@pytest.mark.usefixtures("content_type")
def test_collect_links_from_index_page(pypi_session):
    collected = sorted(
        collect_links_from_location(
            pypi_session, Link("https://test.pypi.org/simple/click")
        ),
        key=lambda link: link.filename,
    )
    assert len(collected) == 5
    assert all(link.url.startswith("https://test.pypi.org") for link in collected)


@pytest.mark.parametrize("filename", ["findlinks", "findlinks/index.html"])
def test_collect_links_from_local_file(pypi_session, fixtures_dir, filename):
    link = Link.from_path(fixtures_dir / filename)
    collected = sorted(
        collect_links_from_location(pypi_session, link),
        key=lambda link: link.filename,
    )
    assert [link.filename for link in collected] == [
        "click-8.1.3-py3-none-any.whl",
        "click-8.1.3.tar.gz",
        "first-2.0.3-py2.py3-none-any.whl",
        "first-2.0.3.tar.gz",
    ]


def test_collect_links_from_local_dir_expand(pypi_session, fixtures_dir):
    link = Link.from_path(fixtures_dir / "findlinks")
    collected = sorted(
        collect_links_from_location(pypi_session, link, expand=True),
        key=lambda link: link.filename,
    )
    assert [link.filename for link in collected] == [
        "Jinja2-3.1.2-py3-none-any.whl",
        "click-8.1.3-py3-none-any.whl",
        "click-8.1.3.tar.gz",
        "first-2.0.3-py2.py3-none-any.whl",
        "first-2.0.3.tar.gz",
    ]
