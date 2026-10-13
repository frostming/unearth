import errno
import os
from pathlib import Path

import pytest

from unearth import Link
from unearth.preparer import unpack_link

WHEEL_NAME = "click-8.1.3-py3-none-any.whl"
WHEEL_LINK = Link(f"https://pypi.org/files/{WHEEL_NAME}")


@pytest.fixture
def wheel_paths(tmp_path):
    location = tmp_path / "wheels"
    location.mkdir()
    return tmp_path / "download", location / WHEEL_NAME


@pytest.fixture
def wheel_data(fixtures_dir):
    return (fixtures_dir / "files" / WHEEL_NAME).read_bytes()


@pytest.fixture
def cross_device(mocker, wheel_paths):
    download_dir, _ = wheel_paths
    replace = os.replace

    def replace_across_filesystems(source, target):
        if Path(source) == download_dir / WHEEL_NAME:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return replace(source, target)

    mocker.patch("unearth.preparer.os.replace", side_effect=replace_across_filesystems)


@pytest.mark.parametrize("cross_filesystem", [False, True])
@pytest.mark.parametrize("existing", [False, True])
def test_unpack_remote_wheel(
    pypi_session, wheel_paths, wheel_data, request, cross_filesystem, existing
):
    download_dir, target = wheel_paths
    if cross_filesystem:
        request.getfixturevalue("cross_device")
    if existing:
        target.write_bytes(b"previous wheel")

    result = unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert result == target
    assert target.read_bytes() == wheel_data
    assert not (download_dir / WHEEL_NAME).exists()
    assert list(target.parent.iterdir()) == [target]


def test_unpack_local_wheel(pypi_session, wheel_paths, wheel_data, mocker):
    download_dir, target = wheel_paths
    download_dir.mkdir()
    source = download_dir / WHEEL_NAME
    source.write_bytes(wheel_data)
    replace = mocker.patch("unearth.preparer.os.replace")

    result = unpack_link(
        pypi_session, Link.from_path(source), download_dir, target.parent
    )

    assert result == source
    assert source.read_bytes() == wheel_data
    assert list(target.parent.iterdir()) == []
    replace.assert_not_called()


def test_unpack_wheel_already_in_destination(
    pypi_session, wheel_paths, wheel_data, mocker
):
    _, target = wheel_paths
    target.write_bytes(wheel_data)
    replace = mocker.patch("unearth.preparer.os.replace")

    result = unpack_link(pypi_session, WHEEL_LINK, target.parent, target.parent)

    assert result == target
    assert target.read_bytes() == wheel_data
    assert list(target.parent.iterdir()) == [target]
    replace.assert_not_called()


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
def test_unpack_remote_wheel_preserves_errors(
    pypi_session, wheel_paths, wheel_data, mocker, error_number
):
    download_dir, target = wheel_paths
    target.write_bytes(b"previous wheel")
    error = OSError(error_number, "Cannot replace the wheel")
    mocker.patch("unearth.preparer.os.replace", side_effect=error)

    with pytest.raises(OSError) as caught:
        unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert caught.value is error
    assert (download_dir / WHEEL_NAME).read_bytes() == wheel_data
    assert target.read_bytes() == b"previous wheel"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.usefixtures("cross_device")
@pytest.mark.parametrize("existing", [False, True])
def test_unpack_cross_device_wheel_copy_failure(
    pypi_session, wheel_paths, wheel_data, mocker, existing
):
    download_dir, target = wheel_paths
    if existing:
        target.write_bytes(b"previous wheel")
    error = OSError(errno.ENOSPC, "No space left on device")

    def fail_copy(source, destination):
        Path(destination).write_bytes(b"partial copy")
        raise error

    mocker.patch("unearth.preparer.shutil.copy2", side_effect=fail_copy)

    with pytest.raises(OSError) as caught:
        unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert caught.value is error
    assert (download_dir / WHEEL_NAME).read_bytes() == wheel_data
    if existing:
        assert target.read_bytes() == b"previous wheel"
    assert list(target.parent.iterdir()) == ([target] if existing else [])


def test_unpack_cross_device_wheel_replace_failure(
    pypi_session, wheel_paths, wheel_data, mocker
):
    download_dir, target = wheel_paths
    target.write_bytes(b"previous wheel")
    error = OSError(errno.EACCES, "Cannot replace the wheel")

    def fail_replace(source, destination):
        if Path(source) == download_dir / WHEEL_NAME:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        raise error

    mocker.patch("unearth.preparer.os.replace", side_effect=fail_replace)

    with pytest.raises(OSError) as caught:
        unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert caught.value is error
    assert (download_dir / WHEEL_NAME).read_bytes() == wheel_data
    assert target.read_bytes() == b"previous wheel"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.usefixtures("cross_device")
def test_unpack_cross_device_wheel_destination_is_directory(
    pypi_session, wheel_paths, wheel_data
):
    download_dir, target = wheel_paths
    target.mkdir()

    with pytest.raises(OSError):
        unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert list(target.parent.iterdir()) == [target]
    assert (download_dir / WHEEL_NAME).read_bytes() == wheel_data


@pytest.mark.usefixtures("cross_device")
def test_unpack_cross_device_wheel_destination_is_symlink(
    pypi_session, wheel_paths, wheel_data, tmp_path
):
    download_dir, target = wheel_paths
    original = tmp_path / "original.whl"
    original.write_bytes(b"previous wheel")
    try:
        target.symlink_to(original)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314:
            pytest.skip("Symbolic link creation is not permitted")
        raise

    result = unpack_link(pypi_session, WHEEL_LINK, download_dir, target.parent)

    assert result == target
    assert not target.is_symlink()
    assert target.read_bytes() == wheel_data
    assert original.read_bytes() == b"previous wheel"
    assert list(target.parent.iterdir()) == [target]
    assert not (download_dir / WHEEL_NAME).exists()
