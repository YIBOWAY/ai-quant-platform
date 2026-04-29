from __future__ import annotations

import os

import httpx
from pydantic import SecretStr


class OpenAICompatLLMClient:
    """Small OpenAI-compatible chat-completions client for optional LLM use."""

    def __init__(
        self,
        *,
        api_key: str | SecretStr,
        base_url: str,
        model: str,
        timeout: int = 60,
        http_client: httpx.Client | None = None,
    ) -> None:
        token = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        if not token:
            raise RuntimeError("LLM API key is required for provider openai/xai")
        self.api_key = token
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.http_client = http_client or httpx.Client(timeout=timeout)

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = self.http_client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response did not contain choices[0].message.content") from exc
        if not isinstance(content, str):
            raise RuntimeError("LLM response content must be a string")
        return content


class OpenAIClient(OpenAICompatLLMClient):
    """Backward-compatible CLI client for ``--llm openai``."""

    def __init__(self, *, model: str | None = None) -> None:
        api_key = os.getenv("QS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("QS_OPENAI_API_KEY or OPENAI_API_KEY is required")
        super().__init__(
            api_key=api_key,
            base_url=os.getenv("QS_OPENAI_BASE_URL") or "https://api.openai.com/v1",
            model=(
                model
                or os.getenv("QS_OPENAI_MODEL")
                or os.getenv("OPENAI_MODEL")
                or "gpt-4o-mini"
            ),
        )
