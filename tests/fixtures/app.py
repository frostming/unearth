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
    return flask.send_from_directory(BASE_DIR / "index", package + ".html")


@bp.route("/simple")
def package_index_root():
    packages = [p.stem for p in (BASE_DIR / "index").glob("*.html")]
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
