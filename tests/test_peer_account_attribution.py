"""Unknown ownership in a real artificial account cannot prove an empty peer."""
import json

import pytest

from quant_system.execution import assistant_remote as remote
from tests.test_assistant_remote import _tree_hash
from tests.test_capital_peer_holdings import _allocation_count, _setup_history


@pytest.mark.parametrize('sources', [None, {}, {'manual': 49.0}, {'manual': -50.0}])
def test_incomplete_account_source_partition_cannot_remove_peer(tmp_path, monkeypatch, sources):
    settings, candidate, peer, storage, accounts = _setup_history(
        tmp_path, monkeypatch, traded=True,
    )
    storage.save_sleeve_lots(peer['sleeve_id'], [])
    raw = json.loads(accounts.account_path.read_text())
    assert raw['positions']['AAPL']['quantity'] == 50.0
    if sources is None:
        raw['positions']['AAPL'].pop('source_quantity')
    else:
        raw['positions']['AAPL']['source_quantity'] = sources
    accounts.account_path.write_text(json.dumps(raw))
    before, count = _tree_hash(tmp_path), _allocation_count(accounts)
    with pytest.raises(remote.AssistantRemoteError, match='peer_account_unavailable'):
        remote.hang_candidate(settings, candidate_id=candidate['candidate_id'],
                              expected_source_digest=candidate['source_digest'])
    assert _allocation_count(accounts) == count
    assert _tree_hash(tmp_path) == before
