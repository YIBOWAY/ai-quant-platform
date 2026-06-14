from pathlib import Path

import yaml


def test_environment_installs_api_and_dev_extras() -> None:
    environment = yaml.safe_load(Path("environment.yml").read_text(encoding="utf-8"))
    pip_dependencies = next(
        item["pip"]
        for item in environment["dependencies"]
        if isinstance(item, dict) and "pip" in item
    )

    assert "-e .[api,dev]" in pip_dependencies
