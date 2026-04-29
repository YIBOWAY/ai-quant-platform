from quant_system.agent.llm.base import LLMClient
from quant_system.agent.llm.openai_client import OpenAICompatLLMClient
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.config.settings import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    """Build the configured LLM client without giving agents trading permissions."""

    if settings.llm.provider == "stub":
        return StubLLMClient()
    if settings.llm.api_key is None:
        raise RuntimeError("LLM_API_KEY or QS_LLM_API_KEY is required for provider openai/xai")
    if not settings.llm.model:
        raise RuntimeError("LLM_MODEL or QS_LLM_MODEL is required for provider openai/xai")
    return OpenAICompatLLMClient(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url or "https://api.openai.com/v1",
        model=settings.llm.model,
        timeout=settings.llm.timeout,
    )


__all__ = ["LLMClient", "OpenAICompatLLMClient", "StubLLMClient", "build_llm_client"]
