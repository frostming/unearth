"""Unpack the link to an installed wheel or source."""

from __future__ import annotations

import errno
import functools
import hashlib
import logging
import mimetypes
import os
import shutil
import stat
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from unearth.errors import HashMismatchError, UnpackError
from unearth.fetchers import Fetcher
from unearth.link import Link
from unearth.utils import (
    BZ2_EXTENSIONS,
    TAR_EXTENSIONS,
    XZ_EXTENSIONS,
    ZIP_EXTENSIONS,
    display_path,
    format_size,
    iter_with_callback,
)
from unearth.vcs import vcs_support

HTTPErrors: tuple[type[Exception], ...] = (httpx.HTTPError,)
try:
    from requests import HTTPError

    HTTPErrors += (HTTPError,)
except ModuleNotFoundError:
    pass

if TYPE_CHECKING:
    from typing import Protocol

    class DownloadReporter(Protocol):
        def __call__(self, link: Link, completed: int, total: int | None) -> None: ...

    class UnpackReporter(Protocol):
        def __call__(
            self, filename: Path, completed: int, total: int | None
        ) -> None: ...


def noop_download_reporter(link: Link, completed: int, total: int | None) -> None:
    pass


def noop_unpack_reporter(filename: Path, completed: int, total: int | None) -> None:
    pass


READ_CHUNK_SIZE = 8192
logger = logging.getLogger(__name__)

# On Windows, os.open does not support the dir_fd parameter, so we cannot
# use the atomic O_NOFOLLOW + dirfd approach.  Fall back to safe_makedirs
# (create-then-verify) which still has a TOCTOU window but is the best we
# can do on that platform.
_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd


def set_extracted_file_to_default_mode_plus_executable(path: str) -> None:
    """
    Make file present at path have execute for user/group/world
    (chmod +x) is no-op on windows per python docs
    """
    os.chmod(path, (0o777 & ~os.umask(0) | 0o111))


def zip_item_is_executable(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    # if mode and regular file and any execute permissions for
    # user/group/world?
    return bool(mode and stat.S_ISREG(mode) and mode & 0o111)


def is_within_directory(directory: str | Path, path: str | Path) -> bool:
    try:
        Path(os.path.realpath(path)).relative_to(os.path.realpath(directory))
    except ValueError:
        return False
    return True


def safe_makedirs(dest_dir: str | Path, location: str | Path) -> None:
    """Create directory, then verify the resolved path is still within location.

    The post-creation check is necessary because ``is_within_directory`` uses
    ``os.path.realpath``, which cannot resolve symlinks along a path that does
    not yet exist.  A malicious archive can first extract a symlink pointing
    outside ``location`` and then reference a path through that symlink.  By
    re-checking *after* ``os.makedirs`` has materialised the directory (and
    any intermediate symlinks have landed on disk), we catch traversals that
    the pre-creation check misses.

    .. note::

        This function retains a TOCTOU window: an attacker can swap a path
        component between ``makedirs`` and the containment check.  It is
        retained as a fallback for platforms (Windows) that do not support
        ``O_NOFOLLOW`` / ``dir_fd``.  On POSIX systems, prefer
        :func:`makedirs_nofollow` and :func:`open_file_nofollow`.
    """
    os.makedirs(dest_dir, exist_ok=True)
    if not is_within_directory(location, dest_dir):
        raise UnpackError(
            f"Path traversal detected: {dest_dir!r} resolves outside "
            f"target directory ({location!r})"
        )


# ---------------------------------------------------------------------------
# Atomic no-follow helpers (POSIX only)
# ---------------------------------------------------------------------------


def _open_dir_nofollow(parent_fd: int, name: str) -> int:
    """Open or create a single directory component without following symlinks.

    Returns an open file descriptor for the directory.
    Raises UnpackError if the component is a symlink.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    # Try to open existing directory first
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
        # Verify it's really a directory, not a symlink that slipped through
        if stat.S_ISLNK(os.lstat(name, dir_fd=parent_fd).st_mode):
            os.close(fd)
            raise UnpackError(f"Symlink in extraction path component: {name!r}")
        return fd
    except FileNotFoundError:
        pass
    # Create it
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except FileExistsError:
        pass  # race: another process created it, that's fine
    fd = os.open(name, flags, dir_fd=parent_fd)
    # Double-check: must not be a symlink
    if stat.S_ISLNK(os.lstat(name, dir_fd=parent_fd).st_mode):
        os.close(fd)
        raise UnpackError(f"Symlink in extraction path component: {name!r}")
    return fd


def makedirs_nofollow(base_fd: int, rel_path: str) -> int:
    """Create directories for *rel_path* under *base_fd* without following symlinks.

    Returns an open fd for the deepest directory created.
    Caller is responsible for closing the returned fd.
    """
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p and p != "."]
    current_fd = base_fd
    owned_fds = []
    try:
        for part in parts:
            next_fd = _open_dir_nofollow(current_fd, part)
            if current_fd != base_fd:
                owned_fds.append(current_fd)
            current_fd = next_fd
        # Transfer ownership: close intermediate fds, return deepest
        for fd in owned_fds:
            os.close(fd)
        return current_fd
    except Exception:
        if current_fd != base_fd:
            try:
                os.close(current_fd)
            except OSError:
                pass
        for fd in owned_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def open_file_nofollow(dir_fd: int, filename: str) -> int:
    """Open a file for writing without following symlinks.

    Raises UnpackError if *filename* is a symlink.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(filename, flags, 0o666, dir_fd=dir_fd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise UnpackError(f"Symlink detected at file path: {filename!r}") from e
        raise


def split_leading_dir(path: str) -> list[str]:
    path = path.lstrip("/").lstrip("\\")
    if "/" in path and (
        ("\\" in path and path.find("/") < path.find("\\")) or "\\" not in path
    ):
        return path.split("/", 1)
    elif "\\" in path:
        return path.split("\\", 1)
    else:
        return [path, ""]


def has_leading_dir(paths: Iterable[str]) -> bool:
    """Returns true if all the paths have the same leading path name
    (i.e., everything is in one subdirectory in an archive)"""
    common_prefix = None
    for path in paths:
        prefix, _ = split_leading_dir(path)
        if not prefix:
            return False
        elif common_prefix is None:
            common_prefix = prefix
        elif prefix != common_prefix:
            return False
    return True


class HashValidator:
    """Validate the hashes of a file."""

    def __init__(self, package_link: Link, hashes: dict[str, list[str]] | None) -> None:
        if hashes is not None:
            # Always sort the hash values for better comparison.
            hashes = {k: sorted(value) for k, value in hashes.items()}
        self.allowed = hashes
        self.package_link = package_link
        self.got = {}
        if hashes is not None:
            for name in hashes:
                try:
                    self.got[name] = hashlib.new(name)
                except (TypeError, ValueError):
                    raise UnpackError(f"Unknown hash name: {name!r}") from None

    def update(self, chunk: bytes) -> None:
        for hasher in self.got.values():
            hasher.update(chunk)

    def validate(self) -> None:
        if not self.allowed:
            return
        gots: dict[str, str] = {}
        for name, hash_list in self.allowed.items():
            got = self.got[name].hexdigest()
            if got in hash_list:
                return
            gots[name] = got
        raise HashMismatchError(self.package_link, self.allowed, gots)

    def validate_path(self, path: Path) -> None:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(READ_CHUNK_SIZE), b""):
                self.update(chunk)
        self.validate()


def _check_downloaded(path: Path, hashes: dict[str, list[str]] | None) -> bool:
    """Check if the file has been downloaded."""
    if not path.is_file():
        return False
    try:
        HashValidator(Link.from_path(path), hashes).validate_path(path)
    except HashMismatchError:
        logger.debug("File exists at %s, but the hashes don't match", path)
        path.unlink()
        return False
    logger.debug("The file is already downloaded: %s", path)
    return True


def unpack_archive(
    archive: Path, dest: Path, reporter: UnpackReporter = noop_unpack_reporter
) -> None:
    content_type = mimetypes.guess_type(str(archive))[0]
    if (
        content_type == "application/zip"
        or zipfile.is_zipfile(archive)
        or archive.suffix.lower() in ZIP_EXTENSIONS
    ):
        _unzip_archive(archive, dest, reporter=reporter)
    elif (
        content_type == "application/x-gzip"
        or tarfile.is_tarfile(archive)
        or archive.suffix.lower() in (TAR_EXTENSIONS + XZ_EXTENSIONS + BZ2_EXTENSIONS)
    ):
        _untar_archive(archive, dest, reporter=reporter)
    else:
        raise UnpackError(f"Unknown archive type: {archive.name}")


def _unzip_archive(filename: Path, location: Path, reporter: UnpackReporter) -> None:
    os.makedirs(location, exist_ok=True)
    if _SUPPORTS_DIR_FD:
        _unzip_archive_nofollow(filename, location, reporter)
    else:
        _unzip_archive_safe(filename, location, reporter)


def _unzip_archive_nofollow(
    filename: Path, location: Path, reporter: UnpackReporter
) -> None:
    """Unzip using O_NOFOLLOW + dirfd to eliminate TOCTOU race (POSIX)."""
    base_fd = os.open(str(location), os.O_RDONLY | os.O_DIRECTORY)
    try:
        with zipfile.ZipFile(filename, allowZip64=True) as zip:
            leading = has_leading_dir(zip.namelist())
            callback = functools.partial(reporter, filename, total=len(zip.infolist()))
            for info in iter_with_callback(zip.infolist(), callback):
                name = info.filename
                fn = name
                if leading:
                    fn = split_leading_dir(name)[1]
                # Normalise: strip leading slashes/dots, reject absolute paths
                fn = fn.lstrip("/").lstrip("\\")
                if not fn or fn.startswith(".."):
                    continue
                rel_dir = os.path.dirname(fn)
                rel_file = os.path.basename(fn)
                if fn.endswith(("/", "\\")):
                    # Directory entry
                    dir_fd = makedirs_nofollow(base_fd, fn.rstrip("/\\"))
                    os.close(dir_fd)
                else:
                    dir_fd = makedirs_nofollow(base_fd, rel_dir) if rel_dir else base_fd
                    try:
                        file_fd = open_file_nofollow(dir_fd, rel_file)
                        try:
                            with (
                                zip.open(name) as fp,
                                os.fdopen(file_fd, "wb") as destfp,
                            ):
                                shutil.copyfileobj(fp, destfp)
                            file_fd = -1  # fdopen took ownership
                        except Exception:
                            if file_fd >= 0:
                                os.close(file_fd)
                            raise
                        if zip_item_is_executable(info):
                            set_extracted_file_to_default_mode_plus_executable(
                                os.path.join(str(location), fn)
                            )
                    finally:
                        if dir_fd != base_fd:
                            os.close(dir_fd)
    finally:
        os.close(base_fd)


def _unzip_archive_safe(
    filename: Path, location: Path, reporter: UnpackReporter
) -> None:
    """Unzip using safe_makedirs fallback (Windows — TOCTOU window remains)."""
    with zipfile.ZipFile(filename, allowZip64=True) as zip:
        leading = has_leading_dir(zip.namelist())
        callback = functools.partial(reporter, filename, total=len(zip.infolist()))
        for info in iter_with_callback(zip.infolist(), callback):
            name = info.filename
            fn = name
            if leading:
                fn = split_leading_dir(name)[1]
            fn = os.path.join(location, fn)
            dir = os.path.dirname(fn)
            if not is_within_directory(location, fn):
                message = (
                    f"The zip file ({filename}) has a file ({fn}) trying to install "
                    f"outside target directory ({location})"
                )
                raise UnpackError(message)
            if fn.endswith(("/", "\\")):
                # A directory
                safe_makedirs(fn, location)
            else:
                safe_makedirs(dir, location)
                # Don't use read() to avoid allocating an arbitrarily large
                # chunk of memory for the file's content
                with zip.open(name) as fp, open(fn, "wb") as destfp:
                    shutil.copyfileobj(fp, destfp)

                if zip_item_is_executable(info):
                    set_extracted_file_to_default_mode_plus_executable(fn)


def _untar_archive(filename: Path, location: Path, reporter: UnpackReporter) -> None:
    """Untar the file (with path `filename`) to the destination `location`."""
    os.makedirs(location, exist_ok=True)
    if _SUPPORTS_DIR_FD:
        _untar_archive_nofollow(filename, location, reporter)
    else:
        _untar_archive_safe(filename, location, reporter)


def _untar_archive_nofollow(
    filename: Path, location: Path, reporter: UnpackReporter
) -> None:
    """Untar using O_NOFOLLOW + dirfd to eliminate TOCTOU race (POSIX)."""
    lower_fn = str(filename).lower()
    if lower_fn.endswith((".gz", ".tgz")):
        mode = "r:gz"
    elif lower_fn.endswith(BZ2_EXTENSIONS):
        mode = "r:bz2"
    elif lower_fn.endswith(XZ_EXTENSIONS):
        mode = "r:xz"
    elif lower_fn.endswith(".tar"):
        mode = "r"
    else:
        logger.warning(
            "Cannot determine compression type for file %s",
            filename,
        )
        mode = "r:*"
    base_fd = os.open(str(location), os.O_RDONLY | os.O_DIRECTORY)
    try:
        with tarfile.open(filename, mode, encoding="utf-8") as tar:  # type: ignore[call-overload]
            leading = has_leading_dir([member.name for member in tar.getmembers()])
            callback = functools.partial(
                reporter, filename, total=len(tar.getmembers())
            )
            for member in iter_with_callback(tar.getmembers(), callback):
                fn = member.name
                if leading:
                    fn = split_leading_dir(fn)[1]
                # Normalise: strip leading slashes/dots, reject absolute paths
                fn = fn.lstrip("/").lstrip("\\")
                if not fn or fn.startswith(".."):
                    continue
                rel_dir = os.path.dirname(fn)
                rel_file = os.path.basename(fn)

                if member.isdir():
                    dir_fd = makedirs_nofollow(base_fd, fn.rstrip("/\\"))
                    os.close(dir_fd)
                elif member.issym():
                    # Skip symlinks entirely — they are the primary traversal
                    # vector and O_NOFOLLOW would reject them anyway.
                    logger.warning(
                        "In the tar file %s the member %s is a symlink, skipping",
                        filename,
                        member.name,
                    )
                    continue
                else:
                    dir_fd = makedirs_nofollow(base_fd, rel_dir) if rel_dir else base_fd
                    try:
                        try:
                            fp = tar.extractfile(member)
                        except (KeyError, AttributeError) as exc:
                            # Some corrupt tar files seem to produce this
                            # (specifically bad symlinks)
                            logger.warning(
                                "In the tar file %s the member %s is invalid: %s",
                                filename,
                                member.name,
                                exc,
                            )
                            continue
                        assert fp is not None
                        file_fd = open_file_nofollow(dir_fd, rel_file)
                        try:
                            with os.fdopen(file_fd, "wb") as destfp:
                                shutil.copyfileobj(fp, destfp)
                            file_fd = -1  # fdopen took ownership
                        except Exception:
                            if file_fd >= 0:
                                os.close(file_fd)
                            raise
                        fp.close()
                        # Update the timestamp (useful for cython compiled files)
                        tar.utime(member, os.path.join(str(location), fn))
                        # member have any execute permissions for
                        # user/group/world?
                        if member.mode & 0o111:
                            set_extracted_file_to_default_mode_plus_executable(
                                os.path.join(str(location), fn)
                            )
                    finally:
                        if dir_fd != base_fd:
                            os.close(dir_fd)
    finally:
        os.close(base_fd)


def _untar_archive_safe(
    filename: Path, location: Path, reporter: UnpackReporter
) -> None:
    """Untar using safe_makedirs fallback (Windows — TOCTOU window remains)."""
    lower_fn = str(filename).lower()
    if lower_fn.endswith((".gz", ".tgz")):
        mode = "r:gz"
    elif lower_fn.endswith(BZ2_EXTENSIONS):
        mode = "r:bz2"
    elif lower_fn.endswith(XZ_EXTENSIONS):
        mode = "r:xz"
    elif lower_fn.endswith(".tar"):
        mode = "r"
    else:
        logger.warning(
            "Cannot determine compression type for file %s",
            filename,
        )
        mode = "r:*"
    with tarfile.open(filename, mode, encoding="utf-8") as tar:  # type: ignore[call-overload]
        leading = has_leading_dir([member.name for member in tar.getmembers()])
        callback = functools.partial(reporter, filename, total=len(tar.getmembers()))
        for member in iter_with_callback(tar.getmembers(), callback):
            fn = member.name
            if leading:
                fn = split_leading_dir(fn)[1]
            path = os.path.join(location, fn)
            if not is_within_directory(location, path):
                message = (
                    f"The tar file ({filename}) has a file ({path}) trying to install "
                    f"outside target directory ({location})"
                )
                raise UnpackError(message)
            if member.isdir():
                safe_makedirs(path, location)
            elif member.issym():
                if os.path.isabs(member.linkname):
                    link_target = member.linkname
                else:
                    link_target = os.path.join(os.path.dirname(path), member.linkname)
                if not is_within_directory(location, link_target):
                    logger.warning(
                        "In the tar file %s the member %s -> %s points outside %s, skipping",
                        filename,
                        member.name,
                        member.linkname,
                        location,
                    )
                    continue
                try:
                    tar._extract_member(member, path)
                except Exception as exc:  # noqa: BLE001
                    # Some corrupt tar files seem to produce this
                    # (specifically bad symlinks)
                    logger.warning(
                        "In the tar file %s the member %s is invalid: %s",
                        filename,
                        member.name,
                        exc,
                    )
                    continue
            else:
                try:
                    fp = tar.extractfile(member)
                except (KeyError, AttributeError) as exc:
                    # Some corrupt tar files seem to produce this
                    # (specifically bad symlinks)
                    logger.warning(
                        "In the tar file %s the member %s is invalid: %s",
                        filename,
                        member.name,
                        exc,
                    )
                    continue
                safe_makedirs(os.path.dirname(path), location)
                assert fp is not None
                with open(path, "wb") as destfp:
                    shutil.copyfileobj(fp, destfp)
                fp.close()
                # Update the timestamp (useful for cython compiled files)
                tar.utime(member, path)
                # member have any execute permissions for user/group/world?
                if member.mode & 0o111:
                    set_extracted_file_to_default_mode_plus_executable(path)


def unpack_link(
    session: Fetcher,
    link: Link,
    download_dir: Path,
    location: Path,
    hashes: dict[str, list[str]] | None = None,
    verbosity: int = 0,
    download_reporter: DownloadReporter = noop_download_reporter,
    unpack_reporter: UnpackReporter = noop_unpack_reporter,
) -> Path:
    """Unpack link into location.

    The link can be a VCS link or a file link.

    Args:
        session (Fetcher): the requests session
        link (Link): the link to unpack
        download_dir (Path): the directory to download the file to
        location (Path): the destination directory
        hashes (dict[str, list[str]]|None): Optional hash dict for validation
        progress_bar (bool): whether to show the progress bar

    Returns:
        Path: the path to the unpacked file or directory
    """
    location.parent.mkdir(parents=True, exist_ok=True)
    if link.is_vcs:
        backend = vcs_support.get_backend(cast(str, link.vcs), verbosity=verbosity)
        download_reporter(link, 0, 1)
        backend.fetch(link, location)
        download_reporter(link, 1, 1)
        return location

    validator = HashValidator(link, hashes)
    if link.is_file:
        if link.file_path.is_dir():
            logger.info(
                "The file %s is a local directory, use it directly",
                display_path(link.file_path),
            )
            return link.file_path
        artifact = link.file_path
        validator.validate_path(artifact)
    else:
        # A remote artfiact link, check the download dir first
        artifact = download_dir / link.filename
        if not _check_downloaded(artifact, hashes):
            with session.get_stream(link.normalized) as resp:
                try:
                    resp.raise_for_status()
                except HTTPErrors as e:
                    raise UnpackError(f"Download failed: {e}") from None
                try:
                    total = int(resp.headers["Content-Length"])
                except (KeyError, ValueError, TypeError):
                    total = None
                if getattr(resp, "from_cache", False):
                    logger.info("Using cached %s", link)
                else:
                    size = format_size(resp.headers.get("Content-Length", ""))
                    logger.info("Downloading %s (%s)", link, size)
                with artifact.open("wb") as f:
                    callback = functools.partial(download_reporter, link, total=total)
                    for chunk in iter_with_callback(
                        resp.iter_bytes(chunk_size=READ_CHUNK_SIZE),
                        callback,
                        stepper=len,
                    ):
                        if chunk:
                            validator.update(chunk)
                            f.write(chunk)
            validator.validate()
    if link.is_wheel:
        if link.is_file:
            # Use the local file directly
            return artifact
        target_file = location / link.filename
        if target_file != artifact:
            # For wheels downloaded from remote locations, move it to the destination.
            os.replace(artifact, target_file)
        return target_file

    unpack_archive(artifact, location, reporter=unpack_reporter)
    return location
