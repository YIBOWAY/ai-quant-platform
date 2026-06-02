import os

# Tests must never touch the real PostgreSQL run index. A developer's local
# .env may enable QS_DATABASE_* and point at a shared Docker container; without
# this override every API test would index its throwaway tmp-dir runs into that
# container, leaving stale rows whose artifacts vanish when the tmp dir is
# cleaned. Forcing the optional database layer off keeps the suite hermetic.
os.environ["QS_DATABASE_ENABLED"] = "false"
