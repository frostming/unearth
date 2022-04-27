from pathlib import Path

import pytest

from unearth.link import Link
from unearth.utils import WINDOWS


@pytest.mark.parametrize(
    "url, normalized",
    [
        ("https://pypi.org/simple", "https://pypi.org/simple"),
        (
            "git+https://github.com/pallets/click.git@master",
            "git+https://github.com/pallets/click.git@master",
        ),
        ("git+git@github.com:pypa/pip.git", "git+ssh://git@github.com/pypa/pip.git"),
    ],
)
def test_link_normalized(url, normalized):
    assert Link(url).normalized == normalized


@pytest.mark.parametrize(
    "left,right,is_equal",
    [
        (
            Link("https://pypi.org/simple"),
            Link("https://pypi.org/simple", comes_from="https://pypi.org"),
            True,
        ),
        (
            Link("git+git@github.com:pypa/pip.git"),
            Link("git+ssh://git@github.com/pypa/pip.git"),
            True,
        ),
        (
            Link("git+https://github.com/pypa/pip.git@main"),
            Link("git+https://github.com/pypa/pip.git@22.0.4"),
            False,
        ),
        (
            Link("git+https://github.com/pypa/pip.git@main#egg=pip"),
            Link("git+https://github.com/pypa/pip.git@main#egg=pip&subdirectory=src"),
            False,
        ),
        (
            Link("https://pypi.org/simple/click/8.0.1"),
            Link("https://pypi.org/simple/click/8.0.1", yank_reason=""),
            False,
        ),
        (
            Link("https://pypi.org/simple/click/8.0.1", requires_python=">=3.6"),
            Link("https://pypi.org/simple/click/8.0.1", requires_python=">=3.7"),
            False,
        ),
    ],
)
def test_link_equality(left, right, is_equal):
    assert (left == right) is is_equal


def test_link_is_file_and_filepath():
    if WINDOWS:
        link = Link("file:///C:/path/to/file")
        path = Path("C:/path/to/file")
    else:
        link = Link("file:///path/to/file")
        path = Path("/path/to/file")
    assert link.is_file
    assert link.file_path == path

    assert not Link("http://example.org/").is_file


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://example.org/", False),
        ("git+git@github.com:pypa/pip.git", True),
        ("svn+https://svn.example.org/repo", True),
        ("abc+https://test.com/", False),
    ],
)
def test_link_is_vcs(url, expected):
    assert Link(url).is_vcs == expected


def test_link_url_without_fragment():
    link = Link("https://pypi.org/simple#egg=pip&subdirectory=src")
    assert link._fragment_dict == {"egg": "pip", "subdirectory": "src"}
    assert link.subdirectory == "src"
    assert link.url_without_fragment == "https://pypi.org/simple"


def test_link_filename_and_hash():
    link = Link(
        "https://files.pythonhosted.org/packages/c2/f1/df59e28c642d583f7dacffb1e0965d"
        "0e00b218e0186d7858ac5233dce840/click-8.1.3%2Bcpu-py3-none-any.whl"
        "#sha256=bb4d8133cb15a609f44e8213d9b391b0809795062913b383c62be0ee95b1db48"
    )
    assert link.filename == "click-8.1.3+cpu-py3-none-any.whl"
    assert link.is_wheel
    assert link.hash_name == "sha256"
    assert (
        link.hash == "bb4d8133cb15a609f44e8213d9b391b0809795062913b383c62be0ee95b1db48"
    )


@pytest.mark.parametrize(
    "url,splitted,redacted",
    (
        [
            (
                "https://pypi.org/simple",
                (None, "https://pypi.org/simple"),
                "https://pypi.org/simple",
            ),
            (
                "https://abc@pypi.org/simple",
                (("abc", None), "https://pypi.org/simple"),
                "https://***@pypi.org/simple",
            ),
            (
                "https://abc:pass@pypi.org/simple",
                (("abc", "pass"), "https://pypi.org/simple"),
                "https://***@pypi.org/simple",
            ),
        ]
    ),
)
def test_link_split_auth_and_redact(url, splitted, redacted):
    link = Link(url)
    assert splitted == link.split_auth()
    assert link.redacted == redacted
