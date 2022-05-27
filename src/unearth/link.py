"""Remote or local file link."""
from __future__ import annotations

import dataclasses as dc
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, unquote, urlparse

from unearth.utils import (
    add_ssh_scheme_to_git_uri,
    parse_query,
    path_to_url,
    split_auth_from_url,
    url_to_path,
)

if sys.version_info >= (3, 8):
    from functools import cached_property
else:
    from cached_property import cached_property

VCS_SCHEMA = ("git", "hg", "svn", "bzr")
SUPPORTED_HASHES = ("sha1", "sha224", "sha384", "sha256", "sha512", "md5")


@dc.dataclass
class Link:
    """A link can refer to either a remote url or local file.

    Args:
        url (str): The url of the remote file.
        comes_from (str|None): The index page that contains this link
        yank_reason (str|None): The reason why this link is yanked
        requires_python (str|None): The data-python-requires attribute of this link
        vcs (str|None): The vcs type of this link(git/hg/svn/bzr)
    """

    url: str
    comes_from: str | None = None
    yank_reason: str | None = None
    requires_python: str | None = None
    vcs: str | None = dc.field(init=False, default=None)

    def __post_init__(self) -> None:
        vcs_prefixes = tuple(f"{schema}+" for schema in VCS_SCHEMA)
        if self.url.startswith(vcs_prefixes):
            self.vcs, _, url = self.url.partition("+")
            self.normalized = f"{self.vcs}+{add_ssh_scheme_to_git_uri(url)}"
        else:
            self.normalized = self.url

    def as_json(self) -> dict[str, Any]:
        """Return the JSON representation of link object"""
        return {
            "url": self.redacted,
            "comes_from": self.comes_from,
            "yank_reason": self.yank_reason,
            "requires_python": self.requires_python,
        }

    def _ident(self) -> tuple:
        return (self.normalized, self.yank_reason, self.requires_python)

    @cached_property
    def parsed(self) -> ParseResult:
        return urlparse(self.normalized)

    def __repr__(self) -> str:
        return f"<Link {self.redacted} (from {self.comes_from})>"

    def __hash__(self) -> int:
        return hash(self._ident())

    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, Link) and self._ident() == __o._ident()

    @classmethod
    def from_path(cls, file_path: str | Path) -> Link:
        """Create a link from a local file path"""
        url = path_to_url(str(file_path))
        return cls(url)

    @property
    def is_file(self) -> bool:
        return self.parsed.scheme == "file"

    @property
    def file_path(self) -> Path:
        return Path(url_to_path(self.url_without_fragment))

    @property
    def is_vcs(self) -> bool:
        return self.vcs is not None

    @property
    def filename(self) -> str:
        return os.path.basename(unquote(self.parsed.path))

    @property
    def is_wheel(self) -> bool:
        return self.filename.endswith(".whl")

    @cached_property
    def url_without_fragment(self) -> str:
        """Return the url without the fragment."""
        return self.parsed._replace(fragment="").geturl()

    @property
    def subdirectory(self) -> str | None:
        return self._fragment_dict.get("subdirectory")

    @property
    def _fragment_dict(self) -> dict[str, str]:
        return parse_query(self.parsed.fragment)

    @property
    def redacted(self) -> str:
        _, has_auth, host = self.parsed.netloc.rpartition("@")
        if not has_auth:
            return self.url_without_fragment
        netloc = f"***{has_auth}{host}"
        return self.parsed._replace(netloc=netloc, fragment="").geturl()

    def split_auth(self) -> tuple[tuple[str, str | None] | None, str]:
        """Split the url into ((user, password), host)"""
        return split_auth_from_url(self.normalized)

    @property
    def hash_name(self) -> str | None:
        """Return the hash name of the link if a hash is present."""
        result = next(
            (name for name in SUPPORTED_HASHES if name in self._fragment_dict), None
        )
        return result

    @property
    def hash(self) -> str | None:
        """The hash value associated with the URL"""
        if not self.hash_name:
            return None
        return self._fragment_dict.get(self.hash_name)

    @property
    def is_yanked(self) -> bool:
        return self.yank_reason is not None
