import json

import pytest
from packaging.requirements import Requirement

from unearth import PackageFinder
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


@pytest.fixture()
def requirements_file(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("click==8.1.3\nJinja2==3.1.2\n", encoding="utf-8")
    return path


@pytest.fixture()
def finder_factory(mocker):
    factory = mocker.patch("unearth.__main__.PackageFinder")

    def find_matches(requirement):
        return [
            Package(requirement.name, version, Link(f"https://example.org/{version}"))
            for version in ("3.0", "2.0")
        ]

    factory.return_value.find_matches.side_effect = find_matches
    return factory


@pytest.mark.parametrize("flag", ["-r", "--requirements"])
@pytest.mark.parametrize("all_matches", [False, True])
def test_requirements_order_and_all(
    flag, all_matches, requirements_file, finder_factory, capsys
):
    arguments = [flag, str(requirements_file)]
    if all_matches:
        arguments.append("--all")
    cli(arguments)
    result = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in result] == (
        ["click", "click", "Jinja2", "Jinja2"] if all_matches else ["click", "Jinja2"]
    )
    assert [item["version"] for item in result] == (
        ["3.0", "2.0", "3.0", "2.0"] if all_matches else ["3.0", "3.0"]
    )
    assert [
        str(call.args[0])
        for call in finder_factory.return_value.find_matches.call_args_list
    ] == ["click==8.1.3", "Jinja2==3.1.2"]


@pytest.mark.parametrize("prefix", ["", "# Packages\n"])
def test_requirements_utf8_bom(prefix, requirements_file, finder_factory, capsys):
    requirements_file.write_bytes(b"\xef\xbb\xbf" + f"{prefix}click==8.1.3\n".encode())
    cli(["-r", str(requirements_file)])
    finder_factory.return_value.find_matches.assert_called_once_with(
        Requirement("click==8.1.3")
    )
    assert [item["name"] for item in json.loads(capsys.readouterr().out)] == ["click"]


@pytest.mark.parametrize("option", ["no-binary", "only-binary", "prefer-binary"])
def test_requirements_binary_options(option, requirements_file, finder_factory, capsys):
    cli(["-r", str(requirements_file), f"--{option}"])
    assert finder_factory.call_args.kwargs[option.replace("-", "_")] == [
        "click",
        "Jinja2",
    ]


@pytest.mark.parametrize("file_input", [False, True])
def test_single_match_output_shape(
    file_input, requirements_file, finder_factory, capsys
):
    requirements_file.write_text("click\n", encoding="utf-8")
    cli(["-r", str(requirements_file)] if file_input else ["click"])
    result = json.loads(capsys.readouterr().out)
    assert isinstance(result, list if file_input else dict)
    assert (result[0] if file_input else result)["name"] == "click"


def test_positional_all(finder_factory, capsys):
    cli(["click", "--all"])
    assert [item["version"] for item in json.loads(capsys.readouterr().out)] == [
        "3.0",
        "2.0",
    ]


@pytest.mark.parametrize(
    "line, expected",
    [
        ("click==8.1.3 # A comment", "click==8.1.3"),
        (
            'click[extra]; os_name == "a # b" # A comment',
            'click[extra]; os_name == "a # b"',
        ),
        ("click; os_name == 'a # b'", "click; os_name == 'a # b'"),
        ('click; os_name == "a\' # b" # A comment', 'click; os_name == "a\' # b"'),
        (
            "Demo @ https://example.org/demo.whl#sha256=abc # A comment",
            "Demo @ https://example.org/demo.whl#sha256=abc",
        ),
        (
            "Demo @ https://example.org/demo's.whl#sha256=abc # A comment",
            "Demo @ https://example.org/demo's.whl#sha256=abc",
        ),
        (
            "Demo @ git+https://example.org/repo.git@main#subdirectory=src",
            "Demo @ git+https://example.org/repo.git@main#subdirectory=src",
        ),
    ],
)
def test_requirements_comments_and_references(
    line, expected, requirements_file, finder_factory, capsys
):
    requirements_file.write_text(
        "# Packages\r\n\r\n  " + line + "\r\n", encoding="utf-8"
    )
    cli(["-r", str(requirements_file)])
    actual = finder_factory.return_value.find_matches.call_args.args[0]
    assert actual == Requirement(expected)
    assert len(json.loads(capsys.readouterr().out)) == 1


@pytest.mark.parametrize("contents", ["", " \n# A comment\n\t# Another comment\n"])
@pytest.mark.parametrize("link_only", [False, True])
def test_empty_requirements(
    contents, link_only, requirements_file, finder_factory, capsys
):
    requirements_file.write_text(contents, encoding="utf-8")
    cli(["-r", str(requirements_file)] + (["--link-only"] if link_only else []))
    assert capsys.readouterr().out == ("" if link_only else "[]\n")
    finder_factory.return_value.find_matches.assert_not_called()
    finder_factory.return_value.download.assert_not_called()


@pytest.mark.parametrize(
    "line",
    [
        "-r more.txt",
        "--requirements more.txt",
        "-c constraints.txt",
        "--index-url https://example.org/simple",
        "-e ./project",
        "./project",
        "click==8.1.3 --hash=sha256:abc",
        "click==8.1.3 \\",
        "click=>8",
        "https://example.org/demo.whl",
    ],
)
def test_invalid_entry_prevents_lookup_and_download(
    line, requirements_file, finder_factory, tmp_path, capsys
):
    requirements_file.write_text("click\n\n" + line + "\n", encoding="utf-8")
    target = tmp_path / "downloads"
    with pytest.raises(SystemExit) as error:
        cli(["-r", str(requirements_file), "--download", str(target)])
    assert error.value.code == 2
    assert f"{requirements_file}:3:" in capsys.readouterr().err
    finder_factory.assert_not_called()
    assert not target.exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "invalid-utf8"])
def test_requirements_read_error(kind, tmp_path, finder_factory, capsys):
    path = tmp_path / "input"
    if kind == "directory":
        path.mkdir()
    elif kind == "invalid-utf8":
        path.write_bytes(b"click\n\xff")
    with pytest.raises(SystemExit) as error:
        cli(["-r", str(path)])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "Cannot read requirements file" in message
    assert str(path) in message
    finder_factory.assert_not_called()


@pytest.mark.parametrize("arguments", [[], ["click", "-r", "requirements.txt"]])
def test_requirements_input_choice(arguments, finder_factory, capsys):
    with pytest.raises(SystemExit) as error:
        cli(arguments)
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err
    finder_factory.assert_not_called()


@pytest.mark.parametrize("file_input", [False, True])
def test_no_matches(file_input, requirements_file, finder_factory, tmp_path, capsys):
    finder = finder_factory.return_value
    if file_input:
        first = Package("click", "8.1.3", Link("https://example.org/click.whl"))
        finder.find_matches.side_effect = [[first], []]
        arguments = ["-r", str(requirements_file)]
    else:
        finder.find_matches.side_effect = [[]]
        arguments = ["Jinja2==3.1.2"]
    target = tmp_path / "downloads"
    with pytest.raises(SystemExit) as error:
        cli([*arguments, "--download", str(target)])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    if file_input:
        assert (
            f"{requirements_file}:2: No matches are found. (Jinja2==3.1.2)"
            in output.err
        )
    else:
        assert output.err == "No matches are found.\n"
    finder.download.assert_not_called()
    assert not target.exists()


def test_requirements_link_output(requirements_file, finder_factory, capsys):
    cli(["-r", str(requirements_file), "--link-only"])
    assert capsys.readouterr().out.splitlines() == ["https://example.org/3.0"] * 2


@pytest.mark.parametrize("link_only", [False, True])
def test_requirements_download_files(
    link_only,
    requirements_file,
    tmp_path,
    fixtures_dir,
    pypi,
    pypi_session,
    monkeypatch,
    capsys,
):
    files = ["click-8.1.3-py3-none-any.whl", "first-2.0.2.tar.gz"]
    requirements_file.write_text("click==8.1.3\nfirst==2.0.2\n", encoding="utf-8")

    @pypi.route("/batch")
    def batch_links():
        return "\n".join(f'<a href="/files/{name}">{name}</a>' for name in files)

    monkeypatch.setattr(
        "unearth.__main__.PackageFinder",
        lambda **kwargs: PackageFinder(session=pypi_session, **kwargs),
    )
    target = tmp_path / "downloads"
    cli(
        [
            "-r",
            str(requirements_file),
            "--find-link",
            "https://pypi.org/batch",
            "--download",
            str(target),
            *(["--link-only"] if link_only else []),
        ]
    )
    output = capsys.readouterr().out
    if link_only:
        assert output.splitlines() == [
            value
            for name in files
            for value in [
                f"https://pypi.org/files/{name}",
                f"  ==> {(target / name).as_posix()}",
            ]
        ]
    else:
        result = json.loads(output)
        assert [item["name"] for item in result] == ["click", "first"]
        assert [item["local_path"] for item in result] == [
            (target / name).as_posix() for name in files
        ]
    assert sorted(path.name for path in target.iterdir()) == sorted(files)
    for name in files:
        assert (target / name).read_bytes() == (
            fixtures_dir / "files" / name
        ).read_bytes()
