"""Collect links from simple index or find links location."""
from __future__ import annotations

import logging
import mimetypes
from html.parser import HTMLParser
from typing import Iterable, NamedTuple
from urllib import parse

from requests.models import Response

from unearth.link import Link
from unearth.session import PyPISession
from unearth.utils import is_archive_file, path_to_url

logger = logging.getLogger(__package__)


class LinkCollectError(Exception):
    pass


class HTMLPage(NamedTuple):
    link: Link
    html: str


class IndexHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.base_url: str | None = None
        self.anchors: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "base" and self.base_url is None:
            base_url = dict(attrs).get("href")
            if base_url is not None:
                self.base_url = base_url
        elif tag == "a":
            self.anchors.append(dict(attrs))


def parse_html_page(page: HTMLPage) -> Iterable[Link]:
    parser = IndexHTMLParser()
    parser.feed(page.html)
    base_url = parser.base_url or page.link.url_without_fragment
    for anchor in parser.anchors:
        href = anchor.get("href")
        if href is None:
            continue
        url = parse.urljoin(base_url, href)
        requires_python = anchor.get("data-requires-python")
        yank_reason = anchor.get("data-yanked")
        yield Link(
            url, base_url, yank_reason=yank_reason, requires_python=requires_python
        )


def collect_links_from_location(
    session: PyPISession, location: Link, expand: bool = False
) -> Iterable[Link]:
    """Collect package links from a remote URL or local path.

    If the path is a directory and expand is True, collect links from all HTML files
    as well as local artifacts. Otherwise, collect links from $dir/index.html.
    If the path is a file, parse it and collect links from it.
    """
    logger.debug("Collecting links from %s", location.redacted)
    if location.is_file:
        path = location.file_path
        if path.is_dir():
            if expand:
                for child in path.iterdir():
                    file_url = path_to_url(str(child))
                    if _is_html_file(file_url):
                        yield from _collect_links_from_html(session, Link(file_url))
                    else:
                        yield Link(file_url)
            else:
                index_html = Link(path_to_url(path.joinpath("index.html").as_posix()))
                yield from _collect_links_from_html(session, index_html)
        else:
            yield from _collect_links_from_html(session, location)

    else:
        yield from _collect_links_from_html(session, location)


def fetch_page(session: PyPISession, location: Link) -> HTMLPage | None:
    if location.is_vcs:
        logger.warning("Skip %s because it is a VCS link.", location.redacted)
        return None
    try:
        resp = _get_html_response(session, location)
    except LinkCollectError as e:
        logger.warning("Skip %s because of %s.", location.redacted, e)
        return None
    return HTMLPage(Link(resp.url), resp.text)


def _collect_links_from_html(session: PyPISession, location: Link) -> Iterable[Link]:
    if not session.is_secure_origin(location):
        return []
    page = fetch_page(session, location)
    return parse_html_page(page) if page is not None else []


def _is_html_file(file_url: str) -> bool:
    return mimetypes.guess_type(file_url, strict=False)[0] == "text/html"


def _get_html_response(session: PyPISession, location: Link) -> Response:
    if is_archive_file(location.filename):
        # Send a HEAD request to ensure the file is an HTML file to avoid downloading
        # a large file.
        _ensure_html_response(session, location)

    resp = session.get(
        location.normalized,
        headers={"Accept": "text/html", "Cache-Control": "max-age=0"},
    )
    _check_for_status(resp)
    _ensure_html_type(resp)
    return resp


def _ensure_html_response(session: PyPISession, location: Link) -> None:
    if location.parsed.scheme not in {"http", "https"}:
        raise LinkCollectError(
            "NotHTTP: the file looks like an archive but its content-type "
            "cannot be checked by a HEAD request."
        )

    resp = session.head(location.url)
    _check_for_status(resp)
    _ensure_html_type(resp)


def _check_for_status(resp: Response) -> None:
    reason = resp.reason

    if isinstance(reason, bytes):
        try:
            reason = reason.decode("utf-8")
        except UnicodeDecodeError:
            reason = reason.decode("iso-8859-1")

    if 400 <= resp.status_code < 500:
        raise LinkCollectError(f"Client Error({resp.status_code}): {reason}")
    if 500 <= resp.status_code < 600:
        raise LinkCollectError(f"Server Error({resp.status_code}): {reason}")


def _ensure_html_type(resp: Response) -> None:
    content_type = resp.headers.get("content-type", "").lower()
    if not content_type.startswith("text/html"):
        raise LinkCollectError(
            f"NotHTML: only HTML is supported but its content-type "
            f"is {content_type}."
        )
