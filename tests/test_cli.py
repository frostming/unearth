import json

from unearth.__main__ import cli
from unearth.evaluator import Package
from unearth.link import Link


def test_download_does_not_unpack(mocker, tmp_path, capsys):
    link = Link("https://example.org/first-2.0.2.tar.gz")
    match = Package("first", "2.0.2", link)
    finder = mocker.patch("unearth.__main__.PackageFinder").return_value
    finder.find_matches.return_value = [match]
    downloaded = tmp_path / link.filename
    finder.download.return_value = downloaded

    cli(["--no-binary", "--download", str(tmp_path), "first"])

    finder.download.assert_called_once_with(link, str(tmp_path))
    finder.download_and_unpack.assert_not_called()
    assert json.loads(capsys.readouterr().out)["local_path"] == downloaded.as_posix()
