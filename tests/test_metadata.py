"""Checks for the correctness of the integration's metadata."""

import json
import tomllib
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def pyproject_toml(repo_root: Path) -> dict:
    """Return the content of pyproject.toml."""
    with Path.open(repo_root / "pyproject.toml") as pyproject_toml_file:
        toml_string = pyproject_toml_file.read()
    return tomllib.loads(toml_string)


@pytest.fixture(scope="session")
def hacs_json(repo_root: Path) -> dict:
    """Return the content of hacs.json."""
    with Path.open(repo_root / "hacs.json") as hacs_json_file:
        json_string = hacs_json_file.read()
    return json.loads(json_string)


@pytest.fixture(scope="session")
def manifest_json(integration_root: Path) -> dict:
    """Return the content of manifest.json."""
    with Path.open(integration_root / "manifest.json") as manifest_json_file:
        json_string = manifest_json_file.read()
    return json.loads(json_string)


def test_home_assistant_version_in_sync(hacs_json: dict, pyproject_toml: dict) -> None:
    """The homeassistant version hacs.json and pyproject.toml must be the same."""
    version_from_hacs_json = hacs_json["homeassistant"]

    dev_dependencies = pyproject_toml["tool"]["pdm"]["dev-dependencies"]["dev"]
    prefix = "homeassistant=="
    version_from_pyproject_toml = next(
        dep.removeprefix(prefix) for dep in dev_dependencies if dep.startswith(prefix)
    )
    assert (
        version_from_hacs_json == version_from_pyproject_toml
    ), "hacs.json and pyproject.toml reference different versions of Home Assistant"


def test_integration_version_in_sync(manifest_json: dict, pyproject_toml: dict) -> None:
    """The integration version in manifest.json and pyproject.toml must be the same."""
    version_from_manifest_json = manifest_json["version"]
    version_from_pyproject_toml = pyproject_toml["project"]["version"]
    assert version_from_manifest_json == version_from_pyproject_toml, (
        "manifest.json and pyproject.toml contain different versions"
        " for the current integration"
    )


def test_name_in_sync(hacs_json: dict, manifest_json: dict) -> None:
    """The integration name in manifest.json and pyproject.toml must be the same."""
    name_from_hacs_json = hacs_json["name"]
    name_from_manifest_json = manifest_json["name"]

    assert (
        name_from_hacs_json == name_from_manifest_json
    ), "The integration is named differently in hacs.json and manifest.json"

    # The name in pyproject.toml is allowed to be different
