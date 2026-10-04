"""Check the API serialization boundary keeps facts and AI outcomes separate."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from quant_system.api.schemas.research_evaluation import PaperEvaluationResponse


def test_get_keeps_archived_facts_when_ai_failed():
    app = FastAPI()

    @app.get('/evaluation', response_model=PaperEvaluationResponse)
    def read_saved_specimen():
        # Artificial response specimen; no model, market or paper cycle is run.
        return dict(status='failed', facts={'status': 'partial'}, analysis=None,
                    facts_status='partial', interpretation_status='failed',
                    fact_archive_status='archived', fact_archive={'packet_id': 'artificial'})

    saved = TestClient(app).get('/evaluation').json()
    assert saved['facts_status'] == 'partial'
    assert saved['interpretation_status'] == 'failed'
    assert saved['fact_archive_status'] == 'archived'
    assert saved['fact_archive'] == {'packet_id': 'artificial'}
