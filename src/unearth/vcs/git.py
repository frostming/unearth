from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from unearth.errors import UnpackError
from unearth.link import Link
from unearth.utils import add_ssh_scheme_to_git_uri, display_path, path_to_url
from unearth.vcs.base import HiddenText, VersionControl, vcs

logger = logging.getLogger(__package__.split(".")[0])


@vcs.register
class Git(VersionControl):
    name = "git"
    dir_name = ".git"

    def get_git_version(self) -> tuple[int, ...]:
        result = self.run_command(["version"], stdout_only=True, log_output=False)
        output = result.stdout.strip()
        match = re.match(r"git version (\d+)\.(\d+)(?:\.(\d+))?", output)
        if not match:
            raise UnpackError(f"Failed to get git version: {output}")
        return tuple(int(part) for part in match.groups())

    def fetch_new(
        self, dest: Path, url: HiddenText, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        rev_display = f" (revision: {rev})" if rev else ""
        logger.info("Cloning %s%s to %s", url, rev_display, display_path(dest))
        if self.verbosity <= 0:
            flags = ("--quiet",)
        elif self.verbosity == 1:
            flags = ()
        else:
            flags = ("--verbose", "--progress")
        if self.get_git_version() >= (2, 17):
            # Git added support for partial clone in 2.17
            # https://git-scm.com/docs/partial-clone
            # Speeds up cloning by functioning without a complete copy of repository
            self.run_command(
                ["clone", "--filter=blob:none", *flags, url, str(dest)],
            )
        else:
            self.run_command(["clone", *flags, url, str(dest)])

        if rev is not None:
            self.run_command(["checkout", "-q", rev], cwd=dest)
        revision = self.get_revision(dest)
        logger.info("Resolved %s to commit %s", url, revision)
        self._update_submodules(dest)

    def _update_submodules(self, dest: Path) -> None:
        if not dest.joinpath(".gitmodules").exists():
            return
        self.run_command(
            ["submodule", "update", "--init", "-q", "--recursive"], cwd=dest
        )

    def update(self, dest: Path, rev: str | None, args: list[str | HiddenText]) -> None:
        self.run_command(["fetch", "-q", "--tags"], cwd=dest)
        if rev is None:
            rev = "HEAD"
        try:
            # try as if the rev is a branch name or HEAD
            resolved = self._resolve_revision(dest, f"origin/{rev}")
        except UnpackError:
            resolved = self._resolve_revision(dest, rev)
        logger.info("Updating %s to commit %s", display_path(dest), resolved)
        self.run_command(["reset", "--hard", "-q", resolved], cwd=dest)

    def get_remote_url(self, dest: Path) -> str:
        result = self.run_command(
            ["config", "--get-regexp", r"remote\..*\.url"],
            extra_ok_returncodes=(1,),
            cwd=dest,
            stdout_only=True,
            log_output=False,
        )
        remotes = result.stdout.splitlines()
        try:
            found_remote = remotes[0]
        except IndexError:
            raise UnpackError(f"Remote not found for {display_path(dest)}")

        for remote in remotes:
            if remote.startswith("remote.origin.url "):
                found_remote = remote
                break
        url = found_remote.split(" ")[1]
        return self._git_remote_to_pip_url(url.strip())

    def _git_remote_to_pip_url(self, url: str) -> str:
        if "://" in url:
            return url
        if os.path.exists(url):
            return path_to_url(os.path.abspath(url))
        else:
            return add_ssh_scheme_to_git_uri(url)

    def _resolve_revision(self, dest: Path, rev: str | None) -> str:
        if rev is None:
            rev = "HEAD"
        result = self.run_command(
            ["rev-parse", rev],
            cwd=dest,
            stdout_only=True,
            log_output=False,
        )
        return result.stdout.strip()

    def get_revision(self, dest: Path) -> str:
        return self._resolve_revision()

    def is_commit_hash_equal(self, dest: Path, rev: str | None) -> bool:
        return rev is not None and self.get_revision(dest) == rev

    def is_immutable_revision(self, dest: Path, link: Link) -> bool:
        _, rev, _ = self.get_url_and_rev_options(link)
        if rev is None:
            return False
        return self.is_commit_hash_equal(dest, rev)