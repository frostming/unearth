# `unearth`

```{eval-rst}
.. argparse::
    :module: unearth.__main__
    :func: cli_parser
    :prog: unearth
```

## Read requirements from a file

Use `-r FILE` or `--requirements FILE` to read a UTF-8 file. Put one PEP 508
requirement on each line. For example:

```text
# requirements.txt
requests==2.32.3
packaging>=24
```

```console
unearth --requirements requirements.txt --download ./packages
```

Use a file or a positional requirement, but not both. Blank lines and comments
are ignored. Start a comment with `#` at the start of a line or after whitespace.
URL fragments and `#` in quoted marker values are preserved.

File input returns a JSON array, even for one requirement. An empty file returns
`[]`. Results follow the input order. By default, each requirement returns its
best match. Use `--all` to return all matches for each requirement in one array.
Use `--link-only` to print links in the same order, with a local path after each
link when `--download` is set.

All entries are checked before package lookup or download. Invalid entries and
requirements with no match report the file name and line number.

This is a flat list of requirements, such as ordinary pinned `pip freeze`
entries. It does not resolve dependencies. Markers and extras are ignored, as
with positional requirements. Named PEP 508 direct references use the existing
finder behavior. This option does not add support for downloading VCS links.

Pip directives, editable entries, constraints, included files, per-line pip
options, and line continuations are not supported. These entries cause an error.
