from __future__ import annotations


class InstrumentMapper:
    """Pure stub mapping between condition/outcome coordinates and token ids."""

    @staticmethod
    def to_token_id(*, condition_id: str, outcome_index: int) -> str:
        return f"{condition_id}:outcome:{outcome_index}"

    @staticmethod
    def from_token_id(token_id: str) -> tuple[str, int]:
        try:
            condition_id, _, outcome_index = token_id.rpartition(":outcome:")
            return condition_id, int(outcome_index)
        except ValueError as exc:
            raise ValueError(f"token_id {token_id!r} is not a stub token id") from exc
