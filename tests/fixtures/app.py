import os
import random
from pathlib import Path

import flask
from packaging.utils import canonicalize_name

BASE_DIR = Path(__file__).parent
bp = flask.Blueprint("main", __name__)

INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Test PyPI Simple Index</title>
</head>
<body>
    <h1>Test PyPI Simple Index</h1>
    {% for package in packages-%}
    <a href="{{ url_for('.package_index', package=package) }}">{{ package }}</a><br/>
    {%-endfor %}
</body>
</html>
"""


@bp.route("/files/<path:path>")
def package_file(path):
    return flask.send_from_directory(BASE_DIR / "files", path)


@bp.route("/simple/<package>")
def package_index(package):
    canonical_name = canonicalize_name(package)
    if package != canonical_name:
        return flask.redirect(flask.url_for(".package_index", package=canonical_name))
    if os.getenv("INDEX_RETURN_TYPE", "html") == "json":
        return flask.send_from_directory(BASE_DIR / "json", package + ".json"), {
            "Content-Type": "application/vnd.pypi.simple.v1+json"
        }
    else:
        content_type = random.choice(
            ["text/html", "application/vnd.pypi.simple.v1+html"]
        )
        return flask.send_from_directory(BASE_DIR / "index", package + ".html"), {
            "Content-Type": content_type
        }


@bp.route("/simple")
def package_index_root():
    packages = sorted(p.stem for p in (BASE_DIR / "index").glob("*.html"))
    if os.getenv("INDEX_RETURN_TYPE", "html") == "json":
        return flask.jsonify(
            {
                "meta": {"api-version": "1.0"},
                "projects": [{"name": p} for p in packages],
            }
        ), {"Content-Type": "application/vnd.pypi.simple.v1+html"}
    return flask.render_template_string(INDEX_TEMPLATE, packages=packages)


@bp.route("/links/index.html")
def find_links():
    return flask.send_from_directory(BASE_DIR / "findlinks", "index.html")


def create_app():
    app = flask.Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(bp)
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(port=8000)
