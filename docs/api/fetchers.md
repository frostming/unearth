```{caution}
This API is not finalized, and may change in a patch version.
```

# `unearth.fetchers`

```{eval-rst}
.. automodule:: unearth.fetchers

.. autoclass:: unearth.fetchers.PyPIClient
    :members:
```

## Shared Async Client From Sync Threads

Use `unearth.fetchers.async_.SharedAsyncPyPIClient` when sync worker threads
should share a single `httpx.AsyncClient` and event loop for network I/O:

```python
from concurrent.futures import ThreadPoolExecutor

from unearth.fetchers.async_ import SharedAsyncPyPIClient
from unearth.finder import PackageFinder


fetcher = SharedAsyncPyPIClient(http2=True)
finder = PackageFinder(
    session=fetcher,
    index_urls=["https://pypi.org/simple/"],
)

try:
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: finder.find_all_packages("httpx"), range(8)))
finally:
    fetcher.close()
```
