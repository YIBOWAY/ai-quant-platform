from __future__ import annotations

from typing import Protocol


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate text from a prompt."""
