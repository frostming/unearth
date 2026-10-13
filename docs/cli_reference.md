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

Use a file or a positional requirement, but not both. The CLI ignores blank lines
and comments. Start a comment with `#` at the start of a line or after whitespace.
The CLI preserves URL fragments and `#` in quoted marker values.

File input returns a JSON array, even for one requirement. An empty file returns
`[]`. Results follow the input order. By default, each requirement returns its
best match. Use `--all` to return all matches for each requirement in one array.
Use `--link-only` to print links in the same order, with a local path after each
link when you set `--download`.

The CLI checks all entries before package lookup or download. It reports the file
name and line number for invalid entries and requirements with no match.

This is a flat list of requirements, such as ordinary pinned `pip freeze`
entries. It does not resolve dependencies. The finder ignores markers and extras,
as with positional requirements. Named PEP 508 direct references use the existing
finder behavior. This option does not add support for downloading VCS links.

The CLI does not support pip directives, editable entries, constraints, included
files, per-line pip options, or line continuations. These entries cause an error.
