from pathlib import Path


def test_agent_llm_config_uses_backend_response_type_name() -> None:
    api_client = Path("src/frontend/lib/api.ts").read_text(encoding="utf-8")

    assert "export type AgentLLMConfigResponse = ApiEnvelope &" in api_client
    assert "export type AgentLlmConfigResponse = AgentLLMConfigResponse;" in api_client
    assert "apiGet<AgentLLMConfigResponse>" in api_client
