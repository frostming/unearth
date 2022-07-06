import pytest
from packaging.requirements import Requirement

from unearth.evaluator import (
    Evaluator,
    FormatControl,
    Package,
    TargetPython,
    evaluate_package,
)
from unearth.link import Link

BINARY_LINKS = [
    Link("https://test.pypi.org/files/click-8.1.3-py3-none-any.whl"),
    Link("file:///home/user/click-8.1.3-py3-none-any.whl"),
]

SOURCE_LINKS = [
    Link("file:///home/user/code/click"),
    Link("https://test.pypi.org/files/click-8.1.3.tar.gz"),
    Link("https://test.pypi.org/files/Jinja2-3.1.2.zip"),
    Link("git+https://github.com/pallets/click.git@main"),
]


@pytest.fixture()
def session():
    from unearth.session import PyPISession

    sess = PyPISession()
    try:
        yield sess
    finally:
        sess.close()


def test_no_binary_and_only_binary_conflict():
    with pytest.raises(ValueError):
        FormatControl(no_binary=True, only_binary=True)


@pytest.mark.parametrize("link", BINARY_LINKS)
def test_only_binary_is_allowed(link):
    format_control = FormatControl(only_binary=True, no_binary=False)
    format_control.check_format(link, "foo")

    format_control = FormatControl(only_binary=False, no_binary=True)
    with pytest.raises(ValueError):
        format_control.check_format(link, "foo")


@pytest.mark.parametrize("link", SOURCE_LINKS)
def test_no_binary_is_allowed(link):
    format_control = FormatControl(only_binary=True, no_binary=False)
    with pytest.raises(ValueError):
        format_control.check_format(link, "foo")

    format_control = FormatControl(only_binary=False, no_binary=True)
    format_control.check_format(link, "foo")


@pytest.mark.parametrize("link", BINARY_LINKS + SOURCE_LINKS)
def test_default_format_control_allow_all(link):
    format_control = FormatControl()
    format_control.check_format(link, "foo")


@pytest.mark.parametrize("allow_yanked", (True, False))
def test_evaluate_yanked_link(allow_yanked, session):
    link = Link(
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl", yank_reason="bad"
    )
    evaluator = Evaluator("click", session, allow_yanked=allow_yanked)
    if allow_yanked:
        assert evaluator.evaluate_link(link) is not None
    else:
        assert evaluator.evaluate_link(link) is None


@pytest.mark.parametrize(
    "python_version,requires_python,expected",
    [
        ((3, 9), None, True),
        ((3, 9), ">=3.9", True),
        ((3, 8), ">=3.9", False),
    ],
)
@pytest.mark.parametrize("ignore_compatibility", (True, False))
def test_evaluate_link_python_version(
    python_version, requires_python, expected, ignore_compatibility, session
):
    link = Link(
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl",
        requires_python=requires_python,
    )
    evaluator = Evaluator(
        "click",
        session,
        target_python=TargetPython(python_version),
        ignore_compatibility=ignore_compatibility,
    )
    assert (evaluator.evaluate_link(link) is None) is not (
        expected or ignore_compatibility
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://test.pypi.org/files/click-8.1.3.whl",
        "https://test.pypi.org/files/click-8.1.3_develop-py3-none-any.whl",
    ],
)
def test_evaluate_invalid_wheel_name(url, session):
    link = Link(url)
    evaluator = Evaluator("click", session)
    assert evaluator.evaluate_link(link) is None


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://test.pypi.org/files/click-8.1.3-py3-none-any.whl", True),
        ("https://test.pypi.org/files/Click-8.1.3.tar.gz", True),
        ("https://test.pypi.org/files/Jinja2-3.1.2.zip", False),
    ],
)
def test_evaluate_against_name_match(link, expected, session):
    evaluator = Evaluator("click", session)
    assert (evaluator.evaluate_link(Link(link)) is None) is not expected


@pytest.mark.parametrize(
    "link",
    [
        Link("https://test.pypi.org/files/click.zip"),
        Link("https://test.pypi.org/files/click.tar.gz"),
        Link("git+git@github.com:pallets/click.git@main"),
        Link("git+git@github.com:pallets/click.git@main#egg=click"),
    ],
)
def test_evaluate_against_missing_version(link, session):
    evaluator = Evaluator("click", session)
    assert evaluator.evaluate_link(link) is None


@pytest.mark.parametrize(
    "url,match",
    [
        (
            "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl"
            "#sha256=1234567890abcdef",
            True,
        ),
        (
            "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl"
            "#sha256=fedcba0987654321",
            True,
        ),
        (
            "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl"
            "#sha256=1112222",
            False,
        ),
    ],
)
def test_evaluate_against_allowed_hashes(session, url, match):
    evaluator = Evaluator(
        "click", session, hashes={"sha256": ["1234567890abcdef", "fedcba0987654321"]}
    )

    assert (evaluator.evaluate_link(Link(url)) is not None) is match


@pytest.mark.parametrize(
    "url",
    [
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl",
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl#sha256=123456",
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl#md5=1111222",
    ],
)
def test_evaluate_allow_all_hashes(session, url):
    evaluator = Evaluator("click", session)
    assert evaluator.evaluate_link(Link(url)) is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl",
        "https://test.pypi.org/files/click-8.1.3-py3-none-any.whl#md5=1111222",
    ],
)
def test_retrieve_hash_from_internet(pypi, session, url):
    evaluator = Evaluator(
        "click",
        session,
        hashes={
            "sha256": [
                "bb4d8133cb15a609f44e8213d9b391b0809795062913b383c62be0ee95b1db48"
            ]
        },
    )
    link = Link(url)
    assert evaluator.evaluate_link(link) is not None
    assert link.hash_name == "sha256"
    assert (
        link.hash == "bb4d8133cb15a609f44e8213d9b391b0809795062913b383c62be0ee95b1db48"
    )


@pytest.mark.parametrize(
    "link,expected",
    [
        (Link("https://test.pypi.org/files/click-8.1.3-py3-none-any.whl"), True),
        (Link("https://test.pypi.org/files/click-8.1.3-cp39-cp39-win_amd64.whl"), True),
        (
            Link("https://test.pypi.org/files/click-8.1.3-cp310-cp310-win_amd64.whl"),
            False,
        ),
        (
            Link(
                "https://test.pypi.org/files/click-8.1.3-cp39-cp39-"
                "macosx_11_0_arm64.whl"
            ),
            False,
        ),
    ],
)
@pytest.mark.parametrize("ignore_compatibility", (True, False))
def test_evaluate_compatibility_tags(link, expected, ignore_compatibility, session):
    evaluator = Evaluator(
        "click",
        session,
        target_python=TargetPython((3, 9), ["cp39"], "cp", ["win_amd64"]),
        ignore_compatibility=ignore_compatibility,
    )
    assert (evaluator.evaluate_link(link) is None) is not (
        expected or ignore_compatibility
    )


@pytest.mark.parametrize(
    "version,requires,allow_prereleases,expected",
    [
        ("8.1.3", ">=8.0", None, True),
        ("7.1", ">=8.0", None, False),
        ("8.0.0a0", ">=8.0.0dev0", None, True),
        ("8.0.0dev0", ">=7", None, False),
        ("8.0.0dev0", ">=7", True, True),
        ("8.0.0a0", ">=8.0.0dev0", False, False),
    ],
)
def test_evaluate_packages_matching_version(
    version, requires, allow_prereleases, expected
):
    requirement = Requirement(f"click{requires}")
    link = Link(f"https://test.pypi.org/packages/source/c/click/click-{version}.tar.gz")
    package = Package("click", version, link)
    assert evaluate_package(package, requirement, allow_prereleases) is expected


def test_evaluate_packages_matching_url():
    requirement = Requirement(
        "click @ https://test.pypi.org/packages/source/c/click/click-8.1.3.tar.gz"
    )
    link = Link("https://test.pypi.org/packages/source/c/click/click-8.1.3.tar.gz")
    package = Package("click", None, link)
    assert evaluate_package(package, requirement, None)
