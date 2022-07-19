"""Evaluate the links based on the given environment."""
from __future__ import annotations

import dataclasses as dc
import hashlib
import logging
import sys
from typing import Any, cast
from urllib.parse import urlencode

import packaging.requirements
from packaging.specifiers import SpecifierSet
from packaging.tags import Tag
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion
from requests import Session

from unearth.link import Link
from unearth.pep425tags import get_supported
from unearth.utils import ARCHIVE_EXTENSIONS, splitext, strip_extras

logger = logging.getLogger(__package__)


def is_equality_specifier(specifier: SpecifierSet) -> bool:
    return any(s.operator in ("==", "===") for s in specifier)


def parse_version_from_egg_info(egg_info: str, canonical_name: str) -> str | None:
    for i, c in enumerate(egg_info):
        if canonicalize_name(egg_info[:i]) == canonical_name and c in {"-", "_"}:
            return egg_info[i + 1 :]
    return None


class LinkMismatchError(ValueError):
    pass


@dc.dataclass
class TargetPython:
    """Target Python to get the candidates.

    Attributes:
        py_ver: Python version tuple, e.g. ``(3, 9)``.
        platforms: List of platforms, e.g. ``['linux_x86_64']``.
        impl: Implementation, e.g. ``'cp'``.
        abis: List of ABIs, e.g. ``['cp39']``.
    """

    py_ver: tuple[int, ...] | None = None
    abis: list[str] | None = None
    impl: str | None = None
    platforms: list[str] | None = None

    def __post_init__(self):
        self._valid_tags: list[Tag] | None = None

    def supported_tags(self) -> list[Tag]:
        if self._valid_tags is None:
            if self.py_ver is None:
                py_version = None
            else:
                py_version = "".join(map(str, self.py_ver[:2]))
            self._valid_tags = get_supported(
                py_version, self.platforms, self.impl, self.abis
            )
        return self._valid_tags


@dc.dataclass(frozen=True)
class Package:
    """A package instance has a name, version, and link that can be downloaded
    or unpacked.

    Attributes:
        name: The name of the package.
        version: The version of the package, or ``None`` if the requirement is a link.
        link: The link to the package.
    """

    name: str
    version: str | None
    link: Link = dc.field(repr=False)

    def as_json(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the package."""
        return {
            "name": self.name,
            "version": self.version,
            "link": self.link.as_json(),
        }


@dc.dataclass(frozen=True)
class FormatControl:
    only_binary: bool = False
    no_binary: bool = False

    def __post_init__(self):
        if self.only_binary and self.no_binary:
            raise ValueError(
                "Not allowed to set only_binary and no_binary at the same time."
            )

    def check_format(self, link: Link, project_name: str) -> None:
        if self.only_binary:
            if not link.is_wheel:
                raise LinkMismatchError(f"only binaries are allowed for {project_name}")
        if self.no_binary:
            if link.is_wheel:
                raise LinkMismatchError(f"no binary is allowed for {project_name}")
        return


@dc.dataclass
class Evaluator:
    """Evaluate the links based on the given environment.

    Args:
        package_name (str): The links must match the package name
        target_python (TargetPython): The links must match the target Python
        hashes (dict[str, list[str]): The links must have the correct hashes
        ignore_compatibility (bool): Whether to ignore the compatibility check
        allow_yanked (bool): Whether to allow yanked candidates
        format_control (bool): Format control flags
    """

    package_name: str
    session: Session
    target_python: TargetPython = dc.field(default_factory=TargetPython)
    hashes: dict[str, list[str]] = dc.field(default_factory=dict)
    ignore_compatibility: bool = False
    allow_yanked: bool = False
    format_control: FormatControl = dc.field(default_factory=FormatControl)

    def __post_init__(self) -> None:
        self._canonical_name = canonicalize_name(self.package_name)

    def _check_yanked(self, link: Link) -> None:
        if link.yank_reason is not None and not self.allow_yanked:
            yank_reason = f"due to {link.yank_reason}" if link.yank_reason else ""
            raise LinkMismatchError(f"Yanked {yank_reason}")

    def _check_requires_python(self, link: Link) -> None:
        if not self.ignore_compatibility and link.requires_python:
            py_ver = self.target_python.py_ver or sys.version_info[:2]
            py_version = ".".join(str(v) for v in py_ver)
            if not SpecifierSet(link.requires_python).contains(py_version, True):
                raise LinkMismatchError(
                    "The target python version({}) doesn't match "
                    "the requires-python specifier {}".format(
                        py_version, link.requires_python
                    ),
                )

    def _check_hashes(self, link: Link) -> None:
        def hash_mismatch(
            hash_name: str, given_hash: str, allowed_hashes: list[str]
        ) -> None:
            raise LinkMismatchError(
                f"Hash mismatch, expected: {allowed_hashes}\n"
                f"got: {hash_name}:{given_hash}"
            )

        if not self.hashes:
            return
        if link.hash_name and link.hash_name in self.hashes:
            if link.hash not in self.hashes[link.hash_name]:
                hash_mismatch(
                    link.hash_name, cast(str, link.hash), self.hashes[link.hash_name]
                )

        hash_name, allowed_hashes = next(iter(self.hashes.items()))
        given_hash = self._get_hash(link, hash_name)
        if given_hash not in allowed_hashes:
            hash_mismatch(hash_name, given_hash, allowed_hashes)

    def _get_hash(self, link: Link, hash_name: str) -> str:
        if link.hash_name == hash_name:
            return cast(str, link.hash)
        resp = self.session.get(link.normalized, stream=True)
        hasher = hashlib.new(hash_name)
        for chunk in resp.iter_content(chunk_size=1024 * 8):
            hasher.update(chunk)
        digest = hasher.hexdigest()
        # Store the hash on the link for future use
        fragment_dict = link._fragment_dict
        fragment_dict.pop(link.hash_name, None)  # type: ignore
        fragment_dict[hash_name] = digest
        link.__dict__["parsed"] = link.parsed._replace(
            fragment=urlencode(fragment_dict)
        )
        return digest

    def evaluate_link(self, link: Link) -> Package | None:
        """
        Evaluate the link and return the package if it matches or None if it doesn't.
        """
        try:
            self.format_control.check_format(link, self.package_name)
            self._check_yanked(link)
            self._check_requires_python(link)
            version: str | None = None
            if link.is_wheel:
                try:
                    wheel_info = parse_wheel_filename(link.filename)
                except (InvalidWheelFilename, InvalidVersion) as e:
                    raise LinkMismatchError(str(e))
                if self._canonical_name != wheel_info[0]:
                    raise LinkMismatchError(
                        f"The package name doesn't match {wheel_info[0]}"
                    )
                if not self.ignore_compatibility and wheel_info[3].isdisjoint(
                    self.target_python.supported_tags()
                ):
                    raise LinkMismatchError(
                        "none of the wheel tags({}) are compatible".format(
                            ", ".join(sorted(str(tag) for tag in wheel_info[3]))
                        ),
                    )
                version = str(wheel_info[1])
            else:
                if link._fragment_dict.get("egg"):
                    egg_info = strip_extras(link._fragment_dict["egg"])
                else:
                    egg_info, ext = splitext(link.filename)
                    if not ext:
                        raise LinkMismatchError(f"Not a file: {link.filename}")
                    if ext not in ARCHIVE_EXTENSIONS:
                        raise LinkMismatchError(
                            f"Unsupported archive format: {link.filename}"
                        )
                version = parse_version_from_egg_info(egg_info, self._canonical_name)
                if version is None:
                    raise LinkMismatchError(
                        f"Missing version in the filename {egg_info}"
                    )
            self._check_hashes(link)
        except LinkMismatchError as e:
            logger.debug("Skip link %s: %s", link, e)
            return None
        return Package(name=self.package_name, version=version, link=link)


def evaluate_package(
    package: Package,
    requirement: packaging.requirements.Requirement,
    allow_prereleases: bool | None = None,
) -> bool:
    """Evaluate the package based on the requirement.

    Args:
        package (Package): The package to evaluate
        requirement: The requirement to evaluate against
        allow_prerelease (bool|None): Whether to allow prereleases,
            or None to infer from the specifier.
    Returns:
        bool: True if the package matches the requirement, False otherwise
    """
    if requirement.name:
        if canonicalize_name(package.name) != canonicalize_name(requirement.name):
            logger.debug(
                "Skip package %s: name doesn't match %s", package, requirement.name
            )
            return False

    if requirement.specifier and package.version:
        if not requirement.specifier.contains(
            package.version, prereleases=allow_prereleases
        ):
            logger.debug(
                "Skip package %s: version doesn't match %s",
                package,
                requirement.specifier,
            )
            return False
    return True
