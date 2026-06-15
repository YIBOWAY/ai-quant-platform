from pathlib import Path

import yaml

from quant_system.config.settings import DataSettings


def test_environment_installs_api_and_dev_extras() -> None:
    environment = yaml.safe_load(Path("environment.yml").read_text(encoding="utf-8"))
    pip_dependencies = next(
        item["pip"]
        for item in environment["dependencies"]
        if isinstance(item, dict) and "pip" in item
    )

    assert "-e .[api,dev]" in pip_dependencies


def test_env_example_default_provider_matches_code_default() -> None:
    env_lines = Path(".env.example").read_text(encoding="utf-8").splitlines()
    provider_line = next(
        line for line in env_lines if line.startswith("QS_DEFAULT_DATA_PROVIDER=")
    )

    _, raw_value = provider_line.split("=", maxsplit=1)
    example_default = raw_value.strip().strip('"')

    assert example_default == DataSettings().default_data_provider
