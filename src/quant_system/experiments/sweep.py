from __future__ import annotations

from itertools import product

from quant_system.experiments.models import ParameterCombination


def expand_parameter_grid(
    sweep: dict[str, list[int | float | str]],
) -> list[ParameterCombination]:
    if not sweep:
        return [ParameterCombination(run_id="run-001", parameters={})]

    keys = sorted(sweep)
    value_lists = [sweep[key] for key in keys]
    combinations: list[ParameterCombination] = []
    for index, values in enumerate(product(*value_lists), start=1):
        combinations.append(
            ParameterCombination(
                run_id=f"run-{index:03d}",
                parameters=dict(zip(keys, values, strict=True)),
            )
        )
    return combinations
