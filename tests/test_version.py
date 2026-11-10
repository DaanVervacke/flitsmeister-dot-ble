import tomllib
from pathlib import Path

import flitsmeister_dot_ble


def test_pyproject_version_matches_package_version() -> None:
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    assert flitsmeister_dot_ble.__version__ == data["project"]["version"]
