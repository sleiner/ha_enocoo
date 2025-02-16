"""Defines linting and test tasks."""
# ruff: noqa: S101

import shutil
from functools import cache

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_venv = "yes"

DEFAULT_PYTHON_VERSION = "3.13"


@cache
def uv() -> str:
    """
    Return the path for uv which shall be used.

    homeassistant depends on uv itself, which means that for initial installation
    inside a venv subsequent calls in an existing venv, different uv versions might
    be used. Because of this, we always use the outside uv.
    """
    uv_path = shutil.which("uv")
    assert uv_path, "uv needs to be available outside of the project's venv"
    return uv_path


def _install_dev_dependencies(session: nox.Session) -> None:
    session.run_install(uv(), "sync", "--active", external=True, silent=True)


@nox.session(python=[DEFAULT_PYTHON_VERSION])
def ruff_format(session: nox.Session) -> None:
    """Check code formatting using ruff."""
    _install_dev_dependencies(session)
    session.run("ruff", "format", ".", "--check")


@nox.session(python=[DEFAULT_PYTHON_VERSION])
def ruff_check(session: nox.Session) -> None:
    """Lint code using ruff."""
    _install_dev_dependencies(session)
    session.run("ruff", "check", ".")


@nox.session(python=False)
def lockfile_up_to_date(session: nox.Session) -> None:
    """Check whether uv.lock is up to date."""
    session.run(uv(), "lock", "--check", external=True)


@nox.session(python=[DEFAULT_PYTHON_VERSION])
def test(session: nox.Session) -> None:
    """Run the test suite."""
    _install_dev_dependencies(session)
    session.run("pytest")


@nox.session(python=[DEFAULT_PYTHON_VERSION])
def mypy(session: nox.Session) -> None:
    """Type-check using mypy."""
    _install_dev_dependencies(session)
    session.run("mypy", ".")
