"""The command-line interface for the unearth package."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import cast

from packaging.requirements import Requirement

from unearth.finder import PackageFinder
from unearth.link import Link
from unearth.utils import splitext


@dataclass(frozen=True)
class CLIArgs:
    requirement: Requirement
    verbose: bool
    index_urls: list[str]
    find_links: list[str]
    trusted_hosts: list[str]
    no_binary: list[str]
    only_binary: list[str]
    prefer_binary: bool
    all: bool
    link_only: bool
    download: str | None


def _setup_logger(verbosity: bool) -> None:
    logger = logging.getLogger(__package__)
    logger.setLevel(logging.DEBUG if verbosity else logging.WARNING)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find and download packages from a PEP 508 requirement string.",
    )
    parser.add_argument(
        "requirement",
        type=Requirement,
        help="A PEP 508 requirement string, e.g. 'requests>=2.18.4'.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging."
    )
    parser.add_argument(
        "--index-url",
        "-i",
        dest="index_urls",
        metavar="URL",
        action="append",
        help="(Multiple)(PEP 503)Simple Index URLs.",
    )
    parser.add_argument(
        "--find-link",
        "-f",
        dest="find_links",
        metavar="LOCATION",
        action="append",
        help="(Multiple)URLs or locations to find links from.",
    )
    parser.add_argument(
        "--trusted-host",
        dest="trusted_hosts",
        metavar="HOST",
        action="append",
        help="(Multiple)Trusted hosts that should skip the verification.",
    )
    parser.add_argument(
        "--no-binary",
        action="append",
        metavar="PACKAGE",
        help="(Multiple)Specify package names to exclude binary results, "
        "or `:all:` to exclude all binary results.",
    )
    parser.add_argument(
        "--only-binary",
        action="append",
        metavar="PACKAGE",
        help="(Multiple)Specify package names to only allow binary results, "
        "or `:all:` to enforce binary results for all packages.",
    )
    parser.add_argument(
        "--prefer-binary",
        action="store_true",
        help="Prefer binary packages even if sdist candidates of newer versions exist.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Return all applicable versions."
    )
    parser.add_argument(
        "--link-only",
        "-L",
        action="store_true",
        help="Only return links instead of a JSON object.",
    )
    parser.add_argument(
        "--download",
        "-d",
        nargs="?",
        const=".",
        metavar="DIR",
        help="Download the package(s) to DIR.",
    )
    return parser


def get_dest_for_package(dest: str, link: Link) -> str:
    filename = link.filename.rsplit("@", 1)[0]
    fn, _ = splitext(filename)
    return os.path.join(dest, fn)


def cli(argv: list[str] | None = None) -> None:
    parser = cli_parser()
    args = cast(CLIArgs, parser.parse_args(argv))
    _setup_logger(args.verbose)
    finder = PackageFinder(
        index_urls=args.index_urls or ["https://pypi.org/simple"],
        find_links=args.find_links or [],
        trusted_hosts=args.trusted_hosts or [],
        no_binary=args.no_binary or [],
        only_binary=args.only_binary or [],
        prefer_binary=args.prefer_binary,
        verbosity=int(args.verbose),
    )
    matches = finder.find_matches(args.requirement)
    if not matches:
        print("No matches are found.", file=sys.stderr)
        sys.exit(1)
    if not args.all:
        matches = matches[:1]

    result = []
    with tempfile.TemporaryDirectory("unearth-download-") as tempdir:
        for match in matches:
            data = match.as_json()
            if args.download is not None:
                download_dir, dest = tempdir, get_dest_for_package(
                    args.download, match.link
                )
                if match.link.is_wheel:
                    download_dir = args.download
                data["local_path"] = finder.download_and_unpack(
                    match.link,
                    dest,
                    download_dir,
                ).as_posix()
            result.append(data)
    if args.link_only:
        for item in result:
            print(item["link"]["url"])
            if "local_path" in item:
                print("  ==>", item["local_path"])
    else:
        print(json.dumps(result[0] if len(result) == 1 else result, indent=2))


if __name__ == "__main__":
    cli()
