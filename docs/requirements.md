# Requirement Specifications


The methods `unearth.finder.PackageFinder.find_matches` and `unearth.finder.PackageFinder.find_best_match` accept a requirements specification string or an instance of `packaging.requirements.Requirement` as the first argument.

The requirement string follows the specification of [PEP 508](https://www.python.org/dev/peps/pep-0508/). Here are some examples:


## Named requirements

```
flask
werkzeug >= 1.0
click>=8,<9
```

The [environment markers](https://peps.python.org/pep-0508/#environment-markers) and [extras](https://peps.python.org/pep-0508/#extras), however, don't play any role in the package finding, so they will be simply ignored.

## URL requirements

You can specify a requirement with specific URL to the distribution file by including the URL in the requirement string, in the form of `<name> @ <url>`:

```
# A distribution archive for a package
pip @ https://github.com/pypa/pip/archive/1.3.1.zip#sha1=da9234ee9982d4bbb3c72346a6de940a148ea686
# A local path should be specified as a file:// URL
jinja2 @ file:///path/to/code/jinja2-2.10.zip
# It can even be a file:// URL to a local directory
pytz @ file:///path/to/code/pytz-2018.7
```

## VCS requirements

Same as `pip`, `unearth` also supports requirements specified by VCS URLs. Like URL requirements, the VCS URL follows after the `@` sign. The format is as follows:

```
<name> @ <vcs>+<url>[@ref]
```

where `vcs` can be one of `git`, `hg`, `svn` and `bzr`.

```
# A Git repository on the HEAD revision
django @ git+https://github.com/django/django.git
# A VCS repository specified by SSH URL and a specific ref.
pip @ git+git@github.com:pypa/pip.git@main
pip @ git+git@github.com:pypa/pip.git@22.0.3
pip @ svn+https://github.com/pypa/pip.git@123456
# A Git repository on the accurate commit id
flask @ git+https://github.com/pallets/flask.git@ca8e6217fe450435e024bcff3082d2a37445f7e1
```
