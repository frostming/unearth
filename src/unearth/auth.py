from __future__ import annotations

import getpass
import logging
from typing import Any, Iterable, Optional, Tuple, cast
from urllib.parse import urlparse

from requests import Response
from requests.auth import AuthBase, HTTPBasicAuth
from requests.models import PreparedRequest
from requests.utils import get_netrc_auth

from unearth.utils import split_auth_from_netloc, split_auth_from_url

try:
    import keyring  # type: ignore
except ModuleNotFoundError:
    keyring = None  # type: ignore[assignment]

AuthInfo = Tuple[str, str]
MaybeAuth = Optional[Tuple[str, Optional[str]]]
logger = logging.getLogger(__name__)


def get_keyring_auth(url: str | None, username: str | None) -> AuthInfo | None:
    """Return the tuple auth for a given url from keyring."""
    global keyring
    if not url or not keyring:
        return None

    try:
        try:
            get_credential = keyring.get_credential
        except AttributeError:
            pass
        else:
            logger.debug("Getting credentials from keyring for %s", url)
            cred = get_credential(url, username)
            if cred is not None:
                return cred.username, cred.password
            return None

        if not username:
            username = "__token__"
        logger.debug("Getting password from keyring for %s@%s", username, url)
        password = keyring.get_password(url, username)
        if password:
            return username, password

    except Exception as exc:
        logger.warning(
            "Keyring is skipped due to an exception: %s",
            str(exc),
        )
        keyring = None  # type: ignore[assignment]
    return None


class MultiDomainBasicAuth(AuthBase):
    def __init__(self, prompting: bool = True, index_urls: Iterable[str] = ()) -> None:
        self.prompting = prompting
        self.index_urls = list(index_urls)

        self._cached_passwords: dict[str, AuthInfo] = {}
        self._credentials_to_save: tuple[str, str, str] | None = None

    def _get_auth_from_index_url(self, netloc: str) -> tuple[MaybeAuth, str | None]:
        """Return the extracted auth and the original index URL matching
        the requested netloc.

        Returns None if no matching index was found, or if --no-index
        was specified by the user.
        """
        if not netloc or not self.index_urls:
            return None, None

        for u in self.index_urls:
            parsed = urlparse(u)
            auth, index_netloc = split_auth_from_netloc(parsed.netloc)
            if index_netloc == netloc:
                return auth, u
        return None, None

    def _get_new_credentials(
        self,
        original_url: str,
        *,
        allow_netrc: bool = False,
        allow_keyring: bool = False,
    ) -> tuple[str | None, str | None]:
        """Find and return credentials for the specified URL."""
        # Split the credentials and netloc from the url.
        auth, url = split_auth_from_url(original_url)
        netloc = urlparse(url).netloc

        # Start with the credentials embedded in the url
        username, password = None, None
        if auth:
            username, password = auth
            if password is not None:
                logger.debug("Found credentials in url for %s", netloc)
                return cast(AuthInfo, auth)

        # Find a matching index url for this request
        index_auth, index_url = self._get_auth_from_index_url(netloc)
        if index_url:
            logger.debug("Found index url %s", index_url)

            # If an index URL was found, try its embedded credentials
            if index_auth is not None and index_auth[1] is not None:
                logger.debug("Found credentials in index url for %s", netloc)
                return cast(AuthInfo, index_auth)

        # Get creds from netrc if we still don't have them
        if allow_netrc:
            netrc_auth = get_netrc_auth(original_url)
            if netrc_auth:
                logger.debug("Found credentials in netrc for %s", netloc)
                return cast(AuthInfo, netrc_auth)

        # If we don't have a password and keyring is available, use it.
        if allow_keyring:
            # The index url is more specific than the netloc, so try it first
            kr_auth = get_keyring_auth(index_url, username) or get_keyring_auth(
                netloc, username
            )
            if kr_auth:
                logger.debug("Found credentials in keyring for %s", netloc)
                return kr_auth

        return username, password

    def _get_url_and_credentials(
        self, original_url: str
    ) -> tuple[str, str | None, str | None]:
        """Return the credentials to use for the provided URL.

        If allowed, netrc and keyring may be used to obtain the
        correct credentials.

        Returns (url_without_credentials, username, password). Note
        that even if the original URL contains credentials, this
        function may return a different username and password.
        """
        _, url = split_auth_from_url(original_url)
        netloc = urlparse(url).netloc
        # Try to get credentials from original url
        username, password = self._get_new_credentials(original_url)

        # If credentials not found, use any stored credentials for this netloc.
        # Do this if either the username or the password is missing.
        # This accounts for the situation in which the user has specified
        # the username in the index url, but the password comes from keyring.
        if (username is None or password is None) and netloc in self._cached_passwords:
            un, pw = self._cached_passwords[netloc]
            # It is possible that the cached credentials are for a different username,
            # in which case the cache should be ignored.
            if username is None or username == un:
                username, password = un, pw

        if username is not None or password is not None:
            # Store any acquired credentials.
            self._cached_passwords[netloc] = (username or "", password or "")

        return url, username, password

    def __call__(self, req: PreparedRequest) -> PreparedRequest:
        # Get credentials for this request
        url, username, password = self._get_url_and_credentials(cast(str, req.url))
        req.url = url

        if username is not None and password is not None:
            req = HTTPBasicAuth(username, password)(req)

        # Attach a hook to handle 401 responses
        req.register_hook("response", self.handle_401)

        return req

    # Factored out to allow for easy patching in tests
    def _prompt_for_password(self, netloc: str) -> tuple[str | None, str | None, bool]:
        username = input(f"User for {netloc}: ")
        if not username:
            return None, None, False
        auth = get_keyring_auth(netloc, username)
        if auth and auth[0] is not None and auth[1] is not None:
            return auth[0], auth[1], False
        password = getpass.getpass("Password: ")
        return username, password, True

    # Factored out to allow for easy patching in tests
    def _should_save_password_to_keyring(self) -> bool:
        if not keyring:
            return False
        return input("Save credentials to keyring [y/N]: ") == "y"

    def handle_401(self, resp: Response, **kwargs: Any) -> Response:
        # We only care about 401 responses, anything else we want to just
        #   pass through the actual response
        if resp.status_code != 401:
            return resp

        # We are not able to prompt the user so simply return the response
        if not self.prompting:
            return resp

        parsed = urlparse(cast(str, resp.url))

        # Query the keyring for credentials:
        username, password = self._get_new_credentials(
            resp.url,
            allow_netrc=True,
            allow_keyring=True,
        )

        # Prompt the user for a new username and password
        save = False
        if not username and not password:
            username, password, save = self._prompt_for_password(parsed.netloc)

        # Store the new username and password to use for future requests
        self._credentials_to_save = None
        if username is not None and password is not None:
            self._cached_passwords[parsed.netloc] = (username, password)

            # Prompt to save the password to keyring
            if save and self._should_save_password_to_keyring():
                self._credentials_to_save = (parsed.netloc, username, password)

        # Consume content and release the original connection to allow our new
        #   request to reuse the same one.
        resp.content
        resp.raw.release_conn()

        # Add our new username and password to the request
        req = HTTPBasicAuth(username or "", password or "")(resp.request)
        # We add new hooks on the fly, since the req is the same as resp.request
        # The hook will be picked up by the next iteration of `dispatch_hooks()`
        req.register_hook("response", self.warn_on_401)

        # On successful request, save the credentials that were used to
        # keyring. (Note that if the user responded "no" above, this member
        # is not set and nothing will be saved.)
        if self._credentials_to_save:
            req.register_hook("response", self.save_credentials)

        # Send our new request
        new_resp = resp.connection.send(req, **kwargs)  # type: ignore
        new_resp.history.append(resp)

        return new_resp

    def warn_on_401(self, resp: Response, **kwargs: Any) -> None:
        """Response callback to warn about incorrect credentials."""
        if resp.status_code == 401:
            logger.warning(
                "401 Error, Credentials not correct for %s",
                resp.request.url,
            )

    def save_credentials(self, resp: Response, **kwargs: Any) -> None:
        """Response callback to save credentials on success."""
        assert keyring is not None, "should never reach here without keyring"
        if not keyring:
            return

        creds = self._credentials_to_save
        self._credentials_to_save = None
        if creds and resp.status_code < 400:
            try:
                logger.info("Saving credentials to keyring")
                keyring.set_password(*creds)
            except Exception:
                logger.exception("Failed to save credentials")
