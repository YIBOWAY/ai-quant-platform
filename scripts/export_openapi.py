#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

from quant_system.api.server import create_app


def main() -> None:
    output_dir = Path("data/_runtime/openapi-export")
    # create_app configures JSON logging to stdout; keep logs out of the schema stream.
    with redirect_stdout(io.StringIO()):
        schema = create_app(
            output_dir=output_dir,
            bind_address="127.0.0.1",
        ).openapi()
    json.dump(schema, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
