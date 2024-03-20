import logging

import pytest

from unearth.auth import MultiDomainBasicAuth
from unearth.collector import is_secure_origin
from unearth.fetchers.legacy import PyPISession
from unearth.fetchers.sync import PyPIClient
from unearth.link import Link


@pytest.fixture
def private_session(fetcher_type):
    if fetcher_type == "sync":
        session = PyPIClient(trusted_hosts=["example.org", "192.168.0.1:8080"])
    else:
        session = PyPISession(trusted_hosts=["example.org", "192.168.0.1:8080"])
    try:
        yield session
    finally:
        session.close()


@pytest.mark.parametrize(
    "url, is_secure",
    [
        ("https://pypi.org/simple", True),
        ("wss://abc.com/", True),
        ("http://localhost:8000/", True),
        ("http://127.0.0.1:8000/", True),
        ("http://[::1]:8000/", True),
        ("file:///tmp/", True),
        ("ftp://localhost/", True),
        ("http://example.org/", True),
        ("http://example.org/foo/bar", True),
        ("ftp://example.org:8000", True),
        ("http://insecure.com/", False),
        ("http://192.168.0.1/", False),
        ("http://192.168.0.1:8080/simple", True),
    ],
)
def test_session_is_secure_origin(private_session, url, is_secure):
    assert is_secure_origin(private_session, Link(url)) == is_secure


def test_session_with_selfsigned_ca(
    httpserver, custom_certificate_authority, fetcher_type, tmp_path
):
    ca_cert = tmp_path / "ca.crt"
    custom_certificate_authority.cert_pem.write_to_path(ca_cert)
    if fetcher_type == "sync":
        session = PyPIClient(verify=str(ca_cert))
    else:
        session = PyPISession(ca_certificates=ca_cert)

    httpserver.expect_request("/").respond_with_json({})
    with session:
        assert session.get(httpserver.url_for("/")).json() == {}


@pytest.mark.usefixtures("pypi_auth")
def test_session_auth_401_if_no_prompting(pypi_session):
    pypi_session.auth = MultiDomainBasicAuth(prompting=False)
    resp = pypi_session.get("https://pypi.org/simple")
    assert resp.status_code == 401


@pytest.mark.usefixtures("pypi_auth")
def test_session_auth_from_source_urls(pypi_session):
    pypi_session.auth = MultiDomainBasicAuth(
        prompting=False, index_urls=["https://test:password@pypi.org/simple"]
    )
    resp = pypi_session.get("https://pypi.org/simple/click")
    assert resp.status_code == 200
    assert not any(r.status_code == 401 for r in resp.history)


@pytest.mark.usefixtures("pypi_auth")
def test_session_auth_with_empty_password(pypi_session, monkeypatch):
    monkeypatch.setenv("PYPI_PASSWORD", "")
    pypi_session.auth = MultiDomainBasicAuth(
        prompting=False, index_urls=["https://test:@pypi.org/simple"]
    )
    resp = pypi_session.get("https://pypi.org/simple/click")
    assert resp.status_code == 200
    assert not any(r.status_code == 401 for r in resp.history)


@pytest.mark.usefixtures("pypi_auth")
def test_session_auth_from_prompting(pypi_session, mocker):
    pypi_session.auth = MultiDomainBasicAuth(prompting=True)
    mocker.patch.object(
        MultiDomainBasicAuth,
        "_prompt_for_password",
        return_value=("test", "password", False),
    )
    resp = pypi_session.get("https://pypi.org/simple/click")
    assert resp.status_code == 200
    assert any(r.status_code == 401 for r in resp.history)

    resp = pypi_session.get("https://pypi.org/simple/click")
    assert resp.status_code == 200
    assert not any(r.status_code == 401 for r in resp.history)


@pytest.mark.usefixtures("pypi_auth")
def test_session_auth_warn_agains_wrong_credentials(pypi_session, caplog, mocker):
    caplog.set_level(logging.WARNING)
    mocker.patch.object(
        MultiDomainBasicAuth,
        "_prompt_for_password",
        return_value=("test", "incorrect", False),
    )
    pypi_session.auth = MultiDomainBasicAuth(prompting=True)
    resp = pypi_session.get("https://pypi.org/simple/click")
    assert resp.status_code == 401
    record = caplog.records[-1]
    assert record.levelname == "WARNING"
    assert "401 Error, Credentials not correct" in record.message
