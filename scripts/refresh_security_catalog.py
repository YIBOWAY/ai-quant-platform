"""Import the pinned, public US security directory. Does not request market quotes."""

import json

from quant_system.config.settings import load_settings
from quant_system.data.security_catalog import refresh_catalog

if __name__ == "__main__":
    print(json.dumps(refresh_catalog(load_settings()), ensure_ascii=False))
