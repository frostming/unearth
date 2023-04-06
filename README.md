# unearth

<!--index start-->

[![Tests](https://github.com/frostming/unearth/workflows/Tests/badge.svg)](https://github.com/frostming/unearth/actions?query=workflow%3Aci)
[![pypi version](https://img.shields.io/pypi/v/unearth.svg)](https://pypi.org/project/unearth/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pdm-managed](https://img.shields.io/badge/pdm-managed-blueviolet)](https://pdm.fming.dev)

A utility to fetch and download python packages

> _NOTICE_ This project is still in its early stage and the API may change before 1.0 release.

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

unearth requires Python >=3.7

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
>>> result.best_candidate
Package(name='flask', version='2.1.2', link=<Link https://files.pythonhosted.org/packages/ba/76/e9580e494eaf6f09710b0f3b9000c9c0363e44af5390be32bb0394165853/Flask-2.1.2-py3-none-any.whl#sha256=fad5b446feb0d6db6aec0c3184d16a8c1f6c3e464b511649c8918a9be100b4fe (from https://pypi.org/simple/flask)>)
```

Using the CLI:

```bash
$ unearth "flask>=2"
{
  "name": "flask",
  "version": "2.1.2",
  "link": {
    "url": "https://files.pythonhosted.org/packages/ba/76/e9580e494eaf6f09710b0f3b9000c9c0363e44af5390be32bb0394165853/Flask-2.1.2-py3-none-any.whl#sha256=fad5b446feb0d6db6aec0c3184d16a8c1f6c3e464b511649c8918a9be100b4fe",
    "comes_from": "https://pypi.org/simple/flask",
    "yank_reason": null,
    "requires_python": ">=3.7"
  }
}
```

<!--index end-->

## Documentation

[Read the docs](https://unearth.readthedocs.io/en/latest/)
