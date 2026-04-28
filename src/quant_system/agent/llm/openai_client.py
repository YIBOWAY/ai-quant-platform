from __future__ import annotations

import os


class OpenAIClient:
    """Optional OpenAI client, only constructed when explicitly requested."""

    def __init__(self, *, model: str | None = None) -> None:
        api_key = os.getenv("QS_OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("QS_OPENAI_API_KEY is required when --llm openai is used")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI client is not installed. Install the optional OpenAI SDK "
                "before using --llm openai."
            ) from exc
        self.client = OpenAI(api_key=api_key)
        self.model = model or os.getenv("QS_OPENAI_MODEL", "gpt-4o-mini")

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        return response.output_text
