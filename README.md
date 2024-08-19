# unearth

<!--index start-->

[![Tests](https://github.com/frostming/unearth/workflows/Tests/badge.svg)](https://github.com/frostming/unearth/actions?query=workflow%3Aci)
[![pypi version](https://img.shields.io/pypi/v/unearth.svg)](https://pypi.org/project/unearth/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pdm-managed](https://img.shields.io/endpoint?url=https%3A%2F%2Fcdn.jsdelivr.net%2Fgh%2Fpdm-project%2F.github%2Fbadge.json)](https://pdm-project.org)

A utility to fetch and download python packages

## Why this project?

This project exists as the last piece to complete the puzzle of a package manager. The other pieces are:

- [resolvelib](https://pypi.org/project/resolvelib/) - Resolves concrete dependencies from a set of (abstract) requirements.
- [unearth](https://pypi.org/project/unearth/) _(This project)_ - Finds and downloads the best match(es) for a given requirement.
- [build](https://pypi.org/project/build/) - Builds wheels from the source code.
- [installer](https://pypi.org/project/installer/) - Installs packages from wheels.

They provide all the low-level functionalities that are needed to resolve and install packages.

## Why not pip?

The core functionality is basically extracted from pip. However, pip is not designed to be used as a library and hence the API is not very stable.
Unearth serves as a stable replacement for pip's `PackageFinder` API. It will follow the conventions of [Semantic Versioning](https://semver.org/) so that downstream projects can use it to develop their own package finding and downloading.

## Requirements

unearth requires Python >=3.8

## Installation

```bash
$ python -m pip install --upgrade unearth
```

## Quickstart

Get the best matching candidate for a requirement:

```python
>>> from unearth import PackageFinder
>>> finder = PackageFinder(index_urls=["https://pypi.org/simple/"])
>>> result = finder.find_best_match("flask>=2")
>>> result.best
Package(name='flask', version='2.1.2')
```

Using the CLI:

```bash
$ unearth "flask>=2"
{
  "name": "flask",
  "version": "3.0.0",
  "link": {
    "url": "https://files.pythonhosted.org/packages/36/42/015c23096649b908c809c69388a805a571a3bea44362fe87e33fc3afa01f/flask-3.0.0-py3-none-any.whl",
    "comes_from": "https://pypi.org/simple/flask/",
    "yank_reason": null,
    "requires_python": ">=3.8",
    "metadata": "https://files.pythonhosted.org/packages/36/42/015c23096649b908c809c69388a805a571a3bea44362fe87e33fc3afa01f/flask-3.0.0-py3-none-any.whl.metadata"
  }
}
```

<!--index end-->

## Documentation

[Read the docs](https://unearth.readthedocs.io/en/latest/)
