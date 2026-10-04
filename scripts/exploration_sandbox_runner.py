"""Container-only factor adapter. Its output is untrusted and checked by the host."""

from __future__ import annotations

import contextlib
import json
import os
import random
import sys

import numpy as np
import pandas as pd


def main():
    with open("/input/request.json", encoding="utf-8") as handle:
        request = json.load(handle)
    random.seed(1729)
    np.random.seed(1729)
    frame = pd.DataFrame(request["ohlcv"])
    for column in ("timestamp", "available_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    try:
        namespace = {"__name__": "exploration_factor"}
        # No static source inspection is used as an execution safety boundary.
        with open(os.devnull, "w") as quiet, contextlib.redirect_stdout(quiet):
            with open("/input/factor.py", encoding="utf-8") as handle:
                exec(compile(handle.read(), "/input/factor.py", "exec"), namespace)  # noqa: S102
            result = namespace["compute"](frame, request["context"])
            if not isinstance(result, pd.DataFrame):
                raise TypeError("compute must return a DataFrame")
            if list(result.columns) != ["symbol", "timestamp", "score"]:
                raise ValueError("invalid score columns")
            if not np.isfinite(pd.to_numeric(result.score.dropna(), errors="raise")).all():
                raise ValueError("nonfinite score")
            scores = json.loads(
                result.to_json(orient="records", date_format="iso", double_precision=15)
            )
        response = {"status": "ok", "scores": scores}
    except BaseException as exc:
        # Never echo arbitrary source exception text or data back into logs.
        response = {"status": "error", "error_type": type(exc).__name__}
    sys.stdout.write(json.dumps(response, allow_nan=False))


if __name__ == "__main__":
    main()
