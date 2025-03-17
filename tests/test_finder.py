import datetime

import pytest

from unearth import Link
from unearth.evaluator import TargetPython
from unearth.finder import PackageFinder

pytestmark = pytest.mark.usefixtures("content_type")

DEFAULT_INDEX_URL = "https://pypi.org/simple/"


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
def test_find_most_matching_wheel(pypi_session, target_python, filename):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        target_python=target_python,
    )
    assert finder.find_best_match("black").best.link.filename == filename


def test_find_package_with_format_control(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
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


def test_find_package_no_binary_for_all(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        no_binary=[":all:"],
    )
    assert finder.find_best_match("black").best.link.filename == "black-22.3.0.tar.gz"
    assert finder.find_best_match("first").best.link.filename == "first-2.0.2.tar.gz"


def test_find_package_prefer_binary(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        prefer_binary=["first"],
    )
    assert (
        finder.find_best_match("first").best.link.filename
        == "first-2.0.1-py2.py3-none-any.whl"
    )


def test_find_package_with_hash_allowance(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
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
def test_find_package_ignoring_compatibility(pypi_session, ignore_compat):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        target_python=TargetPython(
            (3, 9), abis=["cp39"], impl="cp", platforms=["win_amd64"]
        ),
        ignore_compatibility=ignore_compat,
    )
    all_available = finder.find_matches("black==22.3.0")
    assert len(all_available) == (6 if ignore_compat else 3)


def test_find_package_with_version_specifier(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        ignore_compatibility=True,
    )
    matches = finder.find_matches("black==22.3.0")
    assert len(matches) == 6
    assert all(p.name == "black" and p.version == "22.3.0" for p in matches)
    match = finder.find_best_match("black<22.3.0")
    assert match.best.version == "21.12b0"
    assert len(match.applicable) == 2


def test_find_package_allowing_prereleases(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
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


def test_find_requirement_with_link(pypi_session):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        ignore_compatibility=True,
    )
    req = "first @ https://pypi.org/files/first-2.0.2.tar.gz"
    matches = finder.find_matches(req)
    assert len(matches) == 1
    assert matches[0].name == "first"
    assert matches[0].link.normalized == "https://pypi.org/files/first-2.0.2.tar.gz"


def test_find_requirement_preference(pypi_session, fixtures_dir):
    find_link = Link.from_path(fixtures_dir / "findlinks/index.html")
    finder = PackageFinder(
        session=pypi_session, index_urls=[DEFAULT_INDEX_URL], ignore_compatibility=True
    )
    finder.add_find_links(find_link.normalized)
    best = finder.find_best_match("first").best
    assert best.link.filename == "first-2.0.3-py2.py3-none-any.whl"
    assert best.link.comes_from == find_link.normalized


def test_find_requirement_preference_respect_source_order(pypi_session, fixtures_dir):
    find_link = Link.from_path(fixtures_dir / "findlinks/index.html")
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        ignore_compatibility=True,
        respect_source_order=True,
    )
    finder.add_find_links(find_link.normalized)
    best = finder.find_best_match("first").best
    assert best.link.filename == "first-2.0.2.tar.gz"
    assert best.link.comes_from == "https://pypi.org/simple/first/"


def test_download_package_file(pypi_session, tmp_path):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        ignore_compatibility=True,
    )
    found = finder.find_best_match("first").best.link
    assert found.filename == "first-2.0.2.tar.gz"
    for subdir in ("download", "unpack"):
        (tmp_path / subdir).mkdir()

    download_reports = []
    unpack_reports = []

    def download_reporter(link, completed, total):
        download_reports.append((link, completed, total))

    def unpack_reporter(filename, completed, total):
        unpack_reports.append((filename, completed, total))

    finder.download_and_unpack(
        found,
        tmp_path / "unpack",
        download_dir=tmp_path / "download",
        download_reporter=download_reporter,
        unpack_reporter=unpack_reporter,
    )
    downloaded = tmp_path / "download" / found.filename
    assert downloaded.exists()
    size = downloaded.stat().st_size
    assert size > 0
    _, completed, total = download_reports[-1]
    assert completed == total == size

    filename, completed, total = unpack_reports[-1]
    assert completed == total
    assert filename == downloaded


def test_exclude_newer_than(pypi_session, content_type):
    finder = PackageFinder(
        session=pypi_session,
        index_urls=[DEFAULT_INDEX_URL],
        ignore_compatibility=True,
        exclude_newer_than=datetime.datetime(
            2024, 1, 31, 0, 0, 0, 0, tzinfo=datetime.timezone.utc
        ),
    )
    matches = finder.find_matches("black")
    # black doesn't support upload_time field
    assert not matches

    matches = finder.find_matches("click")
    if content_type == "json":  # only json api supports upload_time
        assert len(matches) == 2
    else:
        assert not matches
