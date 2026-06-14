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


def test_configure_logging_can_write_jsonl_file(tmp_path) -> None:
    logger = configure_logging(level="INFO", log_dir=tmp_path)

    logger.warning("runtime-check", extra={"component": "test"})

    log_path = tmp_path / "backend.jsonl"
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["level"] == "WARNING"
    assert record["message"] == "runtime-check"
    assert record["component"] == "test"
    assert record["logger"] == "quant_system"
    assert len(logging.getLogger("quant_system").handlers) == 2
