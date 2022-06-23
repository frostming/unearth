import pytest

from unearth import Link
from unearth.evaluator import TargetPython
from unearth.finder import PackageFinder

pytestmark = pytest.mark.usefixtures("pypi")


@pytest.mark.parametrize(
    "target_python,filename",
    [
        (
            TargetPython((3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]),
            "black-22.3.0-cp39-cp39-win_amd64.whl",
        ),
        (
            TargetPython((3, 8), abis=["cp38"], impl="cp", platforms=["win_amd64"]),
            "black-22.3.0-cp38-cp38-win_amd64.whl",
        ),
        (
            TargetPython(
                (3, 9), abis=["cp39"], impl="cp", platforms=["manylinux2014_x86_64"]
            ),
            "black-22.3.0-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        ),
        (
            TargetPython(
                (3, 9), abis=["cp39"], impl="cp", platforms=["macosx_11_0_arm64"]
            ),
            "black-22.3.0-py3-none-any.whl",
        ),
    ],
)
def test_find_most_matching_wheel(session, target_python, filename):
    finder = PackageFinder(
        session, index_urls=["https://pypi.org/simple"], target_python=target_python
    )
    assert finder.find_best_match("black").best.link.filename == filename


def test_find_package_with_format_control(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        no_binary=["black"],
        only_binary=["first"],
    )
    assert finder.find_best_match("black").best.link.filename == "black-22.3.0.tar.gz"
    assert (
        finder.find_best_match("first").best.link.filename
        == "first-2.0.1-py2.py3-none-any.whl"
    )


def test_find_package_no_binary_for_all(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        no_binary=[":all:"],
    )
    assert finder.find_best_match("black").best.link.filename == "black-22.3.0.tar.gz"
    assert finder.find_best_match("first").best.link.filename == "first-2.0.2.tar.gz"


def test_find_package_prefer_binary(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        prefer_binary=True,
    )
    assert (
        finder.find_best_match("first").best.link.filename
        == "first-2.0.1-py2.py3-none-any.whl"
    )


def test_find_package_with_hash_allowance(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
    )
    assert (
        finder.find_best_match(
            "first",
            hashes={
                "sha256": [
                    "41d5b64e70507d0c3ca742d68010a76060eea8a3d863e9b5130ab11a4a91aa0e"
                ]
            },
        ).best.link.filename
        == "first-2.0.1-py2.py3-none-any.whl"
    )


@pytest.mark.parametrize("ignore_compat", [True, False])
def test_find_package_ignoring_compatibility(session, ignore_compat):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        ignore_compatibility=ignore_compat,
    )
    all_available = finder.find_matches("black==22.3.0")
    assert len(all_available) == (6 if ignore_compat else 3)


def test_find_package_with_version_specifier(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        ignore_compatibility=True,
    )
    matches = finder.find_matches("black==22.3.0")
    assert len(matches) == 6
    assert all(p.name == "black" and p.version == "22.3.0" for p in matches)
    matches = finder.find_matches("black<22.3.0")
    assert len(matches) == 0


def test_find_package_allowing_prereleases(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        ignore_compatibility=True,
    )
    matches = finder.find_matches("black<22.3.0", allow_prereleases=True)
    assert len(matches) == 2
    assert all(p.name == "black" and p.version == "21.12b0" for p in matches)

    matches = finder.find_matches("black==21.12b0")
    assert len(matches) == 2
    assert all(p.name == "black" and p.version == "21.12b0" for p in matches)

    matches = finder.find_matches("black<=21.12b1", allow_prereleases=False)
    assert len(matches) == 0


def test_find_requirement_with_link(session):
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        ignore_compatibility=True,
    )
    req = "first @ https://pypi.org/files/first-2.0.2.tar.gz"
    matches = finder.find_matches(req)
    assert len(matches) == 1
    assert matches[0].name == "first"
    assert matches[0].link.normalized == "https://pypi.org/files/first-2.0.2.tar.gz"


def test_find_requirement_preference(session, fixtures_dir):
    find_link = Link.from_path(fixtures_dir / "findlinks/index.html")
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        find_links=[find_link.normalized],
        ignore_compatibility=True,
    )
    best = finder.find_best_match("first").best
    assert best.link.filename == "first-2.0.3-py2.py3-none-any.whl"
    assert best.link.comes_from == find_link.normalized


def test_find_requirement_preference_respect_source_order(session, fixtures_dir):
    find_link = Link.from_path(fixtures_dir / "findlinks/index.html")
    finder = PackageFinder(
        session,
        index_urls=["https://pypi.org/simple"],
        find_links=[find_link.normalized],
        ignore_compatibility=True,
        respect_source_order=True,
    )
    best = finder.find_best_match("first").best
    assert best.link.filename == "first-2.0.2.tar.gz"
    assert best.link.comes_from == "https://pypi.org/simple/first/"
