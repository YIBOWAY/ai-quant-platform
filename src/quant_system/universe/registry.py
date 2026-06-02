from __future__ import annotations

from pydantic import BaseModel, Field


class UniverseDefinition(BaseModel):
    id: str
    name: str
    description: str
    symbols: list[str] = Field(min_length=1)
    benchmark_symbol: str = "SPY"

    def normalized_symbols(self) -> list[str]:
        return [symbol.upper().strip() for symbol in self.symbols if symbol.strip()]


class UniverseRegistry:
    def __init__(self) -> None:
        self._universes: dict[str, UniverseDefinition] = {}

    def register(self, universe: UniverseDefinition) -> None:
        if universe.id in self._universes:
            raise ValueError(f"universe id {universe.id!r} is already registered")
        self._universes[universe.id] = universe

    def universe_ids(self) -> list[str]:
        return list(self._universes)

    def list_metadata(self) -> list[UniverseDefinition]:
        return list(self._universes.values())

    def get(self, universe_id: str) -> UniverseDefinition:
        try:
            return self._universes[universe_id]
        except KeyError as exc:
            raise KeyError(f"unknown universe id {universe_id!r}") from exc


def build_default_universe_registry() -> UniverseRegistry:
    registry = UniverseRegistry()
    registry.register(
        UniverseDefinition(
            id="etf",
            name="ETF Core",
            description="Broad liquid US ETF research universe.",
            symbols=["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE"],
            benchmark_symbol="SPY",
        )
    )
    registry.register(
        UniverseDefinition(
            id="technology",
            name="Technology",
            description="Large US technology and communication-services names.",
            symbols=["AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "META", "AVGO", "ORCL", "CRM"],
            benchmark_symbol="SPY",
        )
    )
    registry.register(
        UniverseDefinition(
            id="defense",
            name="Defense",
            description="US defense and aerospace research universe.",
            symbols=["LMT", "RTX", "NOC", "GD", "HII", "LHX", "BA"],
            benchmark_symbol="SPY",
        )
    )
    registry.register(
        UniverseDefinition(
            id="healthcare",
            name="Healthcare",
            description="Large US healthcare and pharma research universe.",
            symbols=["XLV", "UNH", "JNJ", "PFE", "MRK", "ABBV", "TMO", "MDT", "AMGN"],
            benchmark_symbol="SPY",
        )
    )
    return registry
