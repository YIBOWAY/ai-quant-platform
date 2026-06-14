import os
import sys

# Keep this guard even though the package metadata requires Python 3.11+:
# when pytest is launched from the wrong interpreter, this gives the user a
# direct ai-quant recovery command instead of a long import-error cascade.
if sys.version_info < (3, 11):  # noqa: UP036
    raise RuntimeError(
        "Python 3.11+ is required for this project. Use the ai-quant environment: "
        "conda activate ai-quant; python -m pytest -q"
    )

# Tests must never touch the real PostgreSQL run index. A developer's local
# .env may enable QS_DATABASE_* and point at a shared Docker container; without
# this override every API test would index its throwaway tmp-dir runs into that
# container, leaving stale rows whose artifacts vanish when the tmp dir is
# cleaned. Forcing the optional database layer off keeps the suite hermetic.
os.environ["QS_DATABASE_ENABLED"] = "false"
