from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import (
    TYPE_CHECKING,
    Any,
    ContextManager,
    Iterable,
    Iterator,
    Mapping,
    cast,
)

import httpx
from httpx._config import DEFAULT_LIMITS
from httpx._content import AsyncIteratorByteStream

from unearth.fetchers import DEFAULT_SECURE_ORIGINS, Response
from unearth.fetchers.sync import LocalFSTransport
from unearth.utils import parse_netloc

if TYPE_CHECKING:
    import ssl

    from httpx._types import CertTypes, TimeoutTypes

    VerifyTypes = ssl.SSLContext | bool | str


class LocalFSAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self._transport = LocalFSTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = self._transport.handle_request(request)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=AsyncIteratorByteStream(response.stream._stream),  # type: ignore[attr-defined]
            request=request,
            extensions=response.extensions,
        )


class _AsyncStreamResponse:
    def __init__(
        self, fetcher: SharedAsyncPyPIClient, response: httpx.Response
    ) -> None:
        self._fetcher = fetcher
        self._response = response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    @property
    def encoding(self) -> str | None:
        return self._response.encoding

    @property
    def url(self) -> str | None:
        return str(self._response.url)

    @property
    def content(self) -> bytes:
        return self._fetcher._run_coroutine(self._response.aread())

    def json(self) -> dict:
        self._fetcher._run_coroutine(self._response.aread())
        return self._response.json()

    @property
    def reason_phrase(self) -> str:
        return self._response.reason_phrase

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_bytes(self, chunk_size: int | None = None) -> Iterator[bytes]:
        aiter = self._response.aiter_bytes(chunk_size=chunk_size)
        while True:
            try:
                yield self._fetcher._run_coroutine(aiter.__anext__())
            except StopAsyncIteration:
                return


class _AsyncStreamContext:
    def __init__(
        self,
        fetcher: SharedAsyncPyPIClient,
        url: str,
        headers: Mapping[str, str] | None,
    ) -> None:
        self._fetcher = fetcher
        self._url = url
        self._headers = headers
        self._context: Any = None

    async def _aenter(self) -> httpx.Response:
        self._context = self._fetcher._client.stream(
            "GET", self._url, headers=self._headers, auth=self._fetcher.auth
        )
        return await self._context.__aenter__()

    async def _aexit(self, exc_type, exc, tb) -> None:
        await self._context.__aexit__(exc_type, exc, tb)

    def __enter__(self) -> Response:
        return cast(
            Response,
            _AsyncStreamResponse(
                self._fetcher, self._fetcher._run_coroutine(self._aenter())
            ),
        )

    def __exit__(self, exc_type, exc, tb) -> None:
        self._fetcher._run_coroutine(self._aexit(exc_type, exc, tb))


class SharedAsyncPyPIClient:
    """
    Fetcher that allows multiple PackageFinder threads to share a single
    httpx.AsyncClient. This allows us to benefit from http/2 pipelining instead
    of opening a new connection for each thread.
    """

    def __init__(
        self,
        *,
        trusted_hosts: Iterable[str] = (),
        verify: VerifyTypes = True,
        cert: CertTypes | None = None,
        http1: bool = True,
        http2: bool = True,
        limits: httpx.Limits = DEFAULT_LIMITS,
        trust_env: bool = True,
        timeout: TimeoutTypes = 10.0,
        **kwargs: Any,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._closed = False
        self.auth: httpx.Auth | None = None

        self._trusted_host_ports: set[tuple[str, int | None]] = set()
        insecure_transport = httpx.AsyncHTTPTransport(
            verify=False,
            cert=cert,
            http1=http1,
            http2=http2,
            limits=limits,
            trust_env=trust_env,
        )

        mounts: dict[str, httpx.AsyncBaseTransport] = {
            "file://": LocalFSAsyncTransport()
        }
        for host in trusted_hosts:
            hostname, port = parse_netloc(host)
            self._trusted_host_ports.add((hostname, port))
            mounts[f"all://{host}"] = insecure_transport
        mounts.update(kwargs.pop("mounts", {}))

        self._client_kwargs: dict[str, Any] = {
            "verify": verify,
            "cert": cert,
            "http1": http1,
            "http2": http2,
            "limits": limits,
            "trust_env": trust_env,
            "timeout": timeout,
            "mounts": mounts,
            **kwargs,
        }

        self._thread.start()
        self._loop_ready.wait()
        self._client = self._run_coroutine(self._make_client())

    async def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(**self._client_kwargs)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def _submit_coroutine(self, coro: Any) -> Future[Any]:
        result: Future[Any] = Future()

        def runner() -> None:
            task = self._loop.create_task(coro)

            def complete(done: asyncio.Task[Any]) -> None:
                if done.cancelled():
                    result.cancel()
                    return
                error = done.exception()
                if error is not None:
                    result.set_exception(error)
                    return
                result.set_result(done.result())

            task.add_done_callback(complete)

        self._loop.call_soon_threadsafe(runner)
        return result

    def _run_coroutine(self, coro: Any) -> Any:
        return self._submit_coroutine(coro).result()

    def get(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        return self._run_coroutine(
            self._client.get(url, headers=headers, auth=self.auth)
        )

    def head(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> httpx.Response:
        return self._run_coroutine(
            self._client.head(url, headers=headers, auth=self.auth)
        )

    def get_stream(
        self, url: str, *, headers: Mapping[str, str] | None = None
    ) -> ContextManager[Response]:
        return _AsyncStreamContext(self, url, headers)

    def iter_secure_origins(self) -> Iterable[tuple[str, str, str]]:
        yield from DEFAULT_SECURE_ORIGINS
        for host, port in self._trusted_host_ports:
            yield ("*", host, "*" if port is None else str(port))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._run_coroutine(self._client.aclose())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

    def __enter__(self) -> SharedAsyncPyPIClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
