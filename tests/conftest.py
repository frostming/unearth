"""Configuration for the pytest test suite."""

from __future__ import annotations

import os
import sys
from ssl import SSLContext
from typing import TYPE_CHECKING

import flask
import pytest
from httpx import WSGITransport
from wsgiadapter import WSGIAdapter as _WSGIAdapter

from tests.fixtures.app import BASE_DIR, create_app
from unearth.fetchers import PyPIClient
from unearth.fetchers.legacy import InsecureMixin, PyPISession

if TYPE_CHECKING:
    from typing import Literal


class WSGIAdapter(_WSGIAdapter):
    def send(self, request, *args, **kwargs):
        resp = super().send(request, *args, **kwargs)
        resp.connection = self
        return resp


class InsecureWSGIAdapter(InsecureMixin, WSGIAdapter):
    pass


@pytest.fixture(scope="session")
def custom_certificate_authority():
    if sys.version_info >= (3, 13):
        pytest.skip("trustme is not compatible with Python 3.13")
    import trustme

    return trustme.CA()


@pytest.fixture(scope="session")
def self_signed_server_cert(httpserver_listen_address, custom_certificate_authority):
    server, _ = httpserver_listen_address
    return custom_certificate_authority.issue_cert(server)


@pytest.fixture(scope="session")
def httpserver_ssl_context(self_signed_server_cert):
    server_context = SSLContext()
    self_signed_server_cert.configure_cert(server_context)
    return server_context


@pytest.fixture(scope="session")
def httpserver_listen_address():
    return (
        "localhost",
        # select the port randomly
        0,
    )


@pytest.fixture()
def fixtures_dir():
    return BASE_DIR


@pytest.fixture()
def pypi():
    return create_app()


@pytest.fixture()
def pypi_auth(pypi):
    def check_auth(auth):
        return auth.username == os.getenv(
            "PYPI_USER", "test"
        ) and auth.password == os.getenv("PYPI_PASSWORD", "password")

    def unauthenticated():
        message = {"message": "Unauthenticated"}
        resp = flask.make_response(flask.jsonify(message), 401)
        resp.headers["WWW-Authenticate"] = "Basic realm='Main'"
        return resp

    @pypi.before_request
    def require_basic_auth():
        auth = flask.request.authorization
        if not auth or not check_auth(auth):
            return unauthenticated()

    return pypi


@pytest.fixture(params=["sync", "legacy"])
def fetcher_type(request) -> Literal["sync", "legacy"]:
    return request.param


@pytest.fixture()
def session(fetcher_type):
    if fetcher_type == "sync":
        client = PyPIClient()
    else:
        client = PyPISession()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def pypi_session(pypi, fetcher_type, mocker):
    if fetcher_type == "sync":
        client = PyPIClient(transport=WSGITransport(pypi))
    else:
        mocker.patch.object(
            PyPISession, "insecure_adapter_cls", return_value=InsecureWSGIAdapter(pypi)
        )
        mocker.patch.object(
            PyPISession, "secure_adapter_cls", return_value=WSGIAdapter(pypi)
        )
        client = PyPISession()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(params=["html", "json"])
def content_type(request, monkeypatch) -> str:
    monkeypatch.setenv("INDEX_RETURN_TYPE", request.param)
    return request.param
