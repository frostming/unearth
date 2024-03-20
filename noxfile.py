import os

import nox

os.environ.update(PDM_IGNORE_SAVED_PYTHON="1", PDM_USE_VENV="1")


@nox.session(python=("3.8", "3.9", "3.10", "3.11", "3.12"))
def test(session):
    session.run("pdm", "install", "-Gtest", external=True)
    session.run("pytest", "tests/")


@nox.session(python="3.11")
def docs(session):
    session.run("pdm", "install", "-Gdoc", external=True)

    # Generate documentation into `build/docs`
    session.run("sphinx-build", "-n", "-W", "-b", "html", "docs/", "build/docs")


@nox.session(name="docs-live", python="3.11")
def docs_live(session):
    session.run("pdm", "install", "-Gdoc", external=True)
    session.install("sphinx-autobuild")

    session.run(
        "sphinx-autobuild",
        "docs/",
        "build/docs",
        # Rebuild all files when rebuilding
        "-a",
        # Trigger rebuilds on code changes (for autodoc)
        "--watch",
        "src/unearth",
        # Use a not-common high-numbered port
        "--port",
        "8765",
    )
