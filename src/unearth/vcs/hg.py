from __future__ import annotations

import logging
from pathlib import Path

from unearth.utils import display_path, path_to_url
from unearth.vcs.base import HiddenText, VersionControl, vcs

logger = logging.getLogger(__package__.split(".")[0])


@vcs.register
class Mercurial(VersionControl):
    name = "hg"
    dir_name = ".hg"

    def fetch_new(
        self, dest: Path, url: HiddenText, rev: str | None, args: list[str | HiddenText]
    ) -> None:
        rev_display = f" (revision: {rev})" if rev else ""
        logger.info("Cloning hg %s%s to %s", url, rev_display, display_path(dest))
        if self.verbosity <= 0:
            flags = ("--quiet",)
        elif self.verbosity == 1:
            flags = ()
        elif self.verbosity == 2:
            flags = ("--verbose",)
        else:
            flags = ("--verbose", "--debug")
        self.run_command("clone", "--noupdate", *flags, url, dest)
        self.run_command(
            "update",
            *flags,
            *self.get_rev_args(rev),
            cwd=dest,
        )

    def update(self, dest: Path, rev: str | None, args: list[str | HiddenText]) -> None:
        self.run_command(["pull", "-q"], cwd=dest)
        cmd_args = ["update", "-q", *self.get_rev_args(rev)]
        self.run_command(cmd_args, cwd=dest)

    def get_revision(self, dest: Path) -> str:
        current_revision = self.run_command(
            ["parents", "--template={rev}"],
            log_output=False,
            stdout_only=True,
            cwd=dest,
        ).stdout.strip()
        return current_revision

    def get_remote_url(self, dest: Path) -> str:
        url = self.run_command(
            ["showconfig", "paths.default"],
            log_output=False,
            stdout_only=True,
            cwd=dest,
        ).strip()
        if self._is_local_repository(url):
            url = path_to_url(url)
        return url.strip()
