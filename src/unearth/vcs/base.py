from __future__ import annotations

import abc
import dataclasses as dc
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Collection, Type, TypeVar

from unearth.errors import UnpackError, URLError, VCSBackendError
from unearth.link import Link
from unearth.utils import compare_urls

logger = logging.getLogger(__package__.split(".")[0])


class HiddenText:
    """A string that redacts the auth info from the URL."""

    def __init__(self, secret: str, redacted: str) -> None:
        self.secret = secret
        self.redacted = redacted

    def __str__(self) -> str:
        return self.redacted

    def __repr__(self) -> str:
        return f"<URL {str(self)!r}>"


@dc.dataclass
class RevOptions:
    rev: str | None
    extra_args: list[str] = dc.field(default_factory=list)


class VersionControl(abc.ABC):
    """The base class for all version control systems.

    Attributes:
        name: the backend name
        dir_name: the backend data directory, such as '.git'
        action: the word to describe the clone action.
    """

    name: str
    dir_name: str

    def __init__(self, verbosity: int = 0) -> None:
        self.verbosity = verbosity

    def run_command(
        self,
        cmd: list[str | HiddenText],
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        log_output: bool = True,
        stdout_only: bool = False,
        extra_ok_returncodes: Collection[int] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Run the command in the given working directory."""
        env = None
        if extra_env:
            env = dict(os.environ, **extra_env)
        try:
            cmd = [self.name] + cmd
            display_cmd = subprocess.list2cmdline(map(str, cmd))
            logger.debug("Running command %s", display_cmd)
            result = subprocess.run(
                [v.secret if isinstance(v, HiddenText) else v for v in cmd],
                cwd=str(cwd) if cwd else None,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL if stdout_only else subprocess.STDOUT,
                env=env,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if e.returncode in extra_ok_returncodes:
                if log_output:
                    logger.debug(e.stdout.rstrip())
                return subprocess.CompletedProcess(e.args, e.returncode, e.stdout)
            raise UnpackError(e.output) from None
        else:
            if log_output:
                logger.debug(result.stdout.rstrip())
            return result

    def _is_local_repository(self, repo: str) -> bool:
        """
        posix absolute paths start with os.path.sep,
        win32 ones start with drive (like c:\\folder)
        """
        drive, _ = os.path.splitdrive(repo)
        return repo.startswith(os.path.sep) or bool(drive)

    def get_url_and_rev_options(
        self, link: Link
    ) -> tuple[HiddenText, str | None, list[str | HiddenText]]:
        """Get the URL and revision options from the link."""
        parsed = link.parsed
        scheme = parsed.scheme.rsplit("+", 1)[-1]
        netloc, user, password = self.get_netloc_and_auth(parsed.netloc, scheme)
        if password is not None:
            password = HiddenText(password, "***")
        replace_dict = {
            "scheme": parsed.scheme.rsplit("+", 1)[-1],
            "netloc": netloc,
            "fragment": None,
        }
        if "@" not in parsed.path:
            rev = None
        else:
            path, _, rev = parsed.path.rpartition("@")
            if not rev:
                raise URLError(
                    f"The url {link.redacted!r} has an empty revision (after @)."
                    "You should specify a revision or remove the @ from the URL."
                )
            replace_dict["path"] = path
        args = self.make_auth_args(user, password)
        url = parsed._replace(**replace_dict).geturl()
        hidden_url = HiddenText(url, Link(url).redacted)
        return hidden_url, rev, args

    def fetch(self, link: Link, dest: Path) -> None:
        """Clone the repository to the destination directory, and return
        the path to the local repository.

        Args:
            link (Link): the VCS link to the repository
            dest (Path): the destination directory
        """
        url, rev, args = self.get_url_and_rev_options(link)
        if not dest.exists():
            return self.fetch_new(dest, url, rev, args)

        if not self.is_repository_dir(dest) or not compare_urls(
            url.secret, self.get_remote_url(dest)
        ):
            if not self.is_repository_dir(dest):
                logger.debug(f"{dest} is not a repository directory, removing it.")
            else:
                remote_url = self.get_remote_url(dest)
                logger.debug(
                    f"{dest} is a repository directory, but the remote url "
                    f"{remote_url!r} does not match the url {url!r}."
                )
            shutil.rmtree(dest)
            return self.fetch_new(dest, url, rev, args)

        if self.is_commit_hash_equal(dest, rev):
            logger.debug("Repository %s is already up-to-date", dest)
            return
        self.update(dest, rev, args)

    @abc.abstractmethod
    def fetch_new(
        self, dest: Path, url: HiddenText, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        """Fetch the repository from the remote link, as if it is the first time.

        Args:
            dest (Path): the destination directory
            link (Link): the VCS link to the repository
            rev (str|None): the revision to checkout
            args (list[str | HiddenText]): the arguments to pass to the update command
        """
        pass

    @abc.abstractmethod
    def update(self, dest: Path, rev: str | None, args: list[str | HiddenText]) -> None:
        """Update the repository to the given revision.

        Args:
            dest (Path): the destination directory
            rev (str|None): the revision to checkout
            args (list[str | HiddenText]): the arguments to pass to the update command
        """
        pass

    @abc.abstractmethod
    def get_remote_url(self, dest: Path) -> str:
        """Get the remote URL of the repository."""
        return ""

    @abc.abstractmethod
    def get_revision(self, dest: Path) -> str:
        """Get the commit hash of the repository."""
        pass

    def is_immutable_revision(self, dest: Path, link: Link) -> bool:
        """Check if the revision is immutable.
        Always return False if the backend doesn't support immutable revisions.
        """
        return False

    def get_rev_args(self, rev: str | None) -> list[str]:
        """Get the revision arguments for the command."""
        return [rev] if rev is not None else []

    def is_commit_hash_equal(self, dest: Path, rev: str | None) -> bool:
        """Always assume the versions don't match"""
        return False

    def is_repository_dir(self, dest: Path) -> bool:
        """Check if the given directory is a repository directory."""
        return dest.joinpath(self.dir_name).exists()

    def get_netloc_and_auth(
        self, netloc: str, scheme: str
    ) -> tuple[str, str | None, str | None]:
        """Get the auth info and the URL from the link.
        For VCS like git, the auth info must stay in the URL.
        """
        return netloc, None, None

    def make_auth_args(
        self, user: str | None, password: HiddenText | None
    ) -> list[str | HiddenText]:
        """Make the auth args for the URL."""
        return []


_V = TypeVar("_V", bound=Type[VersionControl])


class VcsSupport:
    def __init__(self) -> None:
        self._registry: dict[str, Type[VersionControl]] = {}

    def register(self, vcs: _V) -> _V:
        self._registry[vcs.name] = vcs
        return vcs

    def unregister_all(self) -> None:
        self._registry.clear()

    def get_backend(self, name: str, verbosity: int = 0) -> VersionControl:
        try:
            return self._registry[name](verbosity=verbosity)
        except KeyError:
            raise VCSBackendError(name)


vcs = VcsSupport()
