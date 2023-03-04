"""Configuration for the pytest test suite."""
import os
from ssl import SSLContext
from unittest import mock

import flask
import pytest
import trustme
from wsgiadapter import WSGIAdapter as _WSGIAdapter

from tests.fixtures.app import BASE_DIR, create_app
from unearth.session import InsecureMixin, PyPISession


class WSGIAdapter(_WSGIAdapter):
    def send(self, request, *args, **kwargs):
        resp = super().send(request, *args, **kwargs)
        resp.connection = self
        return resp


class InsecureWSGIAdapter(InsecureMixin, WSGIAdapter):
    pass


@pytest.fixture(scope="session")
def custom_certificate_authority():
    return trustme.CA()


@pytest.fixture(scope="session")
def self_signed_server_cert(httpserver_listen_address, custom_certificate_authority):
    server, port = httpserver_listen_address
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
    wsgi_app = create_app()
    with mock.patch.object(
        PyPISession, "insecure_adapter_cls", return_value=InsecureWSGIAdapter(wsgi_app)
    ):
        with mock.patch.object(
            PyPISession,
            "secure_adapter_cls",
            return_value=WSGIAdapter(wsgi_app),
        ):
            yield wsgi_app


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


@pytest.fixture()
def session():
    s = PyPISession()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(params=["html", "json"])
def content_type(request, monkeypatch):
    monkeypatch.setenv("INDEX_RETURN_TYPE", request.param)
    return request.param
