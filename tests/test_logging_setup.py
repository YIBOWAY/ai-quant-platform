import json
import logging

from quant_system.logging.setup import configure_logging


def test_configure_logging_outputs_json_record(capsys) -> None:
    logger = configure_logging(level="INFO")

    logger.info("phase0-check", extra={"component": "test"})
    captured = capsys.readouterr()

    record = json.loads(captured.out.strip())
    assert record["level"] == "INFO"
    assert record["message"] == "phase0-check"
    assert record["component"] == "test"
    assert record["logger"] == "quant_system"


def test_configure_logging_is_idempotent() -> None:
    first = configure_logging(level="INFO")
    second = configure_logging(level="DEBUG")

    assert first is second
    assert len(logging.getLogger("quant_system").handlers) == 1
    assert logging.getLogger("quant_system").level == logging.DEBUG

