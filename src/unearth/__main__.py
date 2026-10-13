"""The command-line interface for the unearth package."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

from unearth.evaluator import TargetPython
from unearth.finder import PackageFinder


@dataclass(frozen=True)
class CLIArgs:
    requirement: Requirement | None
    requirements: str | None
    verbose: bool
    index_urls: list[str]
    find_links: list[str]
    trusted_hosts: list[str]
    no_binary: bool
    only_binary: bool
    prefer_binary: bool
    all: bool
    link_only: bool
    download: str | None
    py_ver: tuple[int, ...] | None
    abis: list[str] | None
    impl: str | None
    platforms: list[str] | None


def _setup_logger(verbosity: bool) -> None:
    logger = logging.getLogger("unearth")
    logger.setLevel(logging.DEBUG if verbosity else logging.WARNING)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def comma_split(arg: str) -> list[str]:
    return arg.split(",")


def to_py_ver(arg: str) -> tuple[int, ...]:
    return tuple(int(i) for i in arg.split(".") if i.isdigit())


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find and download packages from a PEP 508 requirement string.",
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "requirement",
        nargs="?",
        type=Requirement,
        help="A PEP 508 requirement string, e.g. 'requests>=2.18.4'.",
    )
    inputs.add_argument(
        "--requirements",
        "-r",
        metavar="FILE",
        help="Read PEP 508 requirements from a UTF-8 file, one per line.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging."
    )
    parser.add_argument(
        "--index-url",
        "-i",
        metavar="URL",
        dest="index_urls",
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
        action="store_true",
        help="Exclude binary packages from the results.",
    )
    parser.add_argument(
        "--only-binary",
        action="store_true",
        help="Only include binary packages in the results.",
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
    group = parser.add_argument_group("Target Python options")
    group.add_argument(
        "--python-version",
        "--py",
        dest="py_ver",
        type=to_py_ver,
        help="Target Python version. e.g. 3.11.0",
    )
    group.add_argument(
        "--abis", type=comma_split, help="Comma-separated list of ABIs. e.g. cp39,cp310"
    )
    group.add_argument(
        "--implementation",
        "--impl",
        dest="impl",
        help="Python implementation. e.g. cp,pp,jy,ip",
    )
    group.add_argument(
        "--platforms",
        type=comma_split,
        help="Comma-separated list of platforms. e.g. win_amd64,linux_x86_64",
    )
    return parser


def _strip_comment(line: str) -> str:
    line = line.strip()
    if line.startswith("#"):
        return ""
    for index, char in enumerate(line):
        if char == "#" and line[index - 1].isspace():
            try:
                Requirement(line[:index])
            except InvalidRequirement:
                continue
            return line[:index].rstrip()
    return line


def _read_requirements(
    filename: str, parser: argparse.ArgumentParser
) -> list[tuple[Requirement, str]]:
    try:
        lines = Path(filename).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as error:
        parser.error(f"Cannot read requirements file {filename}: {error}")
    requirements = []
    for number, line in enumerate(lines, 1):
        line = _strip_comment(line)
        if not line:
            continue
        location = f"{filename}:{number}"
        if line.startswith("-") or line.endswith("\\"):
            parser.error(
                f"{location}: This command does not support pip options or line continuations."
            )
        try:
            requirement = Requirement(line)
        except InvalidRequirement as error:
            parser.error(f"{location}: {error}")
        requirements.append((requirement, location))
    return requirements


def cli(argv: list[str] | None = None) -> None:
    parser = cli_parser()
    args = CLIArgs(**vars(parser.parse_args(argv)))
    _setup_logger(args.verbose)
    requirements: list[tuple[Requirement, str | None]]
    if args.requirements is not None:
        requirements = list(_read_requirements(args.requirements, parser))
    else:
        assert args.requirement is not None
        requirements = [(args.requirement, None)]
    names = [requirement.name for requirement, _ in requirements]
    target_python = TargetPython(args.py_ver, args.abis, args.impl, args.platforms)
    finder = PackageFinder(
        index_urls=args.index_urls or [],
        find_links=args.find_links or [],
        trusted_hosts=args.trusted_hosts or [],
        target_python=target_python,
        no_binary=names if args.no_binary else [],
        only_binary=names if args.only_binary else [],
        prefer_binary=names if args.prefer_binary else [],
        verbosity=int(args.verbose),
    )
    matches = []
    for requirement, location in requirements:
        found = list(finder.find_matches(requirement))
        if not found:
            message = "No matches are found."
            if location is not None:
                message = f"{location}: {message} ({requirement})"
            print(message, file=sys.stderr)
            sys.exit(1)
        matches.extend(found if args.all else found[:1])

    result = []
    if args.download:
        os.makedirs(args.download, exist_ok=True)
    for match in matches:
        data = match.as_json()
        if args.download is not None:
            data["local_path"] = finder.download(
                match.link,
                args.download,
            ).as_posix()
        result.append(data)
    if args.link_only:
        for item in result:
            print(item["link"]["url"])
            if "local_path" in item:
                print("  ==>", item["local_path"])
    else:
        output = result[0] if args.requirements is None and len(result) == 1 else result
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    cli()
