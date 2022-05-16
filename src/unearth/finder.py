"""The main class for the unearth package."""
from __future__ import annotations

import atexit
import dataclasses as dc
import functools
import os
from typing import Iterable
from urllib.parse import urljoin

from packaging.requirements import Requirement
from packaging.utils import BuildTag, canonicalize_name, parse_wheel_filename
from packaging.version import parse as parse_version
from requests.sessions import Session

from unearth.collector import collect_links_from_location
from unearth.evaluator import (
    Evaluator,
    FormatControl,
    Package,
    TargetPython,
    evaluate_package,
    is_equality_specifier,
)
from unearth.link import Link
from unearth.session import PyPISession


@dc.dataclass(frozen=True)
class BestMatch:
    """The best match for a package.

    Attributes:
        candidates (list[Package]): All candidates for the
            package.
        applicable_candidates (list[Package]): Candidates
            that match the requirement.
        best_candidate (Package): The best candidate
            for the package.
    """

    candidates: list[Package]
    applicable_candidates: list[Package]
    best_candidate: Package | None


class PackageFinder:
    """The main class for the unearth package.

    Args:
        index_urls: (Iterable[str]): The urls of the index pages.
        find_links: (Iterable[str]): The urls or paths of the find links.
        trusted_hosts: (Iterable[str]): The trusted hosts.
        target_python (TargetPython): The links must match
            the target Python
        ignore_compatibility (bool): Whether to ignore the compatibility check
        prefer_binary (bool): Whether to prefer binary packages even if
            newer sdist pacakges exist.
    """

    def __init__(
        self,
        session: Session | None = None,
        index_urls: Iterable[str] = (),
        find_links: Iterable[str] = (),
        trusted_hosts: Iterable[str] = (),
        target_python: TargetPython | None = None,
        ignore_compatibility: bool = False,
        no_binary: Iterable[str] = (),
        only_binary: Iterable[str] = (),
        prefer_binary: bool = False,
    ) -> None:
        self.index_urls = list(index_urls)
        self.find_links = list(find_links)
        self.target_python = target_python or TargetPython()
        self.ignore_compatibility = ignore_compatibility
        self.no_binary = [canonicalize_name(name) for name in no_binary]
        self.only_binary = [canonicalize_name(name) for name in only_binary]
        self.prefer_binary = prefer_binary
        if session is None:
            session = PyPISession(
                index_urls=self.index_urls, trusted_hosts=trusted_hosts
            )
            atexit.register(session.close)
        self.session = session

        self._tag_priorities = {
            tag: i for i, tag in enumerate(self.target_python.supported_tags())
        }

    def build_evaluator(
        self,
        package_name: str,
        allow_yanked: bool | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> Evaluator:
        """Build an evaluator for the given package name.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            Evaluator: The evaluator for the given package name
        """
        if hashes:
            hashes = {name: sorted(values) for name, values in hashes.items()}
        canonical_name = canonicalize_name(package_name)
        format_control = FormatControl(
            no_binary=canonical_name in self.no_binary or ":all:" in self.no_binary,
            only_binary=canonical_name in self.only_binary
            or ":all:" in self.only_binary,
        )
        return Evaluator(
            package_name=package_name,
            target_python=self.target_python,
            ignore_compatibility=self.ignore_compatibility,
            allow_yanked=allow_yanked,
            hashes=hashes or {},
            format_control=format_control,
        )

    def _build_index_page_link(self, index_url: str, package_name: str) -> Link:
        return Link(urljoin(index_url.rstrip("/") + "/", package_name))

    def _build_find_link(self, find_link: str) -> Link:
        if os.path.exists(find_link):
            return Link.from_path(os.path.abspath(find_link))
        return Link(find_link)

    def _evaluate_links(
        self, links: Iterable[Link], evaluator: Evaluator
    ) -> Iterable[Package]:
        return filter(None, map(evaluator.evaluate_link, links))

    def _evaluate_packages(
        self,
        packages: Iterable[Package],
        requirement: Requirement,
        allow_prereleases: bool | None = None,
    ) -> Iterable[Package]:
        evaluator = functools.partial(
            evaluate_package,
            requirement=requirement,
            allow_prereleases=allow_prereleases,
        )
        return filter(evaluator, packages)

    def _sort_key(self, package: Package) -> tuple:
        link = package.link
        pri = len(self._tag_priorities)
        build_tag: BuildTag = ()
        prefer_binary = False
        if link.is_wheel:
            *_, build_tag, file_tags = parse_wheel_filename(link.filename)
            pri = min(
                (self._tag_priorities.get(tag, pri) for tag in file_tags), default=pri
            )
            if self.prefer_binary:
                prefer_binary = True
        return (
            -int(link.is_yanked),
            -int(prefer_binary),
            parse_version(package.version) if package.version is not None else 0,
            -pri,
            build_tag,
        )

    def _find_packages(
        self,
        package_name: str,
        allow_yanked: bool = False,
        hashes: dict[str, list[str]] | None = None,
    ) -> Iterable[Package]:
        """Find all packages with the given name.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            Iterable[Package]: The packages with the given name
        """
        evaluator = self.build_evaluator(package_name, allow_yanked, hashes)
        for index_url in self.index_urls:
            package_link = self._build_index_page_link(index_url, package_name)
            yield from self._evaluate_links(
                collect_links_from_location(self.session, package_link), evaluator
            )
        for find_link in self.find_links:
            link = self._build_find_link(find_link)
            yield from self._evaluate_links(
                collect_links_from_location(self.session, link, expand=True), evaluator
            )

    def find_all_packages(
        self,
        package_name: str,
        allow_yanked: bool = False,
        hashes: dict[str, list[str]] | None = None,
    ) -> list[Package]:
        """Find all packages with the given package name, best match first.

        Args:
            package_name (str): The desired package name
            allow_yanked (bool): Whether to allow yanked candidates.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            list[Package]: The packages list sorted by best match
        """
        return sorted(
            self._find_packages(package_name, allow_yanked, hashes),
            key=self._sort_key,
            reverse=True,
        )

    def _find_packages_from_requirement(
        self,
        requirement: Requirement,
        allow_yanked: bool | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> Iterable[Package]:
        if allow_yanked is None:
            allow_yanked = is_equality_specifier(requirement.specifier)
        if requirement.url:
            yield Package(requirement.name, None, link=Link(requirement.url))
        else:
            yield from self._find_packages(requirement.name, allow_yanked, hashes)

    def find_matches(
        self,
        requirement: Requirement | str,
        allow_yanked: bool | None = None,
        allow_prereleases: bool | None = None,
        hashes: dict[str, list[str]] | None = None,
    ) -> list[Package]:
        """Find all packages matching the given requirement, best match first.

        Args:
            requirement (Requirement): A packaging.requirements.Requirement
            allow_yanked (bool|None): Whether to allow yanked candidates,
                or None to infer from the specifier.
            allow_prereleases (bool|None): Whether to allow prereleases,
                or None to infer from the specifier.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            list[Package]: The packages list sorted by best match
        """
        if isinstance(requirement, str):
            requirement = Requirement(requirement)
        return sorted(
            self._evaluate_packages(
                self._find_packages_from_requirement(requirement, allow_yanked, hashes),
                requirement,
                allow_prereleases,
            ),
            key=self._sort_key,
            reverse=True,
        )

    def find_best_match(
        self,
        requirement: Requirement | str,
        allow_yanked: bool | None = None,
        allow_prereleases: bool | None = None,
        hashes: dict[str, list[str]] = None,
    ) -> BestMatch:
        """Find the best match for the given requirement.

        Args:
            requirement (Requirement): A packaging.requirements.Requirement
            allow_yanked (bool|None): Whether to allow yanked candidates,
                or None to infer from the specifier.
            allow_prereleases (bool|None): Whether to allow prereleases,
                or None to infer from the specifier.
            hashes (dict[str, list[str]]|None): The hashes to filter on.

        Returns:
            BestMatch: The best match
        """
        if isinstance(requirement, str):
            requirement = Requirement(requirement)
        candidates = list(
            self._find_packages_from_requirement(requirement, allow_yanked, hashes)
        )
        applicable_candidates = list(
            self._evaluate_packages(candidates, requirement, allow_prereleases)
        )
        best_match = max(applicable_candidates, key=self._sort_key, default=None)
        return BestMatch(candidates, applicable_candidates, best_match)
