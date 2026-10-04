"""Artificial transport fixtures only; no HTTP or market calls."""

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "sec_pit_pilot.py"
spec = importlib.util.spec_from_file_location("sec_pit_pilot", PATH)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


@pytest.mark.parametrize("mode", [0o644, 0o666])
def test_user_agent_must_be_private(tmp_path, mode):
    path = tmp_path / "private"
    path.write_text("Artificial Test test@example.invalid")
    path.chmod(mode)
    with pytest.raises(ValueError):
        pilot.read_user_agent(path)


def test_request_plan_precedes_request_and_http_rejection_stops_without_retry(tmp_path):
    output = tmp_path / "pilot"
    calls = []

    def rejected(url, user_agent):
        assert json.loads((output / "request-plan.json").read_text())["max_requests"] == 4
        calls.append(url)
        raise HTTPError(url, 403, "Forbidden", {}, None)

    result = pilot.run(output, "Artificial Test test@example.invalid", fetcher=rejected)
    assert len(calls) == result["attempted_requests"] == 1
    assert result["unattempted_requests"] == 3 and result["status"] == "failed"
    assert "test@example.invalid" not in (output / "receipt.json").read_text()
    assert result["requests"][0]["http_status"] == 403


def test_preexisting_output_is_not_overwritten(tmp_path):
    with pytest.raises(ValueError, match="output_must_be_new"):
        pilot.run(tmp_path, "Artificial Test test@example.invalid")


def test_wrong_cik_preserves_response_but_does_not_continue(tmp_path):
    calls = []

    def wrong(url, user_agent):
        calls.append(url)
        return b'{"cik":1045810}', {"http_status": 200}

    result = pilot.run(tmp_path / "pilot", "Artificial Test test@example.invalid", fetcher=wrong)
    assert len(calls) == 1 and result["status"] == "failed"
    assert (tmp_path / "pilot" / "AAPL-submissions.json").read_bytes() == b'{"cik":1045810}'


def make_artificial_closed_run(directory):
    def original(url, user_agent):
        cik = 320193 if "0000320193" in url else 1045810
        symbol = "AAPL" if cik == 320193 else "NVDA"
        data = {"cik": cik}
        if "/submissions/" in url:
            data.update(tickers=[symbol], filings={"recent": {
                "accessionNumber": [], "acceptanceDateTime": [], "filingDate": [], "form": []},
                "files": [{"name": f"CIK{cik:010d}-submissions-001.json"}]})
        else:
            data["facts"] = {"us-gaap": {}}
        return json.dumps(data).encode(), {"http_status": 200}

    return pilot.run(directory, "Artificial Test test@example.invalid", fetcher=original,
                     pause=lambda _: None)


def test_history_only_fetches_two_declared_files_and_leaves_originals(tmp_path):
    old = tmp_path / "old"
    make_artificial_closed_run(old)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    calls = []

    def historical(url, user_agent):
        assert url.endswith("-submissions-001.json")
        assert "/companyfacts/" not in url
        calls.append(url)
        return json.dumps({"accessionNumber": [], "acceptanceDateTime": [],
                           "filingDate": [], "form": []}).encode(), {"http_status": 200}

    result = pilot.run_history(tmp_path / "new", old, "Artificial Test test@example.invalid",
                               fetcher=historical, pause=lambda _: None)
    assert len(calls) == result["attempted_requests"] == 2
    assert result["source_unchanged"] and result["original_input_unchanged"]
    assert result["status"] == "captured_and_normalized"
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}


def test_history_rejects_tampered_original_before_any_request(tmp_path):
    old = tmp_path / "old"
    make_artificial_closed_run(old)
    (old / "AAPL-submissions.json").write_text('{}')

    def forbidden(*args):
        pytest.fail("No network request after original bytes changed")

    with pytest.raises(ValueError, match="source_artifact_changed"):
        pilot.run_history(tmp_path / "new", old, "Artificial Test test@example.invalid",
                           fetcher=forbidden)
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("body", [b'[]', b'null', b'42', b'"bad"'])
def test_malformed_historical_json_closes_failure_receipt_and_retains_raw(tmp_path, body):
    old = tmp_path / "old"
    make_artificial_closed_run(old)

    def malformed(url, user_agent):
        return body, {"http_status": 200}

    result = pilot.run_history(tmp_path / "new", old, "Artificial Test test@example.invalid",
                               fetcher=malformed)
    assert result["status"] == "failed" and result["error_code"] == "response_validation_failed"
    assert result["attempted_requests"] == 1 and result["unattempted_requests"] == 1
    assert (tmp_path / "new" / "CIK0000320193-submissions-001.json").read_bytes() == body
    assert json.loads((tmp_path / "new" / "receipt.json").read_text())["status"] == "failed"
