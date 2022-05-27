"""Configuration for the pytest test suite."""
from unittest import mock

import flask
import pytest
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


@pytest.fixture()
def fixtures_dir():
    return BASE_DIR


@pytest.fixture()
def pypi():
    wsgi_app = create_app()
    with mock.patch.object(
        PyPISession, "insecure_adapter_cls", return_value=WSGIAdapter(wsgi_app)
    ):
        with mock.patch.object(
            PyPISession,
            "secure_adapter_cls",
            return_value=InsecureWSGIAdapter(wsgi_app),
        ):
            yield wsgi_app


@pytest.fixture()
def pypi_auth(pypi):
    def check_auth(auth):
        return auth.username == "test" and auth.password == "password"

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
