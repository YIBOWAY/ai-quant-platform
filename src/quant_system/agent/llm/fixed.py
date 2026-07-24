from __future__ import annotations


class FixedContentLLMClient:
    """LLMClient-compatible source for externally generated deterministic content."""

    def __init__(self, content: str) -> None:
        self.content = content

    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        return self.content
